from __future__ import annotations

from app.db import get_db
from app.services.errors import ServiceError

# 只读放行口径：只允许展示，不允许台参接口改写
READONLY_KEYS = frozenset({"release_read_track"})


def list_settings(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value, label FROM lab_settings ORDER BY key"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["readonly"] = 1 if d["key"] in READONLY_KEYS else 0
            out.append(d)
        return out


def update_setting(key: str, value: str, db_path: str | None = None) -> dict:
    if not key or value is None:
        raise ServiceError("参数不完整")
    if key in READONLY_KEYS:
        raise ServiceError("放行口径为只读参数，禁止修改", 400)
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT key, value, label FROM lab_settings WHERE key=?", (key,)
        ).fetchone()
        if not row:
            raise ServiceError("设置项不存在", 404)
        conn.execute("UPDATE lab_settings SET value=? WHERE key=?", (str(value), key))
        out = conn.execute(
            "SELECT key, value, label FROM lab_settings WHERE key=?", (key,)
        ).fetchone()
        data = dict(out)
        data["readonly"] = 1 if data["key"] in READONLY_KEYS else 0
        return data


def get_value(key: str, default: str = "", db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM lab_settings WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default
