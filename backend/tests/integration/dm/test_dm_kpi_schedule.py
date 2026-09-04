"""SCHDM001 每週排程核心（US13 FR-004~006）整合測試（真實 DB）。

涵蓋：KPI 週報收件＝全部 DM_ADMIN、未讀提醒逐位未看閱覽者一信（無未看者不寄）、涵蓋全部已發布文件、
經 outbox DP_EMAIL_LOG 非同步（STATUS='PENDING'，篩 TEMPLATE_CODE 防假陽性、驗 params 對齊未 FAILED）、
範本停用則對應信整批不寄（KPI 計算不受影響）。直接呼叫 handler 核心 `run_weekly`（不經 APScheduler）。
"""

import pytest
from sqlalchemy import select, text

from app.core.utils import utcnow
from app.dm.audience.models import DmUserTag
from app.dm.catalog.models import DmCategory, DmTag  # noqa: F401  # 註冊 FK 目標
from app.dm.document.models import DmDocRead, DmDocTag, DmDocument, DmDocVersion
from app.dm.kpi.service import KpiService
from app.dm.roles.authz import DM_ADMIN, DM_VIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration


async def _tag_id(db, tag_name: str) -> int:
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE", DmTag.tag_name == tag_name))


async def _user(db, user_id, name):
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@e.com",
            pwd_hash="x",
            user_name=name,
            pwd_changed_date=utcnow(),
            created_user="seed",
            created_date=utcnow(),
        )
    )
    await db.flush()


async def _grant(db, user_id, role):
    db.add(DmUserRole(user_id=user_id, role_code=role, created_user="seed", created_date=utcnow()))
    await db.flush()


async def _audience(db, user_id, tag_name):
    db.add(DmUserTag(user_id=user_id, tag_id=await _tag_id(db, tag_name), created_user="seed", created_date=utcnow()))
    await db.flush()


async def _doc(db, doc_id, tag_name):
    db.add(
        DmDocument(
            doc_id=doc_id,
            doc_name=doc_id,
            category_code="SOP",
            status="PUBLISHED",
            created_user="author",
            created_date=utcnow(),
        )
    )
    await db.flush()
    v = DmDocVersion(
        doc_id=doc_id,
        version_no="1.0",
        change_summary="摘要",
        file_name="f.pdf",
        file_path="/x/f.pdf",
        file_size=100,
        file_mime="application/pdf",
        status="PUBLISHED",
        published_date=utcnow(),
        created_user="author",
        created_date=utcnow(),
    )
    db.add(v)
    await db.flush()
    doc = await db.get(DmDocument, doc_id)
    doc.current_version_id = v.version_id
    await db.flush()
    db.add(DmDocTag(doc_id=doc_id, tag_id=await _tag_id(db, tag_name), created_user="seed", created_date=utcnow()))
    await db.flush()
    return v.version_id


async def _read(db, doc_id, version_id, user_id):
    db.add(DmDocRead(doc_id=doc_id, version_id=version_id, created_user=user_id, created_date=utcnow()))
    await db.flush()


async def _pending_recipients(db, template_code) -> set[str]:
    rows = await db.execute(
        text(
            'SELECT "RECIPIENT", "STATUS" FROM "DP_EMAIL_LOG" WHERE "TEMPLATE_CODE" = :tc AND "MODULE" = \'DM\''
        ).bindparams(tc=template_code)
    )
    result = set()
    for recipient, status in rows.all():
        assert status == "PENDING", f"{template_code} 應排入 PENDING（params 對齊），實為 {status}"
        result.add(recipient)
    return result


async def _scenario(db):
    """2 管理者；v_unseen（護理師、未看）、v_seen（護理師、已看 D1）；D1 掛護理師。"""
    await _user(db, "adm1", "管甲")
    await _grant(db, "adm1", DM_ADMIN)
    await _user(db, "adm2", "管乙")
    await _grant(db, "adm2", DM_ADMIN)
    await _user(db, "v_unseen", "閱未")
    await _grant(db, "v_unseen", DM_VIEWER)
    await _audience(db, "v_unseen", "護理師")
    await _user(db, "v_seen", "閱已")
    await _grant(db, "v_seen", DM_VIEWER)
    await _audience(db, "v_seen", "護理師")
    vid = await _doc(db, "DM-SOP-000201", "護理師")
    await _read(db, "DM-SOP-000201", vid, "v_seen")  # v_seen 已看、v_unseen 未看


async def test_weekly_report_sent_to_all_admins(db):
    await _scenario(db)
    result = await KpiService().run_weekly(db)
    assert result.weekly_queued == 2
    assert await _pending_recipients(db, "KPI_WEEKLY") == {"adm1@e.com", "adm2@e.com"}


async def test_unread_reminder_only_to_unseen_viewers(db):
    await _scenario(db)
    await KpiService().run_weekly(db)
    # 僅 v_unseen 收未讀提醒；v_seen 已看全部、不寄
    assert await _pending_recipients(db, "UNREAD_REMIND") == {"v_unseen@e.com"}


async def test_unread_reminder_disabled_template_not_sent(db):
    await _scenario(db)
    await db.execute(
        text(
            'UPDATE "DP_NOTIFY_TEMPLATE" SET "IS_ENABLED" = false '
            "WHERE \"MODULE\" = 'DM' AND \"TEMPLATE_CODE\" = 'UNREAD_REMIND'"
        )
    )
    await db.flush()
    result = await KpiService().run_weekly(db)
    # 未讀提醒整批不寄，但 KPI 週報照常
    assert await _pending_recipients(db, "UNREAD_REMIND") == set()
    assert result.unread_notified == 0
    assert await _pending_recipients(db, "KPI_WEEKLY") == {"adm1@e.com", "adm2@e.com"}


async def test_no_viewers_no_unread(db):
    """無任何未看閱覽者 → 不寄未讀提醒（週報仍寄予管理者）。"""
    await _user(db, "adm1", "管甲")
    await _grant(db, "adm1", DM_ADMIN)
    result = await KpiService().run_weekly(db)
    assert await _pending_recipients(db, "UNREAD_REMIND") == set()
    assert result.weekly_queued == 1  # 仍寄週報予管理者
