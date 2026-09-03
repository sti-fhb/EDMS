"""P1 文件生命週期端到端整合測試（T060，真實 DB）。

以真實 service 串接完整生命週期：新增草稿（US5）→ 送審（US5）→ 核准發布（US6）→ 文件庫檢索（US3）→
詳細頁下載記已看（US4）→ 編輯新版本（US5）→ 送審 → 核准（舊版 SUPERSEDED、新版 PUBLISHED）→
廢止申請（US8）→ 核准廢止（US8）。逐階段斷言狀態機與資料一致（DM_DOCUMENT / DM_DOC_VERSION /
DM_CHANGE_LOG / DM_DOC_READ）。收尾型：補跨 US 端到端，各 US 自身切片由既有測試覆蓋。
"""

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.catalog.models import DmTag
from app.dm.deps import DmContext
from app.dm.detail.service import DetailService
from app.dm.document.models import DmDocRead, DmDocument, DmDocVersion
from app.dm.editor.service import EditorService
from app.dm.library.schemas import DocumentQuery
from app.dm.library.service import LibraryService
from app.dm.obsolete.service import ObsoleteService
from app.dm.review.center_service import ReviewCenterService
from app.dm.review.models import DmChangeLog
from app.dm.roles.authz import DM_EDITOR, DM_REVIEWER, DM_VIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_editor = EditorService()
_review = ReviewCenterService()
_obsolete = ObsoleteService()
_detail = DetailService()
_library = LibraryService()
_PDF = "application/pdf"


@pytest.fixture(autouse=True)
def _storage_root(tmp_path, monkeypatch):
    """落盤根目錄導向 tmp（新增 / 下載共用），避免污染工作目錄。"""
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


async def _audience_id(db, name):
    return await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE", DmTag.tag_name == name))


async def _doc(db, doc_id):
    return await db.get(DmDocument, doc_id)


async def _version(db, version_id):
    return await db.get(DmDocVersion, version_id)


async def _change_log_ops(db, doc_id) -> list[str]:
    rows = await db.scalars(
        select(DmChangeLog.operation).where(DmChangeLog.doc_id == doc_id).order_by(DmChangeLog.change_log_id)
    )
    return list(rows.all())


async def test_p1_full_lifecycle(db):
    """新增 → 送審 → 發布 → 檢索 → 下載 → 改版 → 發布 → 廢止申請 → 核准廢止 全鏈。"""
    await _seed_user(db, "ed", "撰寫者")
    await _grant(db, "ed", DM_EDITOR)
    await _seed_user(db, "rev1", "審核者")
    await _grant(db, "rev1", DM_REVIEWER)
    await _seed_user(db, "viewer1", "閱覽者")
    await _grant(db, "viewer1", DM_VIEWER)
    all_aud = await _audience_id(db, "全體")

    # 1) 新增草稿 + 首版
    created = await _editor.create_document(
        db,
        doc_name="領血確認SOP",
        category_code="SOP",
        func_code=None,
        audience_ids=[all_aud],
        retrieval_ids=[],
        version_no="1.0",
        change_summary="首版",
        file_name="v1.pdf",
        file_bytes=b"%PDF-1.4 v1",
        file_mime=_PDF,
        op=_op("ed"),
    )
    doc_id, v1_id = created.doc_id, created.version_id
    assert (await _doc(db, doc_id)).status == "DRAFT"
    assert (await _version(db, v1_id)).status == "DRAFT"

    # 2) 送審
    submitted = await _editor.submit(db, doc_id=doc_id, version_id=v1_id, assigned_reviewer="rev1", op=_op("ed"))
    assert (await _version(db, v1_id)).status == "PENDING_REVIEW"

    # 3) 核准發布
    await _review.approve(db, review_id=submitted.review_id, op=_op("rev1"))
    doc = await _doc(db, doc_id)
    assert doc.status == "PUBLISHED" and doc.current_version_id == v1_id
    assert (await _version(db, v1_id)).status == "PUBLISHED"
    assert await _change_log_ops(db, doc_id) == ["PUBLISH"]

    # 4) 文件庫檢索見文件（以編輯者身分，不受可見性限制）
    res = await _library.search(
        db, query=DocumentQuery(keyword="領血"), ctx=DmContext(user_id="ed", roles=frozenset({DM_EDITOR})), page=1, limit=20
    )
    assert doc_id in [d.doc_id for d in res["data"]]

    # 5) 詳細頁下載 → 寫入 DM_DOC_READ（閱覽者、目前發布版）
    await _detail.prepare_file(
        db, doc_id=doc_id, version_id=v1_id, disposition="download", ctx=DmContext(user_id="viewer1", roles=frozenset({DM_VIEWER}))
    )
    read_cnt = await db.scalar(
        select(func.count())
        .select_from(DmDocRead)
        .where(DmDocRead.doc_id == doc_id, DmDocRead.version_id == v1_id, DmDocRead.created_user == "viewer1")
    )
    assert read_cnt == 1

    # 6) 編輯新版本（草稿）
    ver2 = await _editor.add_version(
        db,
        doc_id=doc_id,
        audience_ids=[all_aud],
        retrieval_ids=[],
        version_no="2.0",
        change_summary="改版重寫",
        file_name="v2.pdf",
        file_bytes=b"%PDF-1.4 v2",
        file_mime=_PDF,
        op=_op("ed"),
    )
    v2_id = ver2.version_id

    # 7) 送審新版
    submitted2 = await _editor.submit(db, doc_id=doc_id, version_id=v2_id, assigned_reviewer="rev1", op=_op("ed"))

    # 8) 核准 → 新版發布、舊版被取代
    await _review.approve(db, review_id=submitted2.review_id, op=_op("rev1"))
    doc = await _doc(db, doc_id)
    assert doc.status == "PUBLISHED" and doc.current_version_id == v2_id
    assert (await _version(db, v2_id)).status == "PUBLISHED"
    assert (await _version(db, v1_id)).status == "SUPERSEDED"
    assert await _change_log_ops(db, doc_id) == ["PUBLISH", "PUBLISH"]

    # 9) 廢止申請
    init = await _obsolete.initiate(
        db, doc_id=doc_id, reason="業務調整不再使用", reviewer_id="rev1", file_name=None, file_bytes=None, file_mime=None, op=_op("ed")
    )
    assert (await _doc(db, doc_id)).status == "PENDING_OBSOLETE"

    # 10) 核准廢止
    await _review.approve(db, review_id=init.review_id, op=_op("rev1"))
    assert (await _doc(db, doc_id)).status == "OBSOLETE"
    assert await _change_log_ops(db, doc_id) == ["PUBLISH", "PUBLISH", "OBSOLETE"]
