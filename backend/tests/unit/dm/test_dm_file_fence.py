"""storage-root 圍籬單元測試（#160，純函式；以 monkeypatch 設定已知根目錄）。"""

import os

import pytest

from app.core.config import settings
from app.core.exceptions import AppError
from app.dm.document.file_paths import is_within_root, resolve_within_root, storage_root

_NF = AppError(status_code=404, detail="查無此文件或無權存取", error_code="DM_DOC_001")


def _set_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))
    return str(tmp_path)


def test_within_root_ok(tmp_path, monkeypatch):
    _set_root(tmp_path, monkeypatch)
    p = os.path.join(str(tmp_path), "DM-TRAINING-000001", "v1.0.pdf")
    assert is_within_root(p) is True
    assert resolve_within_root(p, not_found=_NF) == os.path.realpath(p)


def test_root_itself_within(tmp_path, monkeypatch):
    _set_root(tmp_path, monkeypatch)
    assert is_within_root(storage_root()) is True


def test_dotdot_escape_blocked(tmp_path, monkeypatch):
    _set_root(tmp_path, monkeypatch)
    p = os.path.join(str(tmp_path), "..", "evil.pdf")
    assert is_within_root(p) is False
    with pytest.raises(AppError) as e:
        resolve_within_root(p, not_found=_NF)
    assert e.value.status_code == 404 and e.value.error_code == "DM_DOC_001"


def test_absolute_outside_blocked(tmp_path, monkeypatch):
    _set_root(tmp_path, monkeypatch)
    outside = os.path.join(str(tmp_path.parent), "outside_secret.pdf")
    assert is_within_root(outside) is False
    with pytest.raises(AppError):
        resolve_within_root(outside, not_found=_NF)


def test_sibling_prefix_not_treated_as_within(tmp_path, monkeypatch):
    """root 之字首相同的兄弟目錄（root 為 .../store，路徑在 .../store_evil）不得誤判為 within。"""
    _set_root(tmp_path / "store", monkeypatch)
    sibling = os.path.join(str(tmp_path), "store_evil", "a.pdf")
    assert is_within_root(sibling) is False


@pytest.mark.parametrize("bad", [None, "", 123])
def test_none_or_invalid_fail_closed(tmp_path, monkeypatch, bad):
    """None / 空字串 / 非字串 → fail-closed（回 False / raise not_found），不 TypeError 500（Sec LOW-1）。"""
    _set_root(tmp_path, monkeypatch)
    assert is_within_root(bad) is False
    with pytest.raises(AppError):
        resolve_within_root(bad, not_found=_NF)


def test_resolve_returns_same_path_validated(tmp_path, monkeypatch):
    """回傳之 canonical 路徑即被驗證者（單次 realpath，Sec LOW-2）。"""
    _set_root(tmp_path, monkeypatch)
    p = os.path.join(str(tmp_path), "sub", "..", "a.pdf")  # 正規化後 = {root}/a.pdf，仍在 root 內
    resolved = resolve_within_root(p, not_found=_NF)
    assert resolved == os.path.realpath(p) and is_within_root(resolved)


# ── 相對 FILE_PATH（#233）─────────────────────────────────────
# DB 改存「相對於 storage root 的片段」後，圍籬須以 root 為基準解析；
# 既有絕對路徑資料若仍落在 root 內亦須照常讀取（免 big-bang 轉換）。
# 關鍵安全不變式：join 之後 commonpath 檢查一律保留，穿越 / 注入不得放寬。


def test_relative_path_resolves_under_root(tmp_path, monkeypatch):
    """相對片段以 storage root 為基準解析（#233 核心行為）。"""
    root = _set_root(tmp_path, monkeypatch)
    rel = "DM-MANUAL-900010/abc123.pdf"
    assert is_within_root(rel) is True
    assert resolve_within_root(rel, not_found=_NF) == os.path.realpath(os.path.join(root, rel))


def test_relative_path_with_backslash_stays_within_root(tmp_path, monkeypatch):
    r"""反斜線分隔之相對片段不得逃出圍籬。

    寫入端固定產出 `/`；本測試守的是過渡期 DB 內既有 `\` 資料的安全性，
    非路徑等價性——POSIX 上 `\` 是合法檔名字元、不作分隔符，故只斷言仍在 root 內。
    """
    _set_root(tmp_path, monkeypatch)
    assert is_within_root(r"DM-MANUAL-900010\abc123.pdf") is True


def test_relative_dotdot_escape_blocked(tmp_path, monkeypatch):
    """相對片段含 `../` 逃出 root 一律擋（改存相對路徑後不得放寬穿越防護）。"""
    _set_root(tmp_path, monkeypatch)
    assert is_within_root("../../evil.pdf") is False
    with pytest.raises(AppError):
        resolve_within_root("../../evil.pdf", not_found=_NF)


def test_legacy_absolute_within_root_still_resolves(tmp_path, monkeypatch):
    """既有絕對路徑若仍落在當前 root 內須照常讀取（向後相容，AC3）。"""
    root = _set_root(tmp_path, monkeypatch)
    legacy = os.path.join(root, "DM-MANUAL-900010", "abc123.pdf")
    assert resolve_within_root(legacy, not_found=_NF) == os.path.realpath(legacy)


def test_absolute_injection_outside_root_still_blocked(tmp_path, monkeypatch):
    """絕對路徑注入仍須擋下。

    `os.path.join(root, x)` 對絕對 `x` 會丟棄 root 直接回 `x`——看似形成注入面，
    但其後的 commonpath fail-closed 檢查仍攔得住。此測試即守住該檢查不被重構掉。
    """
    _set_root(tmp_path / "store", monkeypatch)
    outside = os.path.join(str(tmp_path), "outside_secret.pdf")
    assert is_within_root(outside) is False
    with pytest.raises(AppError):
        resolve_within_root(outside, not_found=_NF)
