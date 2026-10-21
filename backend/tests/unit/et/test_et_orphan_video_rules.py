"""孤兒影片檔的判定、列舉與清理編排（#775）。

孤兒＝磁碟上有檔、**沒有任何資料列指向它**（活表含已軟刪、暫存區含已軟刪）。
判定是純函式；列舉與刪除走真的檔案系統但限定在 `tmp_path`——⛔ 不可指向真正的
`ET_VIDEO_STORAGE_ROOT`，本機的測試與開發共用那個目錄。

清理編排（`EtOrphanVideoSweeper`）注入假的引用來源，驗「看不懂就不刪」的各道中止條件。
"""

import os
import uuid

import pytest

from app.et.material import storage
from app.et.material.orphan_sweep import EtOrphanVideoSweeper
from app.et.material.rules import (
    MAX_ORPHAN_DELETES_PER_RUN,
    ORPHAN_GRACE_SECONDS,
    is_managed_video_path,
    select_orphans,
)

pytestmark = pytest.mark.unit

NOW = 1_800_000_000.0
OLD = NOW - ORPHAN_GRACE_SECONDS - 1
FRESH = NOW - ORPHAN_GRACE_SECONDS + 60


def _name(ext: str = "mp4") -> str:
    """系統產生的檔名格式：`{uuid hex}.{副檔名}`。"""
    return f"{uuid.uuid4().hex}.{ext}"


A = f"12/{_name()}"


class TestIsManagedVideoPath:
    @pytest.mark.parametrize("path", [A, f"{storage.TMP_DIRNAME}/{_name('webm')}"])
    def test_系統產生的檔名(self, path: str) -> None:
        assert is_managed_video_path(path)

    @pytest.mark.parametrize(
        "path",
        ["12/a.mp4", ".gitkeep", "lost+found/x", f"abc/{_name()}", f"12/sub/{_name()}", f"12/{_name()}.bak"],
    )
    def test_其他檔一律不是(self, path: str) -> None:
        """根目錄是 bind mount：手放的檔、`lost+found`、誤設 root 時的別人的檔，都不是本作業該碰的。"""
        assert not is_managed_video_path(path)


class TestSelectOrphans:
    def test_沒有被指向且超過寬限期_是孤兒(self) -> None:
        assert select_orphans([(A, OLD)], referenced=set(), now=NOW) == [A]

    def test_被指向的檔_不論多舊都不是孤兒(self) -> None:
        """正向錨點：少了它，「一律刪舊檔」也會讓上一條通過。"""
        assert select_orphans([(A, OLD)], referenced={A}, now=NOW) == []

    def test_寬限期內的檔_不刪(self) -> None:
        """上傳流程是先落檔、後寫列，而那一列要等請求結束才 commit——寬限期擋的是這段空窗。"""
        assert select_orphans([(A, FRESH)], referenced=set(), now=NOW) == []

    def test_非系統產生的檔名_不論多舊都不刪(self) -> None:
        assert select_orphans([("12/manual.mp4", OLD), (".gitkeep", OLD)], referenced=set(), now=NOW) == []

    def test_暫存子目錄的殘檔同樣適用(self) -> None:
        """`.tmp/` 是上傳中途當機留下的，從來不會被任何列指向。"""
        old_tmp, fresh_tmp = f"{storage.TMP_DIRNAME}/{_name()}", f"{storage.TMP_DIRNAME}/{_name()}"
        assert select_orphans([(old_tmp, OLD), (fresh_tmp, FRESH)], referenced=set(), now=NOW) == [old_tmp]

    def test_路徑比對經由_key_正規化(self) -> None:
        """白名單與列舉兩邊各自正規化；只比字串的話，反斜線或大小寫不同就會被當成孤兒。"""
        listed = A.replace("/", "\\")
        assert select_orphans([(listed, OLD)], referenced={A.upper()}, now=NOW, key=str.upper) == []

    def test_一次至多刪上限支數_且最舊的先刪(self) -> None:
        files = [(f"12/{_name()}", OLD - i) for i in range(MAX_ORPHAN_DELETES_PER_RUN + 5)]
        picked = select_orphans(files, referenced=set(), now=NOW)
        assert len(picked) == MAX_ORPHAN_DELETES_PER_RUN
        oldest = sorted(files, key=lambda f: f[1])[:MAX_ORPHAN_DELETES_PER_RUN]
        assert picked == [p for p, _ in oldest]


class TestStorageHelpers:
    def test_列出所有一般檔的相對路徑與修改時間_含暫存子目錄(self, tmp_path) -> None:
        (tmp_path / "12").mkdir()
        (tmp_path / A).write_bytes(b"x")
        (tmp_path / storage.TMP_DIRNAME).mkdir()
        tmp_rel = f"{storage.TMP_DIRNAME}/{_name()}"
        (tmp_path / tmp_rel).write_bytes(b"x")
        os.utime(tmp_path / A, (OLD, OLD))

        files = dict(storage.list_stored_files(str(tmp_path)))

        assert set(files) == {A, tmp_rel}
        assert files[A] == pytest.approx(OLD)

    def test_根目錄不存在時回空清單而非拋錯(self, tmp_path) -> None:
        assert storage.list_stored_files(str(tmp_path / "missing")) == []

    def test_絕對路徑的歷史資料與相對片段解析成同一個_key(self, tmp_path) -> None:
        """migration 676114dc0672 轉不出來的列保留絕對路徑，而讀取端仍接受它（#775 code review HIGH 3）。"""
        root = str(tmp_path)
        assert storage.path_key(root, os.path.join(root, "12", A.split("/")[1])) == storage.path_key(root, A)

    def test_刪除不出根目錄(self, tmp_path) -> None:
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"x")
        (tmp_path / "root").mkdir()
        assert storage.remove_stored_file(str(tmp_path / "root"), "../outside.mp4") is False
        assert outside.exists()

    def test_連結不列出也不刪_其指向的被引用檔保留(self, tmp_path) -> None:
        """security review L1：一個指向被引用檔的連結若被當成孤兒，解析它就會刪掉被引用的那支。"""
        (tmp_path / "12").mkdir()
        target = tmp_path / A
        target.write_bytes(b"x")
        link = tmp_path / "12" / _name()
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            pytest.skip("此環境無法建立 symlink（Windows 需開發者模式或系統管理員）")

        listed = {p for p, _ in storage.list_stored_files(str(tmp_path))}
        removed = storage.remove_stored_file(str(tmp_path), os.path.relpath(link, tmp_path))

        assert listed == {A}
        assert removed is False
        assert target.exists()


class _FakeMaterials:
    def __init__(self, paths: set[str], unreadable: int = 0) -> None:
        self._result = (paths, unreadable)

    async def referenced_video_paths(self, _db):
        return self._result


def _place(root, rel: str, mtime: float) -> None:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x")
    os.utime(path, (mtime, mtime))


class TestSweeperGuards:
    """「看不懂就不刪」：每一道中止條件都要讓孤兒**留著**，並回報原因。"""

    async def _run(self, tmp_path, materials, *, dm_root=None):
        root = str(tmp_path / "et")
        _place(root, A, OLD)
        result = await EtOrphanVideoSweeper(materials).run(
            None, root=root, now=NOW, dm_root=dm_root or str(tmp_path / "dm")
        )
        return result, os.path.exists(os.path.join(root, A))

    async def test_正常情況刪掉孤兒(self, tmp_path) -> None:
        """正向錨點：下面各條「沒刪」才代表是被中止條件擋下的。"""
        result, still_there = await self._run(tmp_path, _FakeMaterials({f"12/{_name()}"}))
        assert (result.deleted, result.aborted, still_there) == (1, None, False)

    async def test_有暫存列讀不出路徑時中止(self, tmp_path) -> None:
        result, still_there = await self._run(tmp_path, _FakeMaterials({f"12/{_name()}"}, unreadable=1))
        assert result.aborted and still_there

    async def test_白名單為空但目錄有影片檔時中止(self, tmp_path) -> None:
        result, still_there = await self._run(tmp_path, _FakeMaterials(set()))
        assert result.aborted and still_there

    async def test_ET_與_DM_根目錄互相包含時中止(self, tmp_path) -> None:
        result, still_there = await self._run(
            tmp_path, _FakeMaterials({f"12/{_name()}"}), dm_root=str(tmp_path / "et" / "dm")
        )
        assert result.aborted and still_there

    async def test_根目錄為空字串時拒絕執行(self) -> None:
        with pytest.raises(ValueError):
            await EtOrphanVideoSweeper(_FakeMaterials(set())).run(None, root="")
