"""quarantine-bug-02：回炉渠道落账、对账联验与指纹闸门。"""
from __future__ import annotations

import pytest

from app.services import captures, quarantine, reconcile, review, rework
from app.services import release_ledger as ledger


@pytest.fixture()
def rework_ticket(db_path):
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
    review.decide(ticket["id"], "驳回回炉", "keeper-a", "回炉重抓", db_path)
    job = next(j for j in rework.list_jobs(db_path) if j["row_id"] == row["id"])
    return row["id"], ticket["id"], bad["id"], bad["item_key"], job["id"]


def test_rework_success_appends_ledger_and_flips_item(rework_ticket, db_path):
    row_id, ticket_id, item_id, item_key, job_id = rework_ticket
    assert ledger.released_count(db_path) == 0

    rework.run_job(job_id, succeed=True, db_path=db_path)

    entries = ledger.list_entries(db_path)
    assert len(entries) == 1
    e = entries[0]
    assert e["item_id"] == item_id
    assert e["item_key"] == item_key
    assert e["channel"] == "回炉成功"
    assert e["fingerprint"]

    from app.db import get_db
    with get_db(db_path) as conn:
        status = conn.execute(
            "SELECT status FROM capture_items WHERE id=?", (item_id,)
        ).fetchone()["status"]
    assert status == "已放行"
    assert ledger.gate_status(item_id, db_path=db_path)["allowed"] is True


def test_reconcile_counts_released_and_reports_gate_block(rework_ticket, db_path):
    row_id, ticket_id, item_id, item_key, job_id = rework_ticket
    rework.run_job(job_id, succeed=True, db_path=db_path)

    report = reconcile.run_reconcile(db_path)
    assert report["released"] == 1
    # 放行后抓取侧不再产生“入舱悬空”错位
    assert report["mismatch"] == 0
    assert report["gate_blocked"] == 0

    # 拧花指纹后再对账：编排拦截数被摘要带出
    entry = ledger.list_entries(db_path)[0]
    from app.db import get_db
    with get_db(db_path) as conn:
        conn.execute("DROP TRIGGER IF EXISTS trg_release_ledger_no_update")
        conn.execute("DROP TRIGGER IF EXISTS trg_release_ledger_no_delete")
        conn.execute(
            "UPDATE release_ledger SET fingerprint='x' WHERE id=?", (entry["id"],)
        )
    try:
        report2 = reconcile.run_reconcile(db_path)
        assert report2["gate_blocked"] == 1
        assert item_id in report2["blocked_item_ids"]
    finally:
        ledger.install_guard_triggers(db_path)


def test_capture_review_cross_check_agrees(rework_ticket, db_path):
    """复核详情联验抓取列表：同一 item_key 的落点与抓取状态必须对得上。"""
    row_id, ticket_id, item_id, item_key, job_id = rework_ticket
    rework.run_job(job_id, succeed=True, db_path=db_path)

    tickets = review.list_tickets(db_path)
    t = next(x for x in tickets if x["id"] == ticket_id)
    assert t["ledger_id"] is not None
    assert t["fingerprint"]

    from app.db import get_db
    with get_db(db_path) as conn:
        batch_id = conn.execute(
            "SELECT batch_id FROM capture_items WHERE id=?", (item_id,)
        ).fetchone()["batch_id"]
    batch = captures.get_batch(batch_id, db_path)
    marked = next(i for i in batch["items"] if i["id"] == item_id)
    assert marked["status"] == "已放行"
    assert marked["release"]["fingerprint"] == t["fingerprint"]
    assert marked["release"]["item_key"] == item_key == t["item_key"]
    assert batch["released_count"] == 1
