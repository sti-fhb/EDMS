"""送簽可見對象必填檢核之分類分支（#377）。

可見對象改查版本層快照（文件層於核准發布時才更新）；TRAINING 分類免填——訓練教材由 ET 引用，
ET 取教材不套可見性條件（`dm/integration/service.py`），可見對象對教師 / 學員零作用。
非 TRAINING 未掛可見對象仍須擋下（DM_DOC_005 / DM-MSG-DM03-008）。
"""

from types import SimpleNamespace

import pytest

from app.core.exceptions import AppError
from app.dm.editor.service import EditorService

pytestmark = pytest.mark.unit


class _StubRepo:
    """僅回應 `_ensure_submittable` 用到的查詢；其餘檢核一律放行，以隔離可見對象這條分支。"""

    def __init__(self, *, has_audience: bool) -> None:
        self._has_audience = has_audience

    async def version_no_taken(self, db, doc_id, version_no) -> bool:
        return False

    async def has_audience_tag(self, db, version_id) -> bool:
        return self._has_audience

    async def manual_func_published_elsewhere(self, db, func_code, exclude_doc_id) -> bool:
        return False

    async def has_pending_obsolete(self, db, doc_id) -> bool:
        return False


def _doc(category_code: str):
    return SimpleNamespace(
        doc_id="DM-SOP-000001", status="PUBLISHED", category_code=category_code, func_code=None
    )


def _ver():
    return SimpleNamespace(version_id=42, version_no="1.0", change_summary="變更摘要", file_path="d/f.pdf")


async def test_non_training_without_audience_is_blocked():
    """非 TRAINING 分類未掛可見對象 → 擋下並回 DM_DOC_005。"""
    svc = EditorService(repository=_StubRepo(has_audience=False))

    with pytest.raises(AppError) as exc:
        await svc._ensure_submittable(None, _doc("SOP"), _ver())

    assert exc.value.error_code == "DM_DOC_005"


async def test_training_without_audience_is_allowed():
    """TRAINING 分類未掛可見對象 → 放行（免填，不再擋 DM_DOC_005）。"""
    svc = EditorService(repository=_StubRepo(has_audience=False))

    await svc._ensure_submittable(None, _doc("TRAINING"), _ver())  # 不拋例外即為通過


async def test_non_training_with_audience_passes():
    """非 TRAINING 分類已掛可見對象 → 放行。"""
    svc = EditorService(repository=_StubRepo(has_audience=True))

    await svc._ensure_submittable(None, _doc("SOP"), _ver())
