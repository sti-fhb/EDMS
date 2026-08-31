r"""ET 影片落盤之回傳值契約與回滾正確性（#233）。

`promote` 回 `(絕對路徑, 相對片段)`——兩者都需要，且用途不可混：

| 用途 | 要哪一個 | 若拿錯 |
|------|---------|--------|
| 寫入 `ET_MATERIAL_VIDEO.FILE_PATH` | 相對片段 | 換 root 即永久失聯（#233 任務說明）|
| 失敗回滾 `discard()` 刪檔 | 絕對路徑 | `os.remove` 找不到檔案、靜默失敗 → 孤兒檔 |

回滾那條特別容易漏：它在 `except` 分支，正常路徑的測試走不到，而 `discard` 內部把
`OSError` 吞掉只留一行 warning，所以「刪不掉」不會以任何形式冒出來。
"""

import os

import pytest

from app.core.config import settings
from app.et.material import storage

_MATERIAL_ID = "11"


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ET_VIDEO_STORAGE_ROOT", str(tmp_path))
    return str(tmp_path)


def _make_tmp_video(root: str, content: bytes = b"fake-mp4") -> str:
    """在 storage root 的 .tmp 下造一支暫存檔，模擬 save_video_stream 的產出。"""
    tmp_dir = os.path.join(root, storage.TMP_DIRNAME)
    os.makedirs(tmp_dir, exist_ok=True)
    p = os.path.join(tmp_dir, "staged.mp4")
    with open(p, "wb") as f:
        f.write(content)
    return p


def test_promote_returns_absolute_and_relative(root):
    """回 `(絕對, 相對)`：相對片段供 DB、絕對路徑供回滾刪檔。"""
    abs_path, rel = storage.promote(_make_tmp_video(root), video_id_hint=_MATERIAL_ID, ext="mp4")
    assert os.path.isabs(abs_path)
    assert not os.path.isabs(rel)
    assert os.path.realpath(abs_path) == os.path.realpath(os.path.join(root, rel))


def test_relative_segment_shape_and_separator(root):
    r"""相對片段為 `{material_id}/{uuid}.{ext}`，分隔符固定 `/`。"""
    _, rel = storage.promote(_make_tmp_video(root), video_id_hint=_MATERIAL_ID, ext="mp4")
    assert "\\" not in rel
    head, _, tail = rel.partition("/")
    assert head == _MATERIAL_ID
    assert tail.endswith(".mp4") and len(tail) == len("0" * 32) + len(".mp4")


def test_relative_passes_read_side_fence(root):
    """回傳的相對片段直接餵讀取端圍籬須通過——寫入端與讀取端契約必須對得上。"""
    _, rel = storage.promote(_make_tmp_video(root), video_id_hint=_MATERIAL_ID, ext="mp4")
    resolved = storage.resolve_within_root(rel, not_found=AssertionError("圍籬不應擋下自己寫出的路徑"))
    assert os.path.isfile(resolved)


def test_promote_is_atomic_move_not_copy(root):
    """暫存檔搬走後不應留在 .tmp（`os.replace` 而非複製）。"""
    tmp = _make_tmp_video(root)
    abs_path, _ = storage.promote(tmp, video_id_hint=_MATERIAL_ID, ext="mp4")
    assert not os.path.exists(tmp)
    assert os.path.isfile(abs_path)


def test_content_preserved(root):
    """搬移不得改動內容。"""
    abs_path, _ = storage.promote(_make_tmp_video(root, b"payload-123"), video_id_hint=_MATERIAL_ID, ext="mp4")
    with open(abs_path, "rb") as f:
        assert f.read() == b"payload-123"


def test_discard_with_absolute_path_removes_file(root):
    """回滾路徑：以 `promote` 回傳的絕對路徑呼叫 `discard` 須真的刪掉檔案。

    這正是 service 的 `except` 分支所做的事——若該處誤傳相對片段，`os.remove` 會相對
    process CWD 解析而找不到檔案，`discard` 吞掉 `OSError` 後留下孤兒檔且無人察覺。
    """
    abs_path, _ = storage.promote(_make_tmp_video(root), video_id_hint=_MATERIAL_ID, ext="mp4")
    assert os.path.isfile(abs_path)
    storage.discard(abs_path)
    assert not os.path.exists(abs_path)


def test_relative_stays_valid_after_root_moves(root, tmp_path):
    """把 root 換到別處、檔案搬過去，同一筆相對片段仍解析得到——本 issue 的核心價值。"""
    _, rel = storage.promote(_make_tmp_video(root), video_id_hint=_MATERIAL_ID, ext="mp4")
    new_root = tmp_path / "moved_elsewhere"
    os.makedirs(os.path.join(str(new_root), _MATERIAL_ID), exist_ok=True)
    os.replace(os.path.join(root, rel), os.path.join(str(new_root), rel))

    settings.ET_VIDEO_STORAGE_ROOT = str(new_root)
    try:
        resolved = storage.resolve_within_root(rel, not_found=AssertionError("搬 root 後應仍解析得到"))
        assert os.path.isfile(resolved)
    finally:
        settings.ET_VIDEO_STORAGE_ROOT = root
