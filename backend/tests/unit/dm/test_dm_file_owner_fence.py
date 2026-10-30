"""DM 四個取檔呼叫端之檔案歸屬圍籬（#240 A1；stub repository，不需真 DB）。

`resolve_within_root` 的 `expect_prefix` 本身已在 `test_dm_file_fence.py` 驗過；本檔守的是
**呼叫端確實有傳**——四處任一漏傳，該端點就退回「只驗在 root 內」，而純函式測試不會紅。

情境一律是：授權以 A 文件（`_DOC`）判定通過，但該版本的 `FILE_PATH` 指向 B 文件（`_OTHER`）
目錄。正確行為是 404（與「查無」同一回應），而不是串流出 B 文件的檔。
"""

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.dm.deps import DmContext
from app.dm.detail.service import DetailService
from app.dm.integration.service import DmDocumentService
from app.dm.review.center_service import ReviewCenterService
from app.dm.roles.authz import DM_ADMIN

pytestmark = pytest.mark.unit

_DOC ="DM-TRAINING-000001"
_OTHER = "DM-TRAINING-000999"
_OWN_PATH = f"{_DOC}/abc123.pdf"
_FOREIGN_PATH = f"{_OTHER}/abc123.pdf"
_VERSION_ID = 7
_REVIEW_ID = 3
_REVIEWER = "rv"


@pytest.fixture(autouse=True)
def _root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))


class _Repo:
    """依測試需要回傳固定值之 stub；未用到的方法不實作，誤呼叫即 AttributeError。"""

    def __init__(self, **returns):
        for name, value in returns.items():
            setattr(self, name, self._returning(value))

    @staticmethod
    def _returning(value):
        async def _fn(*_args, **_kwargs):
            return value

        return _fn


# ── DetailService.prepare_file（US4 文件詳細頁取檔）──────────────


def _detail(file_path: str) -> DetailService:
    return DetailService(
        repository=_Repo(
            get_document_meta=SimpleNamespace(current_version_id=_VERSION_ID, status="PUBLISHED"),
            get_version_file=SimpleNamespace(file_path=file_path, file_mime="application/pdf", file_name="a.pdf"),
        )
    )


async def _detail_preview(svc: DetailService):
    return await svc.prepare_file(
        None, doc_id=_DOC, version_id=_VERSION_ID, disposition="preview", ctx=DmContext("u", frozenset())
    )


async def test_detail_own_file_served():
    assert (await _detail_preview(_detail(_OWN_PATH))).path.endswith("abc123.pdf")


async def test_detail_foreign_file_404():
    with pytest.raises(AppError) as e:
        await _detail_preview(_detail(_FOREIGN_PATH))
    assert e.value.status_code == 404 and e.value.error_code == "DM_DOC_001"


# ── DmDocumentService.read_file_for_reference（ET 學員取 DM 教材檔）──


def _integration(file_path: str) -> DmDocumentService:
    return DmDocumentService(
        repository=_Repo(
            get_document=SimpleNamespace(doc_id=_DOC, category_code="TRAINING", current_version_id=_VERSION_ID),
            get_version=SimpleNamespace(
                doc_id=_DOC, file_path=file_path, file_mime="application/pdf", file_name="a.pdf"
            ),
        )
    )


async def test_integration_own_file_served():
    content = await _integration(_OWN_PATH).read_file_for_reference(None, doc_id=_DOC, version_id=_VERSION_ID)
    assert content.path.endswith("abc123.pdf")


async def test_integration_foreign_file_404():
    """讀取者是無任何 DM 角色的 ET 學員——本端點不掛 DM 角色閘，歸屬圍籬是最後一道。"""
    with pytest.raises(AppError) as e:
        await _integration(_FOREIGN_PATH).read_file_for_reference(None, doc_id=_DOC, version_id=_VERSION_ID)
    assert e.value.status_code == 404 and e.value.error_code == "DM_DOC_001"


# ── ReviewCenterService（簽核中心：送審檔 / 廢止附件）────────────


def _review(**overrides) -> SimpleNamespace:
    fields = {
        "review_id": _REVIEW_ID,
        "doc_id": _DOC,
        "version_id": _VERSION_ID,
        "review_type": "OBSOLETE",
        "assigned_reviewer": _REVIEWER,
        "obsolete_file_path": _OWN_PATH,
        "obsolete_file_mime": "application/pdf",
        "obsolete_file_name": "a.pdf",
    }
    return SimpleNamespace(**(fields | overrides))


def _center(review: SimpleNamespace, version_path: str = _OWN_PATH) -> ReviewCenterService:
    return ReviewCenterService(
        repository=_Repo(
            get_review=review,
            get_document=SimpleNamespace(doc_id=_DOC, current_version_id=_VERSION_ID),
            get_version=SimpleNamespace(file_path=version_path, file_mime="application/pdf", file_name="a.pdf"),
        )
    )


async def test_center_review_file_own_served():
    svc = _center(_review(review_type="NEW_VERSION"))
    f = await svc.prepare_file(None, review_id=_REVIEW_ID, version_id=_VERSION_ID, op=OperatorInfo(_REVIEWER))
    assert f.path.endswith("abc123.pdf")


async def test_center_review_file_foreign_404():
    svc = _center(_review(review_type="NEW_VERSION"), version_path=_FOREIGN_PATH)
    with pytest.raises(AppError) as e:
        await svc.prepare_file(None, review_id=_REVIEW_ID, version_id=_VERSION_ID, op=OperatorInfo(_REVIEWER))
    assert e.value.status_code == 404 and e.value.error_code == "DM_DOC_001"


async def test_center_obsolete_attachment_own_served():
    svc = _center(_review())
    f = await svc.prepare_obsolete_file(None, review_id=_REVIEW_ID, roles=[DM_ADMIN], op=OperatorInfo("admin"))
    assert f.path.endswith("abc123.pdf")


async def test_center_obsolete_attachment_foreign_404():
    """廢止附件之歸屬以該 review 之 `DOC_ID` 判定。"""
    svc = _center(_review(obsolete_file_path=_FOREIGN_PATH))
    with pytest.raises(AppError) as e:
        await svc.prepare_obsolete_file(None, review_id=_REVIEW_ID, roles=[DM_ADMIN], op=OperatorInfo("admin"))
    assert e.value.status_code == 404 and e.value.error_code == "DM_DOC_001"
