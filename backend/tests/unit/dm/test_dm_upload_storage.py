r"""DM 上傳落盤之回傳值契約（#233）。

`save_upload` 實際寫檔仍用絕對路徑（`makedirs` / `open` 需要），但**回傳給 DB 記錄的是
相對於 storage root 的片段**——存絕對路徑會讓 `FILE_PATH` 綁死在當下的機器與工作目錄，
worktree 一被清掉即永久失聯（#233 任務說明）。

分隔符固定 `/`：Windows 上讀取端 `os.path.join(root, "a/b.pdf")` 正常且 `realpath` 會正規化，
反之若存 `\` 則 POSIX 讀不到（`\` 在 POSIX 是合法檔名字元、不作分隔符）。
"""

import os

import pytest

from app.core.config import settings
from app.dm.document.file_paths import is_within_root, storage_root
from app.dm.editor.storage import generate_file_id, save_upload

_DOC_ID = "DM-MANUAL-900010"
_DATA = b"%PDF-1.4 fake"


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DM_FILE_STORAGE_ROOT", str(tmp_path))
    return str(tmp_path)


def test_returns_relative_segment_not_absolute(root):
    """回傳值為相對片段，不得是絕對路徑。"""
    rel = save_upload(doc_id=_DOC_ID, file_id="abc123", filename="a.pdf", data=_DATA)
    assert rel == f"{_DOC_ID}/abc123.pdf"
    assert not os.path.isabs(rel)


def test_returned_separator_is_forward_slash(root):
    r"""分隔符固定 `/`——存 `\` 會讓同一筆資料在 POSIX 讀不到。"""
    rel = save_upload(doc_id=_DOC_ID, file_id="abc123", filename="a.pdf", data=_DATA)
    assert "\\" not in rel


def test_file_actually_written_under_root(root):
    """回傳相對路徑，但檔案實際落在 root 下的絕對位置且內容正確。"""
    rel = save_upload(doc_id=_DOC_ID, file_id="abc123", filename="a.pdf", data=_DATA)
    abs_path = os.path.join(root, rel)
    assert os.path.isfile(abs_path)
    with open(abs_path, "rb") as f:
        assert f.read() == _DATA


def test_returned_value_passes_read_side_fence(root):
    """回傳值直接餵給讀取端圍籬須通過——寫入端與讀取端的契約必須對得上。"""
    rel = save_upload(doc_id=_DOC_ID, file_id="abc123", filename="a.pdf", data=_DATA)
    assert is_within_root(rel) is True


def test_no_extension_filename(root):
    """原始檔名無副檔名時，回傳片段僅含 file_id。"""
    rel = save_upload(doc_id=_DOC_ID, file_id="abc123", filename="noext", data=_DATA)
    assert rel == f"{_DOC_ID}/abc123"


def test_illegal_extension_chars_dropped(root):
    """副檔名含非英數字元一律捨棄（既有安全行為，不得因本次改動而變）。"""
    rel = save_upload(doc_id=_DOC_ID, file_id="abc123", filename="a.p df", data=_DATA)
    assert rel == f"{_DOC_ID}/abc123"


def test_path_traversal_doc_id_rejected(root):
    """受污染之 doc_id 仍須擋下（寫入端圍籬，既有行為）。"""
    with pytest.raises(ValueError):
        save_upload(doc_id="../evil", file_id="abc123", filename="a.pdf", data=_DATA)


def test_relative_stays_valid_after_root_moves(root, tmp_path):
    """把 root 換到別處、檔案搬過去，同一筆相對片段仍解析得到——本 issue 的核心價值。"""
    rel = save_upload(doc_id=_DOC_ID, file_id="abc123", filename="a.pdf", data=_DATA)
    original = os.path.join(root, rel)

    new_root = tmp_path / "moved_elsewhere"
    os.makedirs(os.path.join(str(new_root), _DOC_ID), exist_ok=True)
    os.replace(original, os.path.join(str(new_root), rel))
    settings.DM_FILE_STORAGE_ROOT = str(new_root)
    try:
        assert storage_root() == os.path.realpath(str(new_root))
        assert is_within_root(rel) is True
        assert os.path.isfile(os.path.join(storage_root(), rel))
    finally:
        settings.DM_FILE_STORAGE_ROOT = root


def test_file_id_is_random_hex(root):
    """FILE_ID 為隨機不可猜之 hex（既有行為，避免以原始檔名組路徑）。"""
    a, b = generate_file_id(), generate_file_id()
    assert a != b and len(a) == 32 and all(c in "0123456789abcdef" for c in a)
