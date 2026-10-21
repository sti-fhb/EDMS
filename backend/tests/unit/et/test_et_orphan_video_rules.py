"""孤兒影片檔的判定與列舉（#775）。

孤兒＝磁碟上有檔、**沒有任何資料列指向它**（活表含已軟刪、暫存區含已軟刪）。
判定是純函式；列舉走真的檔案系統但限定在 `tmp_path`——⛔ 不可指向真正的
`ET_VIDEO_STORAGE_ROOT`，本機的測試與開發共用那個目錄。
"""

import os

import pytest

from app.et.material import storage
from app.et.material.rules import ORPHAN_GRACE_SECONDS, select_orphans

pytestmark = pytest.mark.unit

NOW = 1_800_000_000.0
OLD = NOW - ORPHAN_GRACE_SECONDS - 1
FRESH = NOW - ORPHAN_GRACE_SECONDS + 60


class TestSelectOrphans:
    def test_沒有被指向且超過寬限期_是孤兒(self) -> None:
        assert select_orphans([("12/a.mp4", OLD)], referenced=set(), now=NOW) == ["12/a.mp4"]

    def test_被指向的檔_不論多舊都不是孤兒(self) -> None:
        """正向錨點：少了它，「一律刪舊檔」也會讓上一條通過。"""
        assert select_orphans([("12/a.mp4", OLD)], referenced={"12/a.mp4"}, now=NOW) == []

    def test_寬限期內的檔_不刪(self) -> None:
        """上傳流程是先落檔、後寫列，而那一列要等請求結束才 commit——寬限期擋的是這段空窗。"""
        assert select_orphans([("12/a.mp4", FRESH)], referenced=set(), now=NOW) == []

    def test_暫存子目錄的殘檔同樣適用(self) -> None:
        """`.tmp/` 是上傳中途當機留下的，從來不會被任何列指向。"""
        tmp = f"{storage.TMP_DIRNAME}/x.part"
        assert select_orphans([(tmp, OLD), (f"{storage.TMP_DIRNAME}/y.part", FRESH)], referenced=set(), now=NOW) == [
            tmp
        ]

    def test_路徑比對不受分隔符影響(self) -> None:
        """DB 存 `/` 分隔（#233）；Windows 列舉若帶 `\\` 而未正規化，所有檔都會被當成孤兒。"""
        assert select_orphans([("12\\a.mp4", OLD)], referenced={"12/a.mp4"}, now=NOW) == []


class TestListStoredFiles:
    def test_列出所有檔的相對路徑與修改時間_含暫存子目錄(self, tmp_path) -> None:
        (tmp_path / "12").mkdir()
        (tmp_path / "12" / "a.mp4").write_bytes(b"x")
        (tmp_path / storage.TMP_DIRNAME).mkdir()
        (tmp_path / storage.TMP_DIRNAME / "b.part").write_bytes(b"x")
        os.utime(tmp_path / "12" / "a.mp4", (OLD, OLD))

        files = dict(storage.list_stored_files(str(tmp_path)))

        assert set(files) == {"12/a.mp4", f"{storage.TMP_DIRNAME}/b.part"}
        assert files["12/a.mp4"] == pytest.approx(OLD)

    def test_根目錄不存在時回空清單而非拋錯(self, tmp_path) -> None:
        assert storage.list_stored_files(str(tmp_path / "missing")) == []
