"""T050 發信引擎端到端整合測試（SC-009）。

串接 outbox 全流程：send_email 寫 PENDING 快照即返回（不阻塞呼叫方）→ worker 輪詢寄出 / 重試。
重點驗證跨概念的**已寄快照不受事後改範本影響**（DP_EMAIL_LOG.BODY 為當下渲染快照）、
停用範本 skip、渲染快照與範本解耦。worker 重試 / FAILED 單點機制已由 test_dp_notify_worker 覆蓋，
此檔驗端到端串接與快照隔離。
"""

import pytest
from sqlalchemy import select

from app.core.utils import utcnow
from app.dp.notify.models import DpEmailLog, DpNotifyTemplate
from app.dp.notify.worker import EmailWorker
from app.services import NotifyService

pytestmark = pytest.mark.integration


class _SucceedMailer:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, *, recipient, subject, body):
        self.sent.append(recipient)


class _FailMailer:
    async def send(self, *, recipient, subject, body):
        raise RuntimeError("smtp down")


async def _make_template(db, *, code, body, enabled=True):
    db.add(
        DpNotifyTemplate(
            module="DP",
            template_code=code,
            template_name="e2e",
            subject="主旨",
            body=body,
            channel="EMAIL",
            is_enabled=enabled,
            is_system=False,
            version=1,
            created_user="admin01",
            created_date=utcnow(),
        )
    )
    await db.flush()


async def _logs_for(db, code):
    stmt = select(DpEmailLog).where(DpEmailLog.template_code == code).order_by(DpEmailLog.message_id)
    return list((await db.execute(stmt)).scalars().all())


async def test_send_writes_pending_snapshot_without_blocking(db):
    """send_email 立即回 queued_count、寫 PENDING 快照（不同步寄、不阻塞呼叫方，SC-009）。"""
    await _make_template(db, code="E2E_SNAP", body="您好 {name}")
    result = await NotifyService().send_email(
        db, recipients=["a@x.com"], template_code="E2E_SNAP", module="DP", params={"name": "小明"}, caller_module="DP"
    )
    assert result.queued_count == 1 and result.skipped_reason is None

    rows = await _logs_for(db, "E2E_SNAP")
    assert len(rows) == 1
    assert rows[0].status == "PENDING"
    assert rows[0].body == "您好 小明"  # 已渲染快照，非範本原文


async def test_sent_snapshot_unaffected_by_later_template_edit(db):
    """已寄快照不受事後改範本影響：改範本後新信用新內容，舊信快照不變（SC-009）。"""
    await _make_template(db, code="E2E_EDIT", body="版本一 {name}")
    await NotifyService().send_email(
        db, recipients=["a@x.com"], template_code="E2E_EDIT", module="DP", params={"name": "A"}, caller_module="DP"
    )

    # 事後修改範本 body
    tmpl = (
        await db.execute(select(DpNotifyTemplate).where(DpNotifyTemplate.template_code == "E2E_EDIT"))
    ).scalar_one()
    tmpl.body = "版本二 {name}"
    await db.flush()

    # 再寄一封 → 用新內容
    await NotifyService().send_email(
        db, recipients=["b@x.com"], template_code="E2E_EDIT", module="DP", params={"name": "B"}, caller_module="DP"
    )

    rows = await _logs_for(db, "E2E_EDIT")
    assert len(rows) == 2
    assert rows[0].body == "版本一 A"  # 舊快照不受改範本影響
    assert rows[1].body == "版本二 B"  # 新信用新範本


async def test_disabled_template_skips_send(db):
    """停用範本 → send_email 回 TEMPLATE_DISABLED、不寫 outbox（事件照常不拋錯，SC-009）。"""
    await _make_template(db, code="E2E_OFF", body="停用 {name}", enabled=False)
    result = await NotifyService().send_email(
        db, recipients=["a@x.com"], template_code="E2E_OFF", module="DP", params={"name": "X"}, caller_module="DP"
    )
    assert result.queued_count == 0 and result.skipped_reason == "TEMPLATE_DISABLED"
    assert await _logs_for(db, "E2E_OFF") == []


async def test_worker_processes_pending_to_sent(db):
    """worker 輪詢 PENDING → 成功寄出標 SENT（端到端串接）。"""
    await _make_template(db, code="E2E_SEND", body="寄 {name}")
    await NotifyService().send_email(
        db, recipients=["a@x.com"], template_code="E2E_SEND", module="DP", params={"name": "Y"}, caller_module="DP"
    )
    mailer = _SucceedMailer()
    await EmailWorker().process_pending_once(db, mailer=mailer, max_retry=3, interval_minutes=0)

    rows = await _logs_for(db, "E2E_SEND")
    assert rows[0].status == "SENT" and mailer.sent == ["a@x.com"]


async def test_worker_failure_marks_failed_at_cap(db):
    """worker 寄送持續失敗達上限 → FAILED 留錯誤訊息（端到端；單點重試邏輯見 notify_worker）。"""
    await _make_template(db, code="E2E_FAIL", body="失敗 {name}")
    await NotifyService().send_email(
        db, recipients=["a@x.com"], template_code="E2E_FAIL", module="DP", params={"name": "Z"}, caller_module="DP"
    )
    await EmailWorker().process_pending_once(db, mailer=_FailMailer(), max_retry=1, interval_minutes=0)

    rows = await _logs_for(db, "E2E_FAIL")
    assert rows[0].status == "FAILED" and rows[0].error_msg is not None