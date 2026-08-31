"""ET 影片 storage-root 圍籬單元測試（#233；純函式，以 monkeypatch 設定已知根目錄）。

`ET_MATERIAL_VIDEO.FILE_PATH` 改存「相對於 `ET_VIDEO_STORAGE_ROOT` 的片段」後，圍籬須以
root 為基準解析。本檔比照 DM 之 `tests/unit/dm/test_dm_file_fence.py`——ET 側原先沒有圍籬
測試（影片播放端點尚未實作、`resolve_within_root` 無呼叫端），趁改動時一併補上，避免日後
播放端點落地時才發現圍籬從未被驗證過。

讀取者可能是**無任何 DM / 管理權限的學員**（見 `app/et/material/storage.py` 模組 docstring），
故圍籬失效的影響面大於一般端點。
"""

import os

import pytest

from app.core.config import settings
from app.core.exceptions import AppError
from app.et.material.storage import resolve_within_root, storage_root

_NF = AppError(status_code=404, detail="查無此影片", error_code="ET_MATERIAL_001")


def _set_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ET_VIDEO_STORAGE_ROOT", str(tmp_path))
    return str(tmp_path)


def test_relative_path_resolves_under_root(tmp_path, monkeypatch):
    """相對片段以 storage root 為基準解析（#233 核心行為）。"""
    root = _set_root(tmp_path, monkeypatch)
    rel = "11/29ef331bdee4462991704274df9ac962.mp4"
    assert resolve_within_root(rel, not_found=_NF) == os.path.realpath(os.path.join(root, rel))


def test_legacy_absolute_within_root_still_resolves(tmp_path, monkeypatch):
    """既有絕對路徑若仍落在當前 root 內須照常讀取（向後相容，AC3）。"""
    root = _set_root(tmp_path, monkeypatch)
    legacy = os.path.join(root, "11", "abc.mp4")
    assert resolve_within_root(legacy, not_found=_NF) == os.path.realpath(legacy)


def test_relative_dotdot_escape_blocked(tmp_path, monkeypatch):
    """相對片段含 `../` 逃出 root 一律擋。"""
    _set_root(tmp_path, monkeypatch)
    with pytest.raises(AppError) as e:
        resolve_within_root("../../evil.mp4", not_found=_NF)
    assert e.value.status_code == 404 and e.value.error_code == "ET_MATERIAL_001"


def test_absolute_injection_outside_root_blocked(tmp_path, monkeypatch):
    """絕對路徑注入須擋下。

    `os.path.join(root, x)` 對絕對 `x` 會丟棄 root 直接回 `x`，**commonpath 檢查是唯一防線**；
    此測試即守住該檢查不被重構掉。
    """
    _set_root(tmp_path / "store", monkeypatch)
    outside = os.path.join(str(tmp_path), "outside_secret.mp4")
    with pytest.raises(AppError):
        resolve_within_root(outside, not_found=_NF)


def test_sibling_prefix_not_treated_as_within(tmp_path, monkeypatch):
    """root 之字首相同的兄弟目錄（root 為 .../store，路徑在 .../store_evil）不得誤判為 within。"""
    _set_root(tmp_path / "store", monkeypatch)
    sibling = os.path.join(str(tmp_path), "store_evil", "a.mp4")
    with pytest.raises(AppError):
        resolve_within_root(sibling, not_found=_NF)


@pytest.mark.parametrize("bad", [None, "", 123])
def test_none_or_invalid_fail_closed(tmp_path, monkeypatch, bad):
    """None / 空字串 / 非字串 → fail-closed（raise not_found），不 TypeError 500。"""
    _set_root(tmp_path, monkeypatch)
    with pytest.raises(AppError):
        resolve_within_root(bad, not_found=_NF)


def test_root_itself_resolves(tmp_path, monkeypatch):
    """root 本身（相對片段為 `.`）落在 root 內。"""
    root = _set_root(tmp_path, monkeypatch)
    assert resolve_within_root(".", not_found=_NF) == os.path.realpath(root)


def test_resolve_returns_same_path_validated(tmp_path, monkeypatch):
    """回傳之 canonical 路徑即被驗證者（單次 realpath，避免 TOCTOU）。"""
    root = _set_root(tmp_path, monkeypatch)
    rel = "sub/../a.mp4"  # 正規化後 = {root}/a.mp4，仍在 root 內
    assert resolve_within_root(rel, not_found=_NF) == os.path.realpath(os.path.join(root, rel))


def test_storage_root_is_absolute(tmp_path, monkeypatch):
    """storage_root() 回正規化絕對路徑（相對設定值依 CWD 解析，見 #239）。"""
    _set_root(tmp_path, monkeypatch)
    assert os.path.isabs(storage_root())
