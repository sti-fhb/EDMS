"""暫時重現腳本：續編草稿改標籤是否即時生效（手測回報）。定位用，定位後刪除或轉為正式測試。"""

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.catalog.models import DmTag
from app.dm.editor.service import EditorService
from app.dm.roles.authz import DM_EDITOR
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_editor = EditorService()
_PDF = "application/pdf"


@pytest.fixture(autouse=True)
def _storage_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))


def _op(uid):
    return OperatorInfo(user_id=uid)


async def _seed(db):
    db.add(
        DpUser(
            user_id="ed",
            email="ed@e.com",
            pwd_hash="x",
            user_name="撰寫者",
            pwd_changed_date=utcnow(),
            created_user="seed",
            created_date=utcnow(),
        )
    )
    await db.flush()
    db.add(DmUserRole(user_id="ed", role_code=DM_EDITOR, created_user="seed", created_date=utcnow()))
    await db.flush()


async def _two_aud(db):
    rows = await db.scalars(
        select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE").order_by(DmTag.tag_id).limit(2)
    )
    ids = list(rows.all())
    return ids[0], ids[1]


async def test_repro_continue_draft_tag_change(db):
    """首版草稿 → 續編改可見對象 → 再讀預帶值，應為新值。"""
    await _seed(db)
    aud_a, aud_b = await _two_aud(db)

    created = await _editor.create_document(
        db,
        doc_name="草稿",
        category_code="SOP",
        func_code=None,
        audience_ids=[aud_a],
        retrieval_ids=[],
        version_no="1.0",
        change_summary="首版",
        file_name="a.pdf",
        file_bytes=b"%PDF-1.4 a",
        file_mime=_PDF,
        op=_op("ed"),
    )

    t1 = await _editor.get_doc_tags(db, created.doc_id, user_id="ed")
    assert t1.audience_ids == [str(aud_a)], f"建立後預帶應為 A，實得 {t1.audience_ids}"

    # 續編：改為 B
    await _editor.update_draft_version(
        db,
        doc_id=created.doc_id,
        version_id=created.version_id,
        doc_name="草稿",
        func_code=None,
        assigned_reviewer=None,
        audience_ids=[aud_b],
        retrieval_ids=[],
        version_no="1.0",
        change_summary="首版",
        file_name=None,
        file_bytes=None,
        file_mime=None,
        op=_op("ed"),
    )

    t2 = await _editor.get_doc_tags(db, created.doc_id, user_id="ed")
    assert t2.audience_ids == [str(aud_b)], f"續編後預帶應為 B，實得 {t2.audience_ids}"
