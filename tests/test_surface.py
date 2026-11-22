"""quarantine-bug-02：审计舱位摘要、设置只读放行口径、HTTP 四屏接口。"""
from __future__ import annotations

import pytest

from app.services import audit, settings, quarantine
from app.services.errors import ServiceError
from app.services.release_ledger import gate_summary, released_count

READONLY_KEY = "release_read_track"


def test_audit_summary_carries_bin_slot_overview(db_path):
    summary = audit.summary(db_path)
    bins = quarantine.list_bins(db_path)
    assert "bin_slots" in summary
    slots = {b["bin_code"]: b for b in summary["bin_slots"]}
    for b in bins:
        assert b["bin_code"] in slots
        slot = slots[b["bin_code"]]
        assert slot["bin_code"] == b["bin_code"]
        assert slot["title"] == b["title"]
        assert slot["status"] == b["status"]
        assert slot["capacity"] == b["capacity"]
        assert slot["pending_count"] == b["pending_count"]
        assert slot["row_count"] == b["row_count"]


def test_release_policy_setting_is_seeded_readonly(db_path):
    rows = {s["key"]: s for s in settings.list_settings(db_path)}
    assert READONLY_KEY in rows
    assert rows[READONLY_KEY]["value"] == "切流账册"
    assert rows[READONLY_KEY]["readonly"] == 1


def test_readonly_release_setting_cannot_be_updated(db_path):
    with pytest.raises(ServiceError) as exc:
        settings.update_setting(READONLY_KEY, "双写两轨", db_path)
    assert "只读" in exc.value.message
    # 值原样不动
    assert settings.get_value(READONLY_KEY, db_path=db_path) == "切流账册"


def test_dashboard_release_gate_summary(db_path):
    from app.services import reconcile
    dash = reconcile.dashboard(db_path)
    assert dash["release_gate"]["released_count"] == released_count(db_path)
    assert "blocked_count" in dash["release_gate"]
    assert "blocked_item_ids" in dash["release_gate"]


def test_http_four_screens_release_surface(testapp_factory, db_path):
    """四屏接口层：复核徽标/落点、抓取已放行件数、审计舱位、设置只读口径。"""
    app = testapp_factory
    # 造一条放行
    from app.services import captures, review
    batches = captures.list_batches(db_path)
    batch = next(b for b in batches if b["status"] != "已关闭")
    bins = quarantine.list_bins(db_path)
    open_bin = next(b for b in bins if b["status"] == "开放")
    detail = captures.get_batch(batch["id"], db_path)
    bad = next(i for i in detail["items"] if i["quality"] != "合格" and i["status"] == "待检")
    row = quarantine.enter_item(bad["id"], open_bin["id"], "HTTP 入舱", db_path)
    ticket = next(
        t for t in review.list_tickets(db_path)
        if t["row_id"] == row["id"] and t["decision"] == "待决"
    )
    r = app.post_json(f"/api/tickets/{ticket['id']}/decide", {"decision": "放行"})
    assert r.status_code == 200
    assert r.json["fingerprint"]
    assert r.json["item_status"] == "已放行"

    # 复核列表：徽标数据与落点行
    tickets = app.get("/api/tickets").json["items"]
    mine = next(t for t in tickets if t["id"] == ticket["id"])
    assert mine["decision"] == "放行"
    assert mine["fingerprint"]
    assert mine["ledger_id"] is not None

    # 抓取批次详情：已放行件数 + 逐条落点
    bd = app.get(f"/api/batches/{batch['id']}").json
    assert bd["released_count"] == 1
    marked = next(i for i in bd["items"] if i["id"] == bad["id"])
    assert marked["status"] == "已放行"
    assert marked["release"]["fingerprint"]

    # 审计页：舱位摘要
    aud = app.get("/api/audits").json
    assert aud["summary"]["bin_slots"]
    assert any(s["bin_code"] == open_bin["bin_code"] for s in aud["summary"]["bin_slots"])

    # 设置页：只读放行口径
    setting_map = {s["key"]: s for s in app.get("/api/settings").json["items"]}
    assert setting_map[READONLY_KEY]["readonly"] == 1
    bad_resp = app.post_json(
        "/api/settings/update",
        {"key": READONLY_KEY, "value": "双写两轨"},
        expect_errors=True,
    )
    assert bad_resp.status_code == 400
    assert "只读" in bad_resp.json["error"]

    # 写败中文说明：重复放行
    again = app.post_json(
        f"/api/tickets/{ticket['id']}/decide",
        {"decision": "放行"},
        expect_errors=True,
    )
    assert again.status_code == 409
    assert again.json["error"]


def test_http_scaffold_routes_removed(testapp_factory):
    """脚手架残留不得收工：旧 release_pack 接口必须拆除。"""
    for path in (
        "/api/release_pack/dash",
        "/api/release_pack/commit",
        "/api/release_pack/cutover",
        "/api/release_pack/dual",
        "/api/release_pack/snap",
        "/api/release_pack/half",
    ):
        r = testapp_factory.get(path, expect_errors=True)
        assert r.status_code == 404, path
