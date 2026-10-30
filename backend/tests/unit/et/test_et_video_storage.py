r"""ET 影片落盤之回傳值契約與回滾正確性（#233）。

`promote` 回 `(絕對路徑, 相對片段)`——兩者都需要，且用途不可混：

| 用途 | 要哪一個 | 若拿錯 |
|------|---------|--------|
| 寫入 `ET_MATERIAL_VIDEO.FILE_PATH` | 相對片段 | 換 root 即永久失聯（#233 任務說明）|
| 失敗回滾 `discard()` 刪檔 | 絕對路徑 | `os.remove` 找不到檔案、靜默失敗 → 孤兒檔 |

回滾那條特別容易漏：它在 `except` 分支，正常路徑的測試走不到，而 `discard` 內部把
`OSError` 吞掉只留一行 warning，所以「刪不掉」不會以任何形式冒出來。
"""

import logging
import os

import pytest

from app.core.config import settings
from app.core.exceptions import AppError
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


# ── 寫入端圍籬（#240 A3）──────────────────────────────────────
# `save_video_stream` 寫在 root 下自建的 `.tmp/`，`promote` / `discard` 原本卻完全不驗路徑。
# 目前兩者只吃伺服器自建路徑而安全，但 `discard` 是「傳什麼就刪什麼」的原語——日後任何人
# 把 DB 值餵進去就是任意刪檔。圍籬放在函式本身，不依賴呼叫端。


def _outside_file(tmp_path, name: str = "outside.bin") -> str:
    """在 storage root **之外**造一支檔，作為不得被搬動 / 刪除的對象。"""
    p = tmp_path.parent / f"{tmp_path.name}_{name}"
    p.write_bytes(b"do-not-touch")
    return str(p)


def test_promote_rejects_hint_escaping_root(root, tmp_path):
    """`video_id_hint` 帶 `..` 逃出 root → `ET_MATERIAL_007`，暫存檔原地不動、root 外不落檔。"""
    staged = _make_tmp_video(root)
    with pytest.raises(AppError) as e:
        storage.promote(staged, video_id_hint="../escaped", ext="mp4")
    assert e.value.status_code == 422 and e.value.error_code == "ET_MATERIAL_007"
    assert os.path.isfile(staged)
    assert not (tmp_path.parent / "escaped").exists()


def test_promote_rejects_source_outside_root(root, tmp_path):
    """來源在 root 外 → 拒絕，不得把 root 外的檔搬進來（等於讓它可經串流端點被讀取）。"""
    outside = _outside_file(tmp_path)
    with pytest.raises(AppError) as e:
        storage.promote(outside, video_id_hint=_MATERIAL_ID, ext="mp4")
    assert e.value.error_code == "ET_MATERIAL_007"
    assert os.path.isfile(outside)


@pytest.mark.parametrize("hint", ["", ".tmp", "abc", "1/2", "\u00b2"])
def test_promote_rejects_non_numeric_hint(root, hint):
    """目錄名須為純 ASCII 數字：空字串 / `.tmp` 會落在 root 頂層或暫存區，巢狀與非數字亦不合預期。"""
    staged = _make_tmp_video(root)
    with pytest.raises(AppError) as e:
        storage.promote(staged, video_id_hint=hint, ext="mp4")
    assert e.value.error_code == "ET_MATERIAL_007"
    assert os.path.isfile(staged)


def test_promote_rejects_source_in_root_but_not_staging(root):
    """root 內、但不在 `.tmp/` 的檔（如另一份教材被引用中的影片）不得被搬走——否則原教材失聯。"""
    referenced = os.path.join(root, "7", "ref.mp4")
    os.makedirs(os.path.dirname(referenced))
    with open(referenced, "wb") as f:
        f.write(b"in-use")
    with pytest.raises(AppError) as e:
        storage.promote(referenced, video_id_hint=_MATERIAL_ID, ext="mp4")
    assert e.value.error_code == "ET_MATERIAL_007"
    assert os.path.isfile(referenced)


def test_promote_rejects_symlink_source(root, tmp_path):
    """`.tmp/` 下的 symlink 不是暫存檔——搬過去會在正式區留下一個指向他處的連結。"""
    outside = _outside_file(tmp_path)
    tmp_dir = os.path.join(root, storage.TMP_DIRNAME)
    os.makedirs(tmp_dir, exist_ok=True)
    link = os.path.join(tmp_dir, "link.mp4")
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("此平台不允許建立 symlink")
    with pytest.raises(AppError):
        storage.promote(link, video_id_hint=_MATERIAL_ID, ext="mp4")
    assert os.path.islink(link)


def test_promote_rejection_logged_without_path(root, tmp_path, caplog):
    """攔截時記安全事件，但不記路徑（sti-backend-logging）。"""
    with caplog.at_level(logging.WARNING), pytest.raises(AppError):
        storage.promote(_make_tmp_video(root), video_id_hint="../escaped", ext="mp4")
    assert caplog.records
    assert "escaped" not in caplog.text and root not in caplog.text


def test_discard_refuses_path_outside_root(root, tmp_path, caplog):
    """root 外之路徑 → 拒刪並記安全事件（不記路徑），不拋錯。"""
    outside = _outside_file(tmp_path)
    with caplog.at_level(logging.WARNING):
        storage.discard(outside)
    assert os.path.isfile(outside)
    assert caplog.records and outside not in caplog.text


def test_discard_refuses_dotdot_escape(root, tmp_path):
    """root 內起頭、以 `..` 繞出去的絕對路徑一樣拒刪。"""
    outside = _outside_file(tmp_path)
    storage.discard(os.path.join(root, "..", os.path.basename(outside)))
    assert os.path.isfile(outside)


def test_discard_refuses_relative_path(root, monkeypatch, tmp_path):
    """相對路徑拒刪：`discard` 只吃絕對路徑（見 `promote` docstring），不得依 CWD 解析去刪檔。"""
    victim = tmp_path / "cwd_victim.bin"
    victim.write_bytes(b"x")
    monkeypatch.chdir(tmp_path)
    storage.discard("cwd_victim.bin")
    assert victim.exists()


def test_discard_symlink_removes_link_not_target(root, tmp_path):
    """root 內之 symlink 指向 root 外 → 只刪連結本身，不碰其指向的檔。"""
    outside = _outside_file(tmp_path)
    link = os.path.join(root, "link.mp4")
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("此平台不允許建立 symlink")
    storage.discard(link)
    assert os.path.isfile(outside)
    assert not os.path.lexists(link)


@pytest.mark.parametrize("bad", [None, "", 123, "nul-in-dir\x00/a.mp4", "a\x00.mp4"])
def test_discard_invalid_input_does_not_raise(root, bad):
    """無效輸入（含內嵌 NUL）不拋錯——`discard` 位於清理路徑，失敗不該蓋掉原本的錯誤。"""
    storage.discard(os.path.join(root, bad) if isinstance(bad, str) and "\x00" in bad else bad)
