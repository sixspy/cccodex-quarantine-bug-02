"""quarantine-bug-02：放行落点账册（切流账册单轨）红→绿测试。

覆盖：
- 复核放行后抓取侧翻「已放行」，且放行当刻条目键与放行指纹落入只追加账册；
- 账册禁回刷（无 UPDATE/DELETE 路径，重复追加被挡）；
- 两名仓管并发放行同一复核单，仅一人成功（排他）；
- 放行指纹被拧花时，清洗编排闸门拦住该件。
"""
from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.db import get_db
from app.services import captures, quarantine, review
from app.services import release_ledger as ledger
from app.services.errors import ServiceError


@pytest.fixture()
def open_ticket(db_path):
    """造一条待复核坏件，返回 (row_id, ticket_id, item_id, item_key)。"""
    batches = captures.list_batches(db_path)
    batch = next(b for b in batches if b["status"] != "已关闭")
    bins = quarantine.list_bins(db_path)
    open_bin = next(b for b in bins if b["status"] == "开放")
    detail = captures.get_batch(batch["id"], db_path)
    bad = next(i for i in detail["items"] if i["quality"] != "合格" and i["status"] == "待检")
    row = quarantine.enter_item(bad["id"], open_bin["id"], "测试入舱", db_path)
    ticket = next(
        t for t in review.list_tickets(db_path)
        if t["row_id"] == row["id"] and t["decision"] == "待决"
    )
    return row["id"], ticket["id"], bad["id"], bad["item_key"]


# ---------- 第 1 段：放行落点 ----------

def test_release_writes_ledger_and_flips_capture(open_ticket, db_path):
    row_id, ticket_id, item_id, item_key = open_ticket
    out = review.decide(ticket_id, "放行", "keeper-a", "核验无误", db_path)

    assert out["decision"] == "放行"

    # 抓取侧不再挂“入舱/待复核”，必须翻成已放行
    detail = captures.get_batch(
        captures.list_batches(db_path)[0]["id"], db_path
    ) if False else None
    with get_db(db_path) as conn:
        item = conn.execute(
            "SELECT status FROM capture_items WHERE id=?", (item_id,)
        ).fetchone()
        qrow = conn.execute(
            "SELECT status FROM quarantine_rows WHERE id=?", (row_id,)
        ).fetchone()
    assert item["status"] == "已放行"
    assert qrow["status"] == "已放行"

    # 放行当刻条目键 + 放行指纹必须有落点行
    entries = ledger.list_entries(db_path)
    assert len(entries) == 1
    e = entries[0]
    assert e["item_key"] == item_key
    assert e["item_id"] == item_id
    assert e["ticket_id"] == ticket_id
    assert e["channel"] == "复核放行"
    assert e["fingerprint"]
    assert e["created_at"]


def test_ledger_is_append_only_no_backfill(open_ticket, db_path):
    _, ticket_id, _, _ = open_ticket
    review.decide(ticket_id, "放行", "keeper-a", "", db_path)

    first = ledger.list_entries(db_path)[0]

    # 服务层不提供回刷路径；对同一复核单二次追加必须被挡
    with pytest.raises(ServiceError) as exc:
        ledger.append_release(
            ticket_id=ticket_id,
            row_id=first["row_id"],
            item_id=first["item_id"],
            item_key=first["item_key"],
            reviewer="keeper-b",
            channel="复核放行",
            db_path=db_path,
        )
    assert "已存在放行落点" in exc.value.message

    # 账册行原样未动（禁回刷）
    again = ledger.list_entries(db_path)
    assert len(again) == 1
    assert again[0]["fingerprint"] == first["fingerprint"]
    assert again[0]["reviewer"] == "keeper-a"

    # 直接 SQL 改写也不允许（触发器兜底）
    with get_db(db_path) as conn:
        with pytest.raises(sqlite3.Error):
            conn.execute(
                "UPDATE release_ledger SET reviewer='x' WHERE id=?", (first["id"],)
            )
        with pytest.raises(sqlite3.Error):
            conn.execute("DELETE FROM release_ledger WHERE id=?", (first["id"],))


def test_concurrent_release_only_one_wins(open_ticket, db_path):
    row_id, ticket_id, item_id, item_key = open_ticket
    errors: list[str] = []

    def release(reviewer: str) -> str:
        try:
            review.decide(ticket_id, "放行", reviewer, "并发抢放", db_path)
            return "ok"
        except ServiceError as exc:
            errors.append(exc.message)
            return "fail"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(release, ["keeper-a", "keeper-b"]))

    assert sorted(results) == ["fail", "ok"]
    assert len(ledger.list_entries(db_path)) == 1
    assert any("已裁决" in m or "已存在放行落点" in m or "正在处理" in m for m in errors)

    with get_db(db_path) as conn:
        cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM release_ledger WHERE ticket_id=?", (ticket_id,)
        ).fetchone()["c"]
        item_status = conn.execute(
            "SELECT status FROM capture_items WHERE id=?", (item_id,)
        ).fetchone()["status"]
    assert cnt == 1
    assert item_status == "已放行"


# ---------- 第 2 段：指纹闸门 ----------

def test_tampered_fingerprint_blocks_pipeline(open_ticket, db_path):
    row_id, ticket_id, item_id, item_key = open_ticket
    review.decide(ticket_id, "放行", "keeper-a", "", db_path)
    entry = ledger.list_entries(db_path)[0]

    # 正常状态：闸门放行该件
    assert ledger.gate_status(item_id, db_path=db_path)["allowed"] is True

    # 指纹被拧花（绕过服务层直接改库模拟外部破坏；触发器只挡账册表自身的常规改写，
    # 这里临时撤触发器做破坏注入，再恢复）
    with get_db(db_path) as conn:
        conn.execute("DROP TRIGGER IF EXISTS trg_release_ledger_no_update")
        conn.execute("DROP TRIGGER IF EXISTS trg_release_ledger_no_delete")
        conn.execute(
            "UPDATE release_ledger SET fingerprint='tampered-fp' WHERE id=?",
            (entry["id"],),
        )
    try:
        gate = ledger.gate_status(item_id, db_path=db_path)
        assert gate["allowed"] is False
        assert "指纹" in gate["reason"]

        blocked = ledger.blocked_item_ids(db_path)
        assert item_id in blocked
    finally:
        # 恢复触发器，保证后续连接仍受禁回刷保护
        ledger.install_guard_triggers(db_path)


def test_released_count_on_capture_side(open_ticket, db_path):
    row_id, ticket_id, item_id, item_key = open_ticket
    assert ledger.released_count(db_path) == 0
    review.decide(ticket_id, "放行", "keeper-a", "", db_path)
    assert ledger.released_count(db_path) == 1

    # 批次详情携带已放行件数与逐条放行落点
    with get_db(db_path) as conn:
        batch_id = conn.execute(
            "SELECT batch_id FROM capture_items WHERE id=?", (item_id,)
        ).fetchone()["batch_id"]
    batch = captures.get_batch(batch_id, db_path)
    assert batch["released_count"] == 1
    marked = next(i for i in batch["items"] if i["id"] == item_id)
    assert marked["status"] == "已放行"
    assert marked["release"] is not None
    assert marked["release"]["item_key"] == item_key
    assert marked["release"]["fingerprint"]
