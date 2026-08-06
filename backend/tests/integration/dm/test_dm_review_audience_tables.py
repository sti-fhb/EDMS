"""DM 簽核 / 變更歷程 / 可見對象授權表整合測試（DM_REVIEW / DM_CHANGE_LOG / DM_USER_TAG）。

驗證 migration 建表 + FK + append-only 變更歷程 + 可見對象授權唯一約束 (USER_ID, TAG_ID)。
分類（SOP）與可見對象（護理師）引用業務種子既有列，避開 PK 衝突。
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.utils import utcnow
from app.dm.audience.models import DmUserTag
from app.dm.catalog.models import DmTag
from app.dm.document.models import DmDocument
from app.dm.review.models import DmChangeLog, DmReview

pytestmark = pytest.mark.integration


async def _seed_doc(db):
    # SOP 分類已由業務種子建立，直接引用；此處只建文件
    db.add(
        DmDocument(
            doc_id="DM-SOP-000001",
            doc_name="程序",
            category_code="SOP",
            status="DRAFT",
            created_user="e",
            created_date=utcnow(),
        )
    )
    await db.flush()


async def test_review_insert_and_fk(db):
    """送審紀錄寫入；FK→文件；STATUS 預設 PENDING。"""
    await _seed_doc(db)
    now = utcnow()
    db.add(
        DmReview(
            doc_id="DM-SOP-000001",
            review_type="NEW",
            assigned_reviewer="rev1",
            submit_date=now,
            created_user="e",
            created_date=now,
        )
    )
    await db.flush()
    row = (await db.execute(select(DmReview).where(DmReview.doc_id == "DM-SOP-000001"))).scalar_one()
    assert row.status == "PENDING" and row.review_type == "NEW" and row.assigned_reviewer == "rev1"


async def test_change_log_append(db):
    """公開變更歷程 append-only 寫入（PUBLISH 事件）。"""
    await _seed_doc(db)
    now = utcnow()
    db.add(
        DmChangeLog(
            doc_id="DM-SOP-000001",
            operation="PUBLISH",
            applicant_user_id="e",
            approver_user_id="rev1",
            operation_time=now,
            note="首版發布",
            created_user="rev1",
            created_date=now,
        )
    )
    await db.flush()
    log = (await db.execute(select(DmChangeLog).where(DmChangeLog.doc_id == "DM-SOP-000001"))).scalar_one()
    assert log.operation == "PUBLISH" and log.note == "首版發布"


async def test_user_tag_unique(db):
    """可見對象授權唯一約束 (USER_ID, TAG_ID)：同人同標籤重複被擋（引用種子之「護理師」標籤）。"""
    now = utcnow()
    tag = (
        await db.execute(select(DmTag).where(DmTag.tag_group_code == "AUDIENCE", DmTag.tag_name == "護理師"))
    ).scalar_one()
    db.add(DmUserTag(user_id="viewer1", tag_id=tag.tag_id, created_user="admin", created_date=now))
    await db.flush()
    db.add(DmUserTag(user_id="viewer1", tag_id=tag.tag_id, created_user="admin", created_date=now))
    with pytest.raises(IntegrityError):
        await db.flush()
