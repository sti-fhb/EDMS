"""標籤版本層快照流程整合測試（#377，真實 DB）。

驗證標籤生效時點由「存草稿當下」改為「核准發布當下」：草稿階段的標籤變更存於版本層
（DM_VERSION_TAG），文件層（DM_DOC_TAG，即 visibility 判定依據）僅於核准發布時更新，
退回則完全不套用。推翻 spec_us5 FR-003 原「存檔當下即生效」之設計。
"""

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.catalog.models import DmTag
from app.dm.document.models import DmDocTag, DmVersionTag
from app.dm.editor.service import EditorService
from app.dm.review.center_service import ReviewCenterService
from app.dm.roles.authz import DM_EDITOR, DM_REVIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_editor = EditorService()
_review = ReviewCenterService()
_PDF = "application/pdf"


@pytest.fixture(autouse=True)
def _storage_root(tmp_path, monkeypatch):
    """落盤根目錄導向 tmp，避免污染工作目錄。"""
    monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))


def _op(uid):
    return OperatorInfo(user_id=uid)


async def _seed_user(db, user_id, name):
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


async def _two_audience_ids(db) -> tuple[int, int]:
    """取兩個相異之可見對象標籤（不寫死名稱，避免綁定 seed 內容）。"""
    rows = await db.scalars(
        select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE").order_by(DmTag.tag_id).limit(2)
    )
    ids = list(rows.all())
    assert len(ids) == 2, "seed 需至少 2 個 AUDIENCE 標籤"
    return ids[0], ids[1]


async def _doc_tag_ids(db, doc_id) -> set[int]:
    """文件層（生效中）之標籤集合。"""
    rows = await db.scalars(select(DmDocTag.tag_id).where(DmDocTag.doc_id == doc_id, DmDocTag.deleted == 0))
    return set(rows.all())


async def _version_tag_ids(db, version_id) -> set[int]:
    """版本層（該版本提議）之標籤集合。"""
    rows = await db.scalars(
        select(DmVersionTag.tag_id).where(DmVersionTag.version_id == version_id, DmVersionTag.deleted == 0)
    )
    return set(rows.all())


async def _publish_first_version(db, *, audience_id: int) -> tuple[str, int]:
    """建立文件 + 首版並核准發布，回傳 (doc_id, version_id)。"""
    created = await _editor.create_document(
        db,
        doc_name="標籤快照測試文件",
        category_code="SOP",
        func_code=None,
        audience_ids=[audience_id],
        retrieval_ids=[],
        version_no="1.0",
        change_summary="首版",
        file_name="v1.pdf",
        file_bytes=b"%PDF-1.4 v1",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=created.doc_id, version_id=created.version_id, assigned_reviewer="rev1", op=_op("ed")
    )
    await _review.approve(db, review_id=submitted.review_id, op=_op("rev1"))
    return created.doc_id, created.version_id


async def _seed_editor_and_reviewer(db):
    await _seed_user(db, "ed", "撰寫者")
    await _grant(db, "ed", DM_EDITOR)
    await _seed_user(db, "rev1", "審核者")
    await _grant(db, "rev1", DM_REVIEWER)


async def test_draft_tag_change_does_not_touch_doc_tag(db):
    """AC1：已發布文件開新版改可見對象並存草稿 → 文件層不變、版本層持有新值。"""
    await _seed_editor_and_reviewer(db)
    aud_a, aud_b = await _two_audience_ids(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)
    assert await _doc_tag_ids(db, doc_id) == {aud_a}

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_ids=[aud_b],  # 改成另一組可見對象
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )

    # 核心：草稿階段文件層完全不受影響（已發布文件之可見範圍不因存草稿而改變）
    assert await _doc_tag_ids(db, doc_id) == {aud_a}
    assert await _version_tag_ids(db, ver2.version_id) == {aud_b}


async def test_approve_applies_version_tags_to_doc(db):
    """AC2：核准發布後文件層等同該版本之版本層快照。"""
    await _seed_editor_and_reviewer(db)
    aud_a, aud_b = await _two_audience_ids(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_ids=[aud_b],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed")
    )
    await _review.approve(db, review_id=submitted.review_id, op=_op("rev1"))

    assert await _doc_tag_ids(db, doc_id) == {aud_b}


async def test_submit_blocked_when_version_snapshot_empty(db):
    """送簽檢核確實讀版本層：文件層有可見對象、版本層為空 → 仍擋 DM_DOC_005。

    此即 migration 必須回填在途草稿的原因——檢核來源改為版本層後，改動前既有的草稿若不回填，
    送簽會被誤擋。回填 SQL 本身屬 schema/資料操作，依 sti-testing 不另寫一次性驗收測試。
    """
    await _seed_editor_and_reviewer(db)
    aud_a, _ = await _two_audience_ids(db)
    doc_id, _v1 = await _publish_first_version(db, audience_id=aud_a)
    assert await _doc_tag_ids(db, doc_id) == {aud_a}  # 文件層有值

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_ids=[aud_a],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    # 模擬「migration 未回填」之在途草稿：抹除該版本快照
    await db.execute(delete(DmVersionTag).where(DmVersionTag.version_id == ver2.version_id))
    await db.flush()

    with pytest.raises(AppError) as exc:
        await _editor.submit(db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed"))
    assert exc.value.error_code == "DM_DOC_005"


async def test_reject_keeps_doc_tags_unchanged(db):
    """AC3：送審被退回 → 文件層維持退回前的值，不被草稿值污染。"""
    await _seed_editor_and_reviewer(db)
    aud_a, aud_b = await _two_audience_ids(db)
    doc_id, _ = await _publish_first_version(db, audience_id=aud_a)

    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_ids=[aud_b],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    submitted = await _editor.submit(
        db, doc_id=doc_id, version_id=ver2.version_id, assigned_reviewer="rev1", op=_op("ed")
    )
    await _review.reject(db, review_id=submitted.review_id, reason="可見對象選錯", op=_op("rev1"))

    # 退回不套用：文件層維持原值；草稿保留自己的快照供續編
    assert await _doc_tag_ids(db, doc_id) == {aud_a}
    assert await _version_tag_ids(db, ver2.version_id) == {aud_b}
