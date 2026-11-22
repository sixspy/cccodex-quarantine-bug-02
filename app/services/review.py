from __future__ import annotations

import sqlite3

from app.db import get_db
from app.services import audit as audit_svc
from app.services import release_ledger
from app.services.errors import ServiceError


def list_tickets(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT t.*, r.status AS row_status, r.reason, i.item_key,
                   i.id AS item_id, b.bin_code,
                   l.id AS ledger_id, l.fingerprint, l.channel
            FROM review_tickets t
            JOIN quarantine_rows r ON r.id=t.row_id
            JOIN capture_items i ON i.id=r.item_id
            JOIN quarantine_bins b ON b.id=r.bin_id
            LEFT JOIN release_ledger l ON l.ticket_id=t.id
            ORDER BY t.id DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def decide(
    ticket_id: int,
    decision: str,
    reviewer: str = "admin",
    comment: str = "",
    db_path: str | None = None,
) -> dict:
    if decision not in ("放行", "驳回回炉", "废弃"):
        raise ServiceError("裁决无效")
    with get_db(db_path) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            raise ServiceError("复核单正由另一仓管处理，请刷新后重试", 409)
        ticket = conn.execute(
            "SELECT * FROM review_tickets WHERE id=?", (ticket_id,)
        ).fetchone()
        if not ticket:
            raise ServiceError("复核单不存在", 404)
        if ticket["decision"] != "待决":
            raise ServiceError("复核单已裁决，禁止重复放行", 409)
        row = conn.execute(
            "SELECT * FROM quarantine_rows WHERE id=?", (ticket["row_id"],)
        ).fetchone()
        if not row or row["status"] != "待复核":
            raise ServiceError("隔离行不可裁决")
        item = conn.execute(
            "SELECT * FROM capture_items WHERE id=?", (row["item_id"],)
        ).fetchone()
        if not item:
            raise ServiceError("抓取条目不存在", 404)

        # 原子认领：条件更新命中 0 行即说明已被另一仓管抢先
        cur = conn.execute(
            """
            UPDATE review_tickets
            SET decision=?, reviewer=?, comment=?, decided_at=datetime('now')
            WHERE id=? AND decision='待决'
            """,
            (decision, reviewer or "admin", comment or "", ticket_id),
        )
        if cur.rowcount != 1:
            raise ServiceError("复核单已被另一仓管抢先裁决", 409)

        if decision == "放行":
            # 放行当刻：条目键 + 放行指纹落入只追加账册（落点）
            entry = release_ledger._append_release_conn(
                conn,
                ticket_id=ticket_id,
                row_id=row["id"],
                item_id=item["id"],
                item_key=item["item_key"],
                reviewer=reviewer or "admin",
                channel="复核放行",
            )
            conn.execute(
                "UPDATE quarantine_rows SET status='已放行' WHERE id=?", (row["id"],)
            )
            # 抓取侧改读放行新旗：不再挂“入舱/待复核”
            conn.execute(
                "UPDATE capture_items SET status='已放行' WHERE id=?", (item["id"],)
            )
            fp = entry["fingerprint"]
        elif decision == "驳回回炉":
            conn.execute(
                "UPDATE quarantine_rows SET status='回炉中' WHERE id=?", (row["id"],)
            )
            conn.execute(
                "UPDATE capture_items SET status='回炉中' WHERE id=?", (item["id"],)
            )
            n = conn.execute("SELECT COUNT(*) AS c FROM rework_jobs").fetchone()["c"] + 1
            conn.execute(
                """
                INSERT INTO rework_jobs(job_code, row_id, status, message)
                VALUES (?, ?, '排队', '复核驳回进入回炉')
                """,
                (f"RWK-{n:04d}", row["id"]),
            )
            fp = None
        else:
            conn.execute(
                "UPDATE quarantine_rows SET status='已废弃' WHERE id=?", (row["id"],)
            )
            conn.execute(
                "UPDATE capture_items SET status='已关闭' WHERE id=?", (item["id"],)
            )
            fp = None
        out = conn.execute(
            """
            SELECT t.*, r.status AS row_status, i.item_key, i.status AS item_status,
                   l.id AS ledger_id, l.fingerprint
            FROM review_tickets t
            JOIN quarantine_rows r ON r.id=t.row_id
            JOIN capture_items i ON i.id=r.item_id
            LEFT JOIN release_ledger l ON l.ticket_id=t.id
            WHERE t.id=?
            """,
            (ticket_id,),
        ).fetchone()
        result = dict(out)
    audit_svc.write_event(
        "复核裁决",
        "review_ticket",
        ticket_id,
        decision + (f"｜放行指纹 {fp}" if fp else ""),
        db_path=db_path,
    )
    return result
