"""DM 文件核心表整合測試（DM_DOCUMENT / DM_DOC_VERSION / DM_DOC_TAG / DM_DOC_READ）。

重點驗：文件↔版本 FK + 循環指標、**手冊唯一部分索引**（同 func 至多一份已發布手冊）、
DM_DOC_READ 同人同版去重（唯一約束）。
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.utils import utcnow
from app.dm.catalog.models import DmFunc
from app.dm.document.models import DmDocRead, DmDocument, DmDocVersion

pytestmark = pytest.mark.integration


async def _seed_catalog(db):
    # MANUAL 分類已由業務種子建立，此處只補測試用 func（func 不在種子內）
    db.add(DmFunc(func_code="BS04", func_name="領血確認", created_user="s", created_date=utcnow()))
    await db.flush()


async def test_document_and_version_fk(db):
    """文件 + 版本寫入；版本 FK→文件；CURRENT_VERSION_ID 邏輯指標可回填。"""
    await _seed_catalog(db)
    now = utcnow()
    db.add(
        DmDocument(
            doc_id="DM-MANUAL-000001",
            doc_name="領血手冊",
            category_code="MANUAL",
            func_code="BS04",
            status="DRAFT",
            created_user="editor",
            created_date=now,
        )
    )
    await db.flush()
    ver = DmDocVersion(
        doc_id="DM-MANUAL-000001",
        version_no="v1.0",
        change_summary="首版",
        file_name="a.pdf",
        file_path="/f/a.pdf",
        file_size=1024,
        file_mime="application/pdf",
        status="PUBLISHED",
        created_user="editor",
        created_date=now,
    )
    db.add(ver)
    await db.flush()
    doc = (await db.execute(select(DmDocument).where(DmDocument.doc_id == "DM-MANUAL-000001"))).scalar_one()
    doc.current_version_id = ver.version_id
    await db.flush()
    assert doc.current_version_id == ver.version_id


async def test_manual_func_unique_when_published(db):
    """手冊唯一：同 func 之第二份『已發布手冊』被部分唯一索引擋下。"""
    await _seed_catalog(db)
    now = utcnow()
    db.add(
        DmDocument(
            doc_id="DM-MANUAL-000001",
            doc_name="手冊A",
            category_code="MANUAL",
            func_code="BS04",
            status="PUBLISHED",
            created_user="e",
            created_date=now,
        )
    )
    await db.flush()
    db.add(
        DmDocument(
            doc_id="DM-MANUAL-000002",
            doc_name="手冊B",
            category_code="MANUAL",
            func_code="BS04",
            status="PUBLISHED",
            created_user="e",
            created_date=now,
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_manual_func_draft_not_blocked(db):
    """同 func 但非『已發布』（DRAFT）→ 不受手冊唯一索引限制。"""
    await _seed_catalog(db)
    now = utcnow()
    db.add(
        DmDocument(
            doc_id="DM-MANUAL-000001",
            doc_name="手冊A",
            category_code="MANUAL",
            func_code="BS04",
            status="PUBLISHED",
            created_user="e",
            created_date=now,
        )
    )
    db.add(
        DmDocument(
            doc_id="DM-MANUAL-000002",
            doc_name="手冊B草稿",
            category_code="MANUAL",
            func_code="BS04",
            status="DRAFT",
            created_user="e",
            created_date=now,
        )
    )
    await db.flush()  # 不應拋錯
    rows = (await db.execute(select(DmDocument).where(DmDocument.func_code == "BS04"))).scalars().all()
    assert len(rows) == 2


async def test_doc_read_dedup_unique(db):
    """DM_DOC_READ 同人同版本重複 → 唯一約束 (DOC_ID, VERSION_ID, CREATED_USER) 擋下（去重計人）。"""
    await _seed_catalog(db)
    now = utcnow()
    db.add(
        DmDocument(
            doc_id="DM-MANUAL-000001",
            doc_name="D",
            category_code="MANUAL",
            func_code="BS04",
            status="PUBLISHED",
            created_user="e",
            created_date=now,
        )
    )
    await db.flush()
    ver = DmDocVersion(
        doc_id="DM-MANUAL-000001",
        version_no="v1.0",
        change_summary="s",
        file_name="a.pdf",
        file_path="/a",
        file_size=1,
        file_mime="application/pdf",
        status="PUBLISHED",
        created_user="e",
        created_date=now,
    )
    db.add(ver)
    await db.flush()
    db.add(DmDocRead(doc_id="DM-MANUAL-000001", version_id=ver.version_id, created_user="reader1", created_date=now))
    await db.flush()
    db.add(DmDocRead(doc_id="DM-MANUAL-000001", version_id=ver.version_id, created_user="reader1", created_date=now))
    with pytest.raises(IntegrityError):
        await db.flush()
