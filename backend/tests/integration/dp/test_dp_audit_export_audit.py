"""DP05 操作記錄匯出本身寫稽核（#675）。

匯出內容含操作者帳號、來源 IP 與異動前後之完整值，且可不帶條件全量取回——判準依
「匯出內容是否含個資」而非「是不是匯出」（見 `docs/specs/et/spec.md` 匯出稽核判準）。
稽核只記**誰、什麼條件、幾筆**，不記任何匯出內容，也不記操作者關鍵字本身（那可能是姓名
或 Email，寫進稽核表等於把個資搬到另一處）。
"""

import json

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.audit.query_service import AuditQueryService
from app.dp.users.models import DpUser

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("backoffice_admin")]

_EXPORT_URL = "/api/dp/audit/logs/export"


async def _seed_user(db, *, user_id: str, user_name: str, email: str) -> None:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=email,
            pwd_hash="x",
            user_name=user_name,
            status="ACTIVE",
            pwd_changed_date=now,
            created_user="seed",
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


async def _insert_log(db, *, operator_id: str = "admin01", action_type: str = "UPDATE", before_value=None) -> None:
    """直接插入一列（查詢 / 匯出不驗鏈，row_hash 給佔位值）。"""
    db.add(
        DpAuditLog(
            module="DP",
            func_name="DP-USERS",
            action_type=action_type,
            result="SUCCESS",
            before_value=before_value,
            row_hash="0" * 64,
            created_user=operator_id,
            created_date=utcnow(),
        )
    )
    await db.flush()


async def _auditor(db) -> dict[str, str]:
    await _seed_user(db, user_id="auditor", user_name="稽核員", email="auditor@edms.local")
    return {"Authorization": f"Bearer {create_access_token(sub='auditor', ttl_minutes=15)}"}


async def _export_audits(db) -> list[DpAuditLog]:
    rows = await db.scalars(
        select(DpAuditLog)
        .where(DpAuditLog.func_name == "DP-AUDIT", DpAuditLog.action_type == "EXPORT")
        .order_by(DpAuditLog.log_id)
    )
    return list(rows)


async def test_匯出一次寫一筆_EXPORT_稽核_含操作者_筆數與條件(client, db) -> None:
    headers = await _auditor(db)
    await _insert_log(db, action_type="UPDATE")
    await _insert_log(db, action_type="UPDATE")
    await _insert_log(db, action_type="DELETE")

    r = await client.get(_EXPORT_URL, params={"action_type": "UPDATE"}, headers=headers)

    assert r.status_code == 200, r.text
    audits = await _export_audits(db)
    assert len(audits) == 1, "匯出操作記錄是把全平台稽核資料帶離系統，必須留痕"
    log = audits[0]
    assert log.module == "DP"
    assert log.result == "SUCCESS"
    assert log.created_user == "auditor"
    assert "2 筆" in (log.description or ""), "應記本次匯出的筆數"
    after = json.loads(log.after_value or "{}")
    assert after["row_count"] == 2
    assert after["action_type"] == "UPDATE"
    assert after["has_operator"] is False


async def test_不記操作者關鍵字與任何匯出內容(client, db) -> None:
    """關鍵字是姓名 / Email；匯出內容含異動前後值——兩者都不得進稽核。"""
    headers = await _auditor(db)
    await _seed_user(db, user_id="victim01", user_name="受害者甲", email="victim@edms.local")
    await _insert_log(db, operator_id="victim01", before_value='{"memo": "機密內容XYZ"}')

    r = await client.get(_EXPORT_URL, params={"operator": "受害者甲"}, headers=headers)

    assert r.status_code == 200, r.text
    # 正向錨點：這次匯出確實命中了那一筆、也確實寫了稽核——否則下面的「不含」恆真
    assert "機密內容XYZ" in r.content.decode("utf-8-sig")
    audits = await _export_audits(db)
    assert len(audits) == 1
    after = json.loads(audits[0].after_value or "{}")
    assert after["has_operator"] is True
    assert after["row_count"] == 1

    recorded = f"{audits[0].description} {audits[0].before_value} {audits[0].after_value}"
    for leaked in ("受害者甲", "victim", "機密內容XYZ"):
        assert leaked not in recorded, f"稽核不得含 {leaked}"


async def test_功能條件只記已登記的代碼_任意字串記為_unknown(client, db) -> None:
    """`func_name` 在 router 只限長度；直接打 API 可塞姓名之類的任意文字。"""
    headers = await _auditor(db)

    known = await client.get(_EXPORT_URL, params={"func_name": "DP-USERS"}, headers=headers)
    arbitrary = await client.get(_EXPORT_URL, params={"func_name": "王小明@edms.local"}, headers=headers)

    assert known.status_code == 200 and arbitrary.status_code == 200
    audits = await _export_audits(db)
    assert len(audits) == 2
    assert json.loads(audits[0].after_value or "{}")["func_name"] == "DP-USERS"
    assert json.loads(audits[1].after_value or "{}")["func_name"] == "<unknown>"
    assert "王小明" not in (audits[1].after_value or "")


async def test_匯出檔不含本次匯出自己那筆_下一次才含(client, db) -> None:
    """先查後寫：本次的稽核列不能出現在本次的檔案裡，否則筆數與內容對不上。"""
    headers = await _auditor(db)

    first = await client.get(_EXPORT_URL, params={"action_type": "EXPORT"}, headers=headers)
    second = await client.get(_EXPORT_URL, params={"action_type": "EXPORT"}, headers=headers)

    assert first.status_code == 200 and second.status_code == 200
    first_rows = [ln for ln in first.content.decode("utf-8-sig").splitlines() if ln.strip()]
    second_rows = [ln for ln in second.content.decode("utf-8-sig").splitlines() if ln.strip()]
    assert len(first_rows) == 1, "第一次匯出時還沒有任何匯出紀錄，只有標頭"
    assert len(second_rows) == 2, "第二次匯出應含第一次留下的那筆"
    assert "DP-操作記錄查詢" in second_rows[1]


async def test_以功能_DP_AUDIT_查得到_並顯示中文(client, db) -> None:
    headers = await _auditor(db)
    await client.get(_EXPORT_URL, headers=headers)

    r = await client.get("/api/dp/audit/logs", params={"func_name": "DP-AUDIT"}, headers=headers)
    options = await client.get("/api/dp/audit/options", headers=headers)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["func_label"] == "DP-操作記錄查詢"
    funcs = {o["value"]: o["label"] for o in options.json()["func_options"]}
    assert funcs.get("DP-AUDIT") == "DP-操作記錄查詢"


async def test_稽核寫入失敗時_HTTP_回錯誤且不帶出檔案(client, db, monkeypatch) -> None:
    """HTTP 層：日後若有人在 router 外層吞掉例外，service 層那條測試照樣綠，這條會紅。"""
    from app.dp.audit import router as audit_router

    headers = await _auditor(db)
    await _insert_log(db, before_value='{"memo": "不該被帶走"}')

    async def _boom(*args, **kwargs) -> None:
        raise RuntimeError("audit down")

    monkeypatch.setattr(audit_router._service._audit, "log_action", _boom)

    r = await client.get(_EXPORT_URL, headers=headers)

    assert r.status_code == 500
    assert "不該被帶走" not in r.text
    assert "操作者帳號" not in r.text, "CSV 標頭不應出現在錯誤回應中"
    assert await _export_audits(db) == []


class _FailingAudit:
    async def log_action(self, *args, **kwargs) -> None:
        raise RuntimeError("audit down")


async def test_稽核寫入失敗時不產出檔案(db) -> None:
    """稽核與匯出同一交易：寫不進去就整個失敗，不讓檔案在沒有軌跡的情況下帶走。"""
    await _insert_log(db)
    service = AuditQueryService(audit=_FailingAudit())

    with pytest.raises(RuntimeError, match="audit down"):
        await service.export_csv(
            db,
            operator_id="auditor",
            operator=None,
            module=None,
            func_name=None,
            action_type=None,
            result=None,
            date_from=None,
            date_to=None,
        )
