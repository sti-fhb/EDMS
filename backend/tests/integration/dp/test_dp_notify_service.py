"""通知發送服務 SRVDP002（T018）整合測試：查範本 + 分流 + 逐收件人寫 outbox（真實 DB）。"""

import pytest
from sqlalchemy import select

from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.dp.notify.models import DpEmailLog, DpNotifyTemplate
from app.services import NotifyService

pytestmark = pytest.mark.integration


async def _make_template(
    db, *, module="DP", code="T_TEST", channel="EMAIL", enabled=True, subject="嗨 {name}", body="內容 {code}"
):
    now = utcnow()
    db.add(
        DpNotifyTemplate(
            module=module,
            template_code=code,
            template_name="測試範本",
            subject=subject,
            body=body,
            channel=channel,
            is_enabled=enabled,
            is_system=False,
            version=1,
            created_user="admin01",
            created_date=now,
        )
    )
    await db.flush()


async def _fetch_logs(db):
    result = await db.execute(select(DpEmailLog).order_by(DpEmailLog.message_id))
    return list(result.scalars().all())


async def test_send_email_writes_pending(db):
    """啟用範本：逐收件人寫 PENDING、渲染快照正確、回 queued_count。"""
    await _make_template(db, code="T_A")
    result = await NotifyService().send_email(
        db,
        recipients=["a@x.com", "b@x.com"],
        template_code="T_A",
        module="DP",
        params={"name": "小明", "code": "999"},
        caller_module="DP",
    )
    assert result.queued_count == 2
    assert result.skipped_reason is None
    logs = await _fetch_logs(db)
    assert len(logs) == 2
    assert {log.recipient for log in logs} == {"a@x.com", "b@x.com"}
    assert all(log.status == "PENDING" for log in logs)
    assert logs[0].subject == "嗨 小明" and logs[0].body == "內容 999"
    assert logs[0].caller_module == "DP"


async def test_missing_template_raises(db):
    """範本不存在 → AppError DP_MAIL_001。"""
    with pytest.raises(AppError) as exc:
        await NotifyService().send_email(
            db,
            recipients=["a@x.com"],
            template_code="NOPE",
            module="DP",
            params={},
            caller_module="DP",
        )
    assert exc.value.status_code == 404
    assert exc.value.error_code == "DP_MAIL_001"


async def test_disabled_template_skipped(db):
    """停用範本 → 不寫 outbox、回 skipped_reason=TEMPLATE_DISABLED。"""
    await _make_template(db, code="T_OFF", enabled=False)
    result = await NotifyService().send_email(
        db,
        recipients=["a@x.com"],
        template_code="T_OFF",
        module="DP",
        params={"name": "x", "code": "1"},
        caller_module="DP",
    )
    assert result.queued_count == 0
    assert result.skipped_reason == "TEMPLATE_DISABLED"
    assert await _fetch_logs(db) == []


async def test_channel_not_email_skipped(db):
    """CHANNEL=MSG → 不寫 outbox、回 skipped_reason=CHANNEL_NOT_EMAIL。"""
    await _make_template(db, code="T_MSG", channel="MSG")
    result = await NotifyService().send_email(
        db,
        recipients=["a@x.com"],
        template_code="T_MSG",
        module="DP",
        params={"name": "x", "code": "1"},
        caller_module="DP",
    )
    assert result.queued_count == 0
    assert result.skipped_reason == "CHANNEL_NOT_EMAIL"
    assert await _fetch_logs(db) == []


async def test_missing_var_writes_failed(db):
    """範本變數缺漏 → 該批寫 FAILED（含錯誤訊息），不拋錯不阻斷呼叫方。"""
    await _make_template(db, code="T_VAR", subject="嗨 {name}", body="內容 {code}")
    result = await NotifyService().send_email(
        db,
        recipients=["a@x.com"],
        template_code="T_VAR",
        module="DP",
        params={"name": "小明"},
        caller_module="DP",
    )
    assert result.queued_count == 0
    logs = await _fetch_logs(db)
    assert len(logs) == 1
    assert logs[0].status == "FAILED"
    assert logs[0].error_msg is not None


async def test_exceeds_recipient_limit_raises(db):
    """收件人超過單次上限 → AppError DP_MAIL_002（不寫 outbox）。"""
    await _make_template(db, code="T_MANY")
    with pytest.raises(AppError) as exc:
        await NotifyService().send_email(
            db,
            recipients=[f"u{i}@x.com" for i in range(51)],
            template_code="T_MANY",
            module="DP",
            params={"name": "x", "code": "1"},
            caller_module="DP",
        )
    assert exc.value.status_code == 422
    assert exc.value.error_code == "DP_MAIL_002"
    assert await _fetch_logs(db) == []


async def test_unbalanced_brace_writes_failed(db):
    """範本含未閉合大括號 → 渲染 ValueError 被捕捉、該批寫 FAILED，不拋錯不阻斷呼叫方。"""
    await _make_template(db, code="T_CSS", subject="嗨", body="<p>{name</p>")
    result = await NotifyService().send_email(
        db,
        recipients=["a@x.com"],
        template_code="T_CSS",
        module="DP",
        params={"name": "小明"},
        caller_module="DP",
    )
    assert result.queued_count == 0
    logs = await _fetch_logs(db)
    assert len(logs) == 1 and logs[0].status == "FAILED" and logs[0].error_msg is not None
