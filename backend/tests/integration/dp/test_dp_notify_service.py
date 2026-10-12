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
    assert result.skipped_reason == "RENDER_FAILED"  # #534：具名，與「刻意跳過」及「無事發生」分得開
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


async def test_queued_count_為零的四種情況彼此可區分(db):
    """`queued_count == 0` 有四種成因，`skipped_reason` 必須分得出來（#534 AC 4）。

    ## 為何需要全集對帳而非逐條各測一次

    這四種的**回傳形狀相同**（`queued_count=0`），只有 `skipped_reason` 不同。逐條各測一次
    的話，少測一種不會有人發現；而少測的那一種若與別種撞值，呼叫端就分不出來——#534 之前
    正是如此：「渲染失敗」與「收件人為空」都回 `None`，於是**唯一代表故障的情況，回報的
    資訊最少**。寫 `if result.skipped_reason:` 的人會抓到停用與管道、唯獨漏掉真正的故障。

    ⚠️ 下方 `set(...)` 的全集斷言是本條的核心：新增第五種成因而忘了給它具名時，這裡會紅。
    """
    await _make_template(db, code="T_OK")
    await _make_template(db, code="T_OFF", enabled=False)
    await _make_template(db, code="T_MSG", channel="MSG")
    await _make_template(db, code="T_BAD", subject="嗨 {name}", body="{未宣告}")

    async def _reason(code: str, recipients: list[str], params: dict[str, str]) -> str | None:
        r = await NotifyService().send_email(
            db, recipients=recipients, template_code=code, module="DP", params=params, caller_module="DP"
        )
        assert r.queued_count == 0, f"{code} 應為 0 才進得了本測試的母體"
        return r.skipped_reason

    full = {"name": "小明", "code": "X"}
    reasons = {
        "停用": await _reason("T_OFF", ["a@x.com"], full),
        "非 Email 管道": await _reason("T_MSG", ["a@x.com"], full),
        "渲染失敗": await _reason("T_BAD", ["a@x.com"], full),
        "收件人為空": await _reason("T_OK", [], full),
    }

    assert reasons == {
        "停用": "TEMPLATE_DISABLED",
        "非 Email 管道": "CHANNEL_NOT_EMAIL",
        "渲染失敗": "RENDER_FAILED",
        "收件人為空": None,
    }
    # 四種成因 → 四個相異值（`None` 只能屬於「無事發生」那一種）
    assert len(set(reasons.values())) == 4, f"有兩種成因撞值，呼叫端分不出來：{reasons}"
