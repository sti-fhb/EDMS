"""storage-root 圍籬單元測試（#160，純函式；以 monkeypatch 設定已知根目錄）。"""

import os

import pytest

from app.core.config import settings
from app.core.exceptions import AppError
from app.dm.document.file_paths import is_within_root, resolve_within_root, storage_root


def _set_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))
    return str(tmp_path)


def test_within_root_ok(tmp_path, monkeypatch):
    _set_root(tmp_path, monkeypatch)
    p = os.path.join(str(tmp_path), "DM-TRAINING-000001", "v1.0.pdf")
    assert is_within_root(p) is True
    assert resolve_within_root(p) == os.path.realpath(p)


def test_root_itself_within(tmp_path, monkeypatch):
    _set_root(tmp_path, monkeypatch)
    assert is_within_root(storage_root()) is True


def test_dotdot_escape_blocked(tmp_path, monkeypatch):
    _set_root(tmp_path, monkeypatch)
    p = os.path.join(str(tmp_path), "..", "evil.pdf")
    assert is_within_root(p) is False
    with pytest.raises(AppError) as e:
        resolve_within_root(p)
    assert e.value.status_code == 404 and e.value.error_code == "DM_DOC_001"


def test_absolute_outside_blocked(tmp_path, monkeypatch):
    _set_root(tmp_path, monkeypatch)
    outside = os.path.join(str(tmp_path.parent), "outside_secret.pdf")
    assert is_within_root(outside) is False
    with pytest.raises(AppError):
        resolve_within_root(outside)


def test_sibling_prefix_not_treated_as_within(tmp_path, monkeypatch):
    """root 之字首相同的兄弟目錄（root 為 .../store，路徑在 .../store_evil）不得誤判為 within。"""
    _set_root(tmp_path / "store", monkeypatch)
    sibling = os.path.join(str(tmp_path), "store_evil", "a.pdf")
    assert is_within_root(sibling) is False
