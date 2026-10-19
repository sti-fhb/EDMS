"""系統操作手冊 func_name 唯一性驗證（T065，真實 DB）。

同一 func_name 至多一份**在架**手冊（部分唯一索引 UX_DM_DOCUMENT_MANUAL_FUNC
WHERE MANUAL AND STATUS IN (PUBLISHED, PENDING_OBSOLETE)）。
- 常態（前一份已發布）：後一份**送簽時**即以 DM_DOC_007 友善擋下。
- 並發（兩份皆送審中、皆未發布 → 依序核准）：第一份發布後，第二份核准撞部分唯一索引 →
  由 approve 映射為友善 DM_DOC_007（部分唯一索引為資料層 backstop、不外露 500）。

🔴 **PENDING_OBSOLETE 納入的理由（#738）**：舊手冊提出廢止申請後狀態轉 PENDING_OBSOLETE，
但它**仍在架、仍列於 DM01**（見 `dm/library/repository.py` 的 `_LIBRARY_STATUSES`）。
納入前，新手冊可在舊手冊廢止核准前發布，DM01 以該作業項目查詢會列出**兩筆**，
與手冊「結果至多一筆」不符。擋的是「同時有兩份在架」，不是「同時有兩份 PUBLISHED」。
"""

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.catalog.models import DmFunc, DmTag
from app.dm.document.models import DmDocument
from app.dm.editor.service import EditorService
from app.dm.obsolete.service import ObsoleteService
from app.dm.review.center_service import ReviewCenterService
from app.dm.roles.authz import DM_EDITOR, DM_REVIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration


async def _all_units_id(db):
    """單位組通用值「全單位」＝不限單位（#437 可見對象配對）。"""
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "UNIT", DmTag.tag_name == "全單位"))


_editor = EditorService()
_review = ReviewCenterService()
_obsolete = ObsoleteService()
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
        audience_unit_ids=[await _all_units_id(db)],
        audience_role_ids=[await _audience_id(db, "全體")],
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


async def _publish_manual(db, *, name, func_code):
    """建手冊 → 送審 → 核准發布，回傳 doc_id。"""
    m = await _create_manual(db, name=name, func_code=func_code)
    s = await _editor.submit(db, doc_id=m.doc_id, version_id=m.version_id, assigned_reviewer="rev1", op=_op("ed"))
    await _review.approve(db, review_id=s.review_id, op=_op("rev1"))
    return m.doc_id


async def _initiate_obsolete(db, doc_id):
    """對已發布手冊發起廢止申請（→ PENDING_OBSOLETE），回傳 review_id。"""
    r = await _obsolete.initiate(
        db,
        doc_id=doc_id,
        reason="改版下架",
        reviewer_id="rev1",
        file_name=None,
        file_bytes=None,
        file_mime=None,
        op=_op("ed"),
    )
    return r.review_id


async def _doc_status(db, doc_id):
    return await db.scalar(select(DmDocument.status).where(DmDocument.doc_id == doc_id))


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
    """兩份手冊皆送審中（皆未發布）→ 依序核准：第一份發布，第二份核准撞索引 → 友善 DM_DOC_007。

    註：以「同交易依序核准」模擬並發之**最終態**（PostgreSQL 對同交易內已 flush 未 commit 之列亦做唯一性
    檢查，故能觸發 backstop）；非真正多連線競爭，但足以驗證部分唯一索引之資料層防線與友善映射。
    """
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


async def test_manual_blocked_at_submit_while_old_pending_obsolete(db):
    """#738 AC1：舊手冊廢止**待簽核期間**，同作業項目新手冊送簽即被擋。

    舊手冊轉 PENDING_OBSOLETE 後仍在架（DM01 仍列出），故「已有對應手冊」須涵蓋此狀態；
    否則新手冊得以發布，DM01 以該作業項目查詢會出現兩筆。
    """
    await _setup_roles(db)
    await _make_func(db, "OPF03", "作業項目三")
    a_id = await _publish_manual(db, name="手冊A", func_code="OPF03")
    await _initiate_obsolete(db, a_id)
    assert await _doc_status(db, a_id) == "PENDING_OBSOLETE"  # 正向錨點：前置確實到位

    b = await _create_manual(db, name="手冊B", func_code="OPF03")
    with pytest.raises(AppError) as ei:
        await _editor.submit(db, doc_id=b.doc_id, version_id=b.version_id, assigned_reviewer="rev1", op=_op("ed"))
    assert ei.value.error_code == "DM_DOC_007"


async def test_manual_blocked_at_approve_when_obsolete_started_after_submit(db):
    """#738 AC2：B 已在送審中、A 之後才提廢止 → 核准 B 時被擋。

    此路徑**送簽檢核擋不到**（B 送簽當下 A 尚未發布），唯一防線是部分唯一索引 ——
    故本條實際驗的是 migration 把 PENDING_OBSOLETE 納入索引 predicate 後的 backstop。
    """
    await _setup_roles(db)
    await _make_func(db, "OPF04", "作業項目四")
    a = await _create_manual(db, name="手冊甲", func_code="OPF04")
    b = await _create_manual(db, name="手冊乙", func_code="OPF04")
    # 兩份皆送審（此時皆未發布，送簽檢核放行）
    sa = await _editor.submit(db, doc_id=a.doc_id, version_id=a.version_id, assigned_reviewer="rev1", op=_op("ed"))
    sb = await _editor.submit(db, doc_id=b.doc_id, version_id=b.version_id, assigned_reviewer="rev1", op=_op("ed"))
    await _review.approve(db, review_id=sa.review_id, op=_op("rev1"))  # 甲 發布
    await _initiate_obsolete(db, a.doc_id)  # 甲 轉廢止待簽核
    assert await _doc_status(db, a.doc_id) == "PENDING_OBSOLETE"  # 正向錨點

    with pytest.raises(AppError) as ei:
        await _review.approve(db, review_id=sb.review_id, op=_op("rev1"))
    assert ei.value.error_code == "DM_DOC_007"


async def test_manual_publishable_after_obsolete_approved(db):
    """#738 AC3：舊手冊廢止**核准後**（轉 OBSOLETE、已下架），新手冊可送審並核准。

    🔴 本條是上面兩條否定斷言的正向錨點：若把 OBSOLETE 也誤納入索引 / 檢核，上面兩條照樣綠，
    但換手冊將永遠做不到——那是比原 bug 更嚴重的靜默失效。
    """
    await _setup_roles(db)
    await _make_func(db, "OPF05", "作業項目五")
    a_id = await _publish_manual(db, name="手冊A", func_code="OPF05")
    obs_id = await _initiate_obsolete(db, a_id)
    await _review.approve(db, review_id=obs_id, op=_op("rev1"))  # 廢止核准 → A 下架
    assert await _doc_status(db, a_id) == "OBSOLETE"

    b = await _create_manual(db, name="手冊B", func_code="OPF05")
    sb = await _editor.submit(db, doc_id=b.doc_id, version_id=b.version_id, assigned_reviewer="rev1", op=_op("ed"))
    await _review.approve(db, review_id=sb.review_id, op=_op("rev1"))
    assert await _doc_status(db, b.doc_id) == "PUBLISHED"
