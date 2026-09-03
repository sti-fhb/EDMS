"""系統操作手冊 func_name 唯一性驗證（T065，真實 DB）。

同一 func_name 至多一份「已發布」手冊（部分唯一索引 UX_DM_DOCUMENT_MANUAL_FUNC WHERE MANUAL+PUBLISHED）。
- 常態（前一份已發布）：後一份**送簽時**即以 DM_DOC_007 友善擋下。
- 並發（兩份皆送審中、皆未發布 → 依序核准）：第一份發布後，第二份核准撞部分唯一索引 →
  由 approve 映射為友善 DM_DOC_007（部分唯一索引為資料層 backstop、不外露 500）。
"""

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.catalog.models import DmFunc, DmTag
from app.dm.editor.service import EditorService
from app.dm.review.center_service import ReviewCenterService
from app.dm.roles.authz import DM_EDITOR, DM_REVIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_editor = EditorService()
_review = ReviewCenterService()
_PDF = "application/pdf"
_MANUAL = "MANUAL"


@pytest.fixture(autouse=True)
def _storage_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))


def _op(uid):
    return OperatorInfo(user_id=uid)


async def _seed_user(db, uid, name):
    db.add(
        DpUser(
            user_id=uid,
            email=f"{uid}@e.com",
            pwd_hash="x",
            user_name=name,
            pwd_changed_date=utcnow(),
            created_user="seed",
            created_date=utcnow(),
        )
    )
    await db.flush()


async def _grant(db, uid, role):
    db.add(DmUserRole(user_id=uid, role_code=role, created_user="seed", created_date=utcnow()))
    await db.flush()


async def _make_func(db, code, name):
    db.add(DmFunc(func_code=code, func_name=name, created_user="seed", created_date=utcnow()))
    await db.flush()


async def _audience_id(db, name):
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE", DmTag.tag_name == name))


async def _create_manual(db, *, name, func_code, author="ed"):
    return await _editor.create_document(
        db,
        doc_name=name,
        category_code=_MANUAL,
        func_code=func_code,
        audience_ids=[await _audience_id(db, "全體")],
        retrieval_ids=[],
        version_no="1.0",
        change_summary="首版",
        file_name="m.pdf",
        file_bytes=b"%PDF-1.4 m",
        file_mime=_PDF,
        op=_op(author),
    )


async def _setup_roles(db):
    await _seed_user(db, "ed", "撰寫者")
    await _grant(db, "ed", DM_EDITOR)
    await _seed_user(db, "rev1", "審核者")
    await _grant(db, "rev1", DM_REVIEWER)


async def test_manual_func_uniqueness_blocked_at_submit(db):
    """前一份手冊已發布 → 後一份送簽即 DM_DOC_007（常態友善擋下）。"""
    await _setup_roles(db)
    await _make_func(db, "OPF01", "作業項目一")
    a = await _create_manual(db, name="手冊A", func_code="OPF01")
    sa = await _editor.submit(db, doc_id=a.doc_id, version_id=a.version_id, assigned_reviewer="rev1", op=_op("ed"))
    await _review.approve(db, review_id=sa.review_id, op=_op("rev1"))  # A 發布

    b = await _create_manual(db, name="手冊B", func_code="OPF01")
    with pytest.raises(AppError) as ei:
        await _editor.submit(db, doc_id=b.doc_id, version_id=b.version_id, assigned_reviewer="rev1", op=_op("ed"))
    assert ei.value.error_code == "DM_DOC_007"


async def test_concurrent_manual_publish_backstopped(db):
    """兩份手冊皆送審中（皆未發布）→ 依序核准：第一份發布，第二份核准撞索引 → 友善 DM_DOC_007。"""
    await _setup_roles(db)
    await _make_func(db, "OPF02", "作業項目二")
    a = await _create_manual(db, name="手冊甲", func_code="OPF02")
    b = await _create_manual(db, name="手冊乙", func_code="OPF02")
    # 兩份皆送審（此時皆未發布，送簽檢核放行）
    sa = await _editor.submit(db, doc_id=a.doc_id, version_id=a.version_id, assigned_reviewer="rev1", op=_op("ed"))
    sb = await _editor.submit(db, doc_id=b.doc_id, version_id=b.version_id, assigned_reviewer="rev1", op=_op("ed"))
    await _review.approve(db, review_id=sa.review_id, op=_op("rev1"))  # 甲 發布
    # 乙 核准 → 撞部分唯一索引 → 友善映射
    with pytest.raises(AppError) as ei:
        await _review.approve(db, review_id=sb.review_id, op=_op("rev1"))
    assert ei.value.error_code == "DM_DOC_007"
