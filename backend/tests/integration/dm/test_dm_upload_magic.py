"""上傳 magic-byte 驗證端到端（T066 M2，真實 DB）：偽造副檔名之檔案經真實 editor 流程被擋。"""

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.catalog.models import DmTag
from app.dm.editor.service import EditorService
from app.dm.roles.authz import DM_EDITOR
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_svc = EditorService()


@pytest.fixture(autouse=True)
def _storage_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))


async def _editor(db):
    db.add(
        DpUser(
            user_id="ed",
            email="ed@e.com",
            pwd_hash="x",
            user_name="撰寫",
            pwd_changed_date=utcnow(),
            created_user="seed",
            created_date=utcnow(),
        )
    )
    await db.flush()
    db.add(DmUserRole(user_id="ed", role_code=DM_EDITOR, created_user="seed", created_date=utcnow()))
    await db.flush()


async def _create(db, *, filename, data, mime):
    aud = await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE", DmTag.tag_name == "全體"))
    return await _svc.create_document(
        db,
        doc_name="測試",
        category_code="SOP",
        func_code=None,
        audience_ids=[aud],
        retrieval_ids=[],
        version_no="1.0",
        change_summary="首版",
        file_name=filename,
        file_bytes=data,
        file_mime=mime,
        op=OperatorInfo(user_id="ed"),
    )


async def test_fake_pdf_rejected(db):
    """副檔名 .pdf 但內容非 PDF（偽造）→ DM_FILE_002。"""
    await _editor(db)
    with pytest.raises(AppError) as ei:
        await _create(db, filename="evil.pdf", data=b"MZ\x90\x00 not a pdf", mime="application/pdf")
    assert ei.value.error_code == "DM_FILE_002"


async def test_real_pdf_stores_server_authoritative_mime(db):
    """真實 PDF（%PDF magic）→ 通過，且落地 MIME 由伺服端判定為 application/pdf、可預覽。"""
    await _editor(db)
    res = await _create(db, filename="ok.pdf", data=b"%PDF-1.4 real", mime="application/octet-stream")
    assert res.previewable is True  # 伺服端判定 application/pdf → 可預覽（不受用戶端謊報 octet-stream 影響）
