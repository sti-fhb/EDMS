"""跨模組門面 `DM_DOC_001` 被吞掉 N 次後 traceback 不成長（#289 Q1）。

ET 端有 5 處以 `except AppError` 攔下 `DmDocumentService` 的錯誤後**不重拋**（改回
`available=False` / `unavailable=True`、跳過、或記 log 後 `continue`），其中每日排程
`doc_change_service` 不需任何使用者操作就會觸發。被吞掉的例外走不到
`main.app_error_handler`，裁示 B 的清理碰不到它；若拒絕用的是模組層級常數，每次 raise 都把
本次 frame 附加到同一個 traceback 上，只增不減。

本檔模擬「呼叫端吞掉」：迴圈呼叫、攔下、不重拋，驗證每次都是新實例，且第一次攔到的例外
在之後 N 輪過後 traceback 深度不變。用 stub repository 即可，不需真 DB（行程內記憶體行為）。
"""

import traceback
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.core.exceptions import AppError
from app.dm.integration.service import DmDocumentService

pytestmark = pytest.mark.unit

_ROUNDS = 10
_DOC = "DM-TRAINING-000001"
_VERSION_ID = 7


@pytest.fixture(autouse=True)
def _root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))


class _Repo:
    """回傳固定值之 stub；未用到的方法不實作，誤呼叫即 AttributeError。"""

    def __init__(self, *, document=None, version=None):
        self._document = document
        self._version = version

    async def get_document(self, _db, _doc_id):
        return self._document

    async def get_version(self, _db, _version_id):
        return self._version


def _doc(category: str = "TRAINING", current_version_id: int | None = _VERSION_ID):
    return SimpleNamespace(
        doc_id=_DOC, doc_name="教材", category_code=category, current_version_id=current_version_id, status="PUBLISHED"
    )


def _ver(file_path: str | None = f"{_DOC}/a.pdf", doc_id: str = _DOC):
    return SimpleNamespace(version_id=_VERSION_ID, doc_id=doc_id, file_path=file_path, file_mime=None, file_name=None)


def _depth(exc: BaseException) -> int:
    return len(traceback.extract_tb(exc.__traceback__))


async def _swallow(call) -> list[AppError]:
    """比照 ET 端吞掉點：攔下 `AppError` 後不重拋，只留下實例。"""
    swallowed: list[AppError] = []
    for _ in range(_ROUNDS):
        try:
            await call()
        except AppError as exc:
            swallowed.append(exc)
        else:  # pragma: no cover - 情境設定錯誤才會走到
            pytest.fail("預期拋出 DM_DOC_001")
    return swallowed


def _assert_no_growth(swallowed: list[AppError]) -> None:
    assert len(swallowed) == _ROUNDS
    assert {(e.status_code, e.error_code) for e in swallowed} == {(404, "DM_DOC_001")}
    # 持有全部實例時 id 不會被回收重用，故 id 相異即代表每次都是新實例。
    assert len({id(e) for e in swallowed}) == _ROUNDS
    # 第一次吞下的例外，在之後 N-1 輪過後深度仍與最後一次相同——常數寫法下前者會是後者的 N 倍。
    assert _depth(swallowed[0]) == _depth(swallowed[-1])


_GET_CURRENT_CASES = {
    "查無文件": _Repo(document=None),
    "非可引用分類": _Repo(document=_doc(category="SOP")),
    "當前版不存在": _Repo(document=_doc(), version=None),
}

_READ_FILE_CASES = {
    "查無文件": _Repo(document=None),
    "非可引用分類": _Repo(document=_doc(category="SOP")),
    "版本不存在": _Repo(document=_doc(), version=None),
    "版本不屬於本文件": _Repo(document=_doc(), version=_ver(doc_id="DM-TRAINING-000999")),
    "版本無落地檔": _Repo(document=_doc(), version=_ver(file_path=None)),
    # 走 `resolve_within_root(not_found=...)`：#860 / #240 圍籬攔下時拋的也必須是新實例。
    "檔案逃逸出根目錄": _Repo(document=_doc(), version=_ver(file_path="../outside.pdf")),
    "檔案不在本文件目錄": _Repo(document=_doc(), version=_ver(file_path="DM-TRAINING-000999/a.pdf")),
}


class TestDmDocumentService被吞掉不累積:
    @pytest.mark.parametrize("repo", _GET_CURRENT_CASES.values(), ids=_GET_CURRENT_CASES.keys())
    async def test_get_current_by_doc_id(self, repo: _Repo) -> None:
        """SRVDM001：ET 吞掉點全數經此（learning / material / publish / doc_change）。"""
        svc = DmDocumentService(repository=repo)  # type: ignore[arg-type]
        _assert_no_growth(await _swallow(lambda: svc.get_current_by_doc_id(None, _DOC)))

    @pytest.mark.parametrize("repo", _READ_FILE_CASES.values(), ids=_READ_FILE_CASES.keys())
    async def test_read_file_for_reference(self, repo: _Repo) -> None:
        """取檔：ET 端以 `raise ... from exc` 改拋，被攔下的 DM 例外仍掛在 `__cause__` 上。"""
        svc = DmDocumentService(repository=repo)  # type: ignore[arg-type]
        _assert_no_growth(
            await _swallow(lambda: svc.read_file_for_reference(None, doc_id=_DOC, version_id=_VERSION_ID))
        )
