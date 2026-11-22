"""放行落点账册（旁路切流账册，单轨）。

- 放行当刻把条目键与放行指纹只追加进 ``release_ledger``；
- 表上触发器禁 UPDATE/DELETE（禁回刷），服务层不开放任何改写路径；
- 抓取侧与清洗编排以本账册为放行新旗的唯一读轨；
- 指纹由当刻不可变字段算出，被拧花即判脏，闸门拦件。
"""
from __future__ import annotations

import hashlib
import sqlite3

from app.db import get_db
from app.services.errors import ServiceError

_CHANNELS = ("复核放行", "回炉成功")

_GUARD_SQL = (
    """
    CREATE TRIGGER IF NOT EXISTS trg_release_ledger_no_update
    BEFORE UPDATE ON release_ledger
    BEGIN
      SELECT RAISE(ABORT, '放行账册禁回刷：不允许更新');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_release_ledger_no_delete
    BEFORE DELETE ON release_ledger
    BEGIN
      SELECT RAISE(ABORT, '放行账册禁回刷：不允许删除');
    END
    """,
)


def install_guard_triggers(db_path: str | None = None) -> None:
    """重装禁回刷触发器（破坏注入测试后用于恢复防护）。"""
    with get_db(db_path) as conn:
        for stmt in _GUARD_SQL:
            conn.execute(stmt)


def compute_fingerprint(
    ticket_id: int,
    row_id: int,
    item_id: int,
    item_key: str,
    channel: str,
    reviewer: str,
    created_at: str,
) -> str:
    """按放行当刻的不可变字段计算放行指纹。"""
    raw = "|".join(
        [
            str(ticket_id),
            str(row_id),
            str(item_id),
            item_key or "",
            channel,
            reviewer or "",
            created_at or "",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _expected_fp(conn, row: sqlite3.Row) -> str:
    return compute_fingerprint(
        row["ticket_id"],
        row["row_id"],
        row["item_id"],
        row["item_key"],
        row["channel"],
        row["reviewer"],
        row["created_at"],
    )


def _append_release_conn(
    conn,
    *,
    ticket_id: int,
    row_id: int,
    item_id: int,
    item_key: str,
    reviewer: str = "",
    channel: str = "复核放行",
) -> dict:
    """在调用方已持有的连接/事务内只追加一条放行落点。"""
    if channel not in _CHANNELS:
        raise ServiceError("放行渠道无效")
    dup = conn.execute(
        """
        SELECT id FROM release_ledger
        WHERE ticket_id=? OR row_id=? OR item_id=?
        """,
        (ticket_id, row_id, item_id),
    ).fetchone()
    if dup:
        raise ServiceError("已存在放行落点，禁止重复回刷", 409)
    created_at = conn.execute("SELECT datetime('now') AS now").fetchone()["now"]
    fp = compute_fingerprint(
        ticket_id, row_id, item_id, item_key, channel, reviewer, created_at
    )
    try:
        cur = conn.execute(
            """
            INSERT INTO release_ledger(
              ticket_id, row_id, item_id, item_key, fingerprint,
              channel, reviewer, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket_id,
                row_id,
                item_id,
                item_key,
                fp,
                channel,
                reviewer or "",
                created_at,
            ),
        )
    except sqlite3.IntegrityError as exc:
        msg = str(exc)
        if "locked" in msg.lower():
            raise ServiceError("放行落点正由另一仓管处理，请刷新后重试", 409)
        raise ServiceError("已存在放行落点，禁止重复回刷", 409)
    entry = conn.execute(
        "SELECT * FROM release_ledger WHERE id=?", (cur.lastrowid,)
    ).fetchone()
    return dict(entry)


def append_release(
    *,
    ticket_id: int,
    row_id: int,
    item_id: int,
    item_key: str,
    reviewer: str = "",
    channel: str = "复核放行",
    db_path: str | None = None,
) -> dict:
    """只追加一条放行落点；同一复核单/隔离行/条目重复追加即拒（禁回刷、排他）。"""
    with get_db(db_path) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            raise ServiceError("放行落点正由另一仓管处理，请刷新后重试", 409)
        return _append_release_conn(
            conn,
            ticket_id=ticket_id,
            row_id=row_id,
            item_id=item_id,
            item_key=item_key,
            reviewer=reviewer,
            channel=channel,
        )


def list_entries(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM release_ledger ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def entry_for_item(item_id: int, db_path: str | None = None) -> dict | None:
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM release_ledger WHERE item_id=?", (item_id,)
        ).fetchone()
        return dict(row) if row else None


def released_count(db_path: str | None = None) -> int:
    with get_db(db_path) as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM release_ledger").fetchone()["c"]


def gate_status(item_id: int, db_path: str | None = None) -> dict:
    """清洗编排闸门：无账册件不在放行轨；指纹拧花即挡。"""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM release_ledger WHERE item_id=?", (item_id,)
        ).fetchone()
        if not row:
            return {"allowed": False, "reason": "无放行落点，继续按待复核拦截"}
        expect = _expected_fp(conn, row)
        if row["fingerprint"] != expect:
            return {"allowed": False, "reason": "放行指纹校验失败：指纹被拧花，拦截编排继续执行"}
        return {
            "allowed": True,
            "reason": "放行指纹一致",
            "fingerprint": row["fingerprint"],
            "entry_id": row["id"],
        }


def blocked_item_ids(db_path: str | None = None) -> list[int]:
    """返回账册内指纹已脏、必须被编排挡住的条目 id。"""
    blocked: list[int] = []
    with get_db(db_path) as conn:
        rows = conn.execute("SELECT * FROM release_ledger").fetchall()
        for row in rows:
            if row["fingerprint"] != _expected_fp(conn, row):
                blocked.append(row["item_id"])
    return blocked


def gate_summary(db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        rows = conn.execute("SELECT * FROM release_ledger").fetchall()
        blocked = [
            row["item_id"] for row in rows if row["fingerprint"] != _expected_fp(conn, row)
        ]
        return {
            "released_count": len(rows),
            "blocked_count": len(blocked),
            "blocked_item_ids": blocked,
        }
