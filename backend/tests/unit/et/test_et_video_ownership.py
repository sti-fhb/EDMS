"""ET 影片檔案歸屬圍籬（#871）：目錄命名、`expect_prefix`、發布時掛回正式目錄。

#240 A1 已為 DM 加上「檔案須落在 `{root}/{doc_id}/` 之下」；ET 原本做不到，因為暫存模式新增的
教材，影片目錄名是 `abs(暫存 id)`，與正式 `MATERIAL_ID` 共用同一個數字命名空間。本檔釘住三件事：

| # | 行為 |
|---|------|
| 1 | 暫存新增的教材改落 `s{stage_id}/`，不再與正式教材的數字目錄相撞 |
| 2 | 播放端以 `expect_prefix=MATERIAL_ID` 驗歸屬；遷移完成（標記檔存在）前只記 log、照常放行 |
| 3 | `link_into_material` 把影片掛進 `{MATERIAL_ID}/`，原路徑保留（交易回滾時仍有效） |
"""

import errno
import logging
import os

import pytest

from app.core.config import settings
from app.core.exceptions import AppError
from app.et.material import storage
from app.et.material.rules import is_managed_video_path

_NF = AppError(status_code=404, detail="查無此課程內容", error_code="ET_LEARN_001")
_NAME = "0123456789abcdef0123456789abcdef.mp4"


@pytest.fixture
def root(tmp_path, monkeypatch) -> str:
    monkeypatch.setattr(settings, "ET_VIDEO_STORAGE_ROOT", str(tmp_path))
    return os.path.realpath(str(tmp_path))


def _put(root: str, rel: str, content: bytes = b"video") -> str:
    full = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(content)
    return full


def _enforce(root: str) -> None:
    storage.mark_ownership_fence_enforced(root)


class TestDirName:
    def test_正式教材用數字目錄(self) -> None:
        assert storage.video_dir_name(7) == "7"

    def test_暫存新增的教材用_s_前綴(self) -> None:
        """負數 id ＝ 暫存節點（`-STAGE_ID`）；不加前綴就會與正式教材 7 落在同一個 `7/`。"""
        assert storage.video_dir_name(-7) == "s7"

    def test_promote_接受暫存目錄名(self, root) -> None:
        tmp = _put(root, f"{storage.TMP_DIRNAME}/{_NAME}")
        _, rel = storage.promote(tmp, video_id_hint="s7", ext="mp4")
        assert rel.startswith("s7/")

    @pytest.mark.parametrize("hint", ["s", "s07", "S7", "s-7", "ss7", "s7/..", "7s"])
    def test_promote_拒收不正規的暫存目錄名(self, root, hint: str) -> None:
        tmp = _put(root, f"{storage.TMP_DIRNAME}/{_NAME}")
        with pytest.raises(AppError) as exc:
            storage.promote(tmp, video_id_hint=hint, ext="mp4")
        assert exc.value.error_code == "ET_MATERIAL_007"


class TestExpectPrefix:
    def test_落在本教材目錄者放行(self, root) -> None:
        _put(root, f"12/{_NAME}")
        _enforce(root)
        resolved = storage.resolve_within_root(f"12/{_NAME}", not_found=_NF, expect_prefix="12")
        assert resolved == os.path.join(root, "12", _NAME)

    def test_落在他份教材目錄者回_404(self, root) -> None:
        _put(root, f"13/{_NAME}")
        _enforce(root)
        with pytest.raises(AppError) as exc:
            storage.resolve_within_root(f"13/{_NAME}", not_found=_NF, expect_prefix="12")
        assert exc.value is _NF

    def test_落在暫存目錄者回_404(self, root) -> None:
        """`s12/` 不是 `12/`——發布後仍指向暫存目錄的列不得放行。"""
        _put(root, f"s12/{_NAME}")
        _enforce(root)
        with pytest.raises(AppError):
            storage.resolve_within_root(f"s12/{_NAME}", not_found=_NF, expect_prefix="12")

    def test_以_dot_dot_繞進本教材目錄外者回_404(self, root) -> None:
        """比對解析後的路徑，不是原始字串：`12/../13/x` 字面上以 `12/` 開頭。"""
        _put(root, f"13/{_NAME}")
        _enforce(root)
        with pytest.raises(AppError):
            storage.resolve_within_root(f"12/../13/{_NAME}", not_found=_NF, expect_prefix="12")

    def test_目錄本身不算落在目錄之下(self, root) -> None:
        os.makedirs(os.path.join(root, "12"))
        _enforce(root)
        with pytest.raises(AppError):
            storage.resolve_within_root("12", not_found=_NF, expect_prefix="12")

    def test_root_圍籬仍先跑(self, root) -> None:
        """`expect_prefix` 是額外一層，不取代 root 圍籬。"""
        _enforce(root)
        with pytest.raises(AppError):
            storage.resolve_within_root("../12/x.mp4", not_found=_NF, expect_prefix="12")

    def test_攔截時不記路徑(self, root, caplog) -> None:
        _put(root, f"13/{_NAME}")
        _enforce(root)
        with caplog.at_level(logging.WARNING), pytest.raises(AppError):
            storage.resolve_within_root(f"13/{_NAME}", not_found=_NF, expect_prefix="12")
        assert caplog.records, "攔截須留安全事件"
        assert all(_NAME not in r.getMessage() and root not in r.getMessage() for r in caplog.records)

    def test_遷移完成前只記_log_照常放行(self, root, caplog) -> None:
        """合併即安全：維運跑完遷移腳本前，既有的「目錄 ≠ MATERIAL_ID」影片仍須可播放。"""
        _put(root, f"13/{_NAME}")
        with caplog.at_level(logging.WARNING):
            resolved = storage.resolve_within_root(f"13/{_NAME}", not_found=_NF, expect_prefix="12")
        assert resolved == os.path.join(root, "13", _NAME)
        assert any("遷移" in r.getMessage() for r in caplog.records)
        assert all(_NAME not in r.getMessage() for r in caplog.records)

    def test_未傳_expect_prefix_時行為不變(self, root) -> None:
        _put(root, f"13/{_NAME}")
        _enforce(root)
        assert storage.resolve_within_root(f"13/{_NAME}", not_found=_NF) == os.path.join(root, "13", _NAME)

    def test_標記檔是一般檔才算數(self, root) -> None:
        """目錄或連結不算——那不是遷移腳本寫出來的東西。"""
        os.makedirs(os.path.join(root, storage.OWNERSHIP_FENCE_MARKER))
        assert not storage.ownership_fence_enforced(root)


class TestLinkIntoMaterial:
    def test_掛進正式目錄且原路徑仍在(self, root) -> None:
        src = _put(root, f"s7/{_NAME}")

        rel = storage.link_into_material(f"s7/{_NAME}", 12)

        assert rel == f"12/{_NAME}"
        target = os.path.join(root, "12", _NAME)
        assert os.path.isfile(src), "原路徑要留著：發布交易回滾時，暫存列仍指向它"
        assert os.path.samefile(src, target)

    def test_已在正式目錄者原樣回傳(self, root) -> None:
        _put(root, f"12/{_NAME}")
        assert storage.link_into_material(f"12/{_NAME}", 12) == f"12/{_NAME}"
        assert os.listdir(root) == ["12"]

    def test_重跑時目標已是同一支檔則沿用(self, root) -> None:
        """遷移腳本中途失敗重跑：上一輪已掛好的連結不得被視為衝突。"""
        _put(root, f"5/{_NAME}")
        assert storage.link_into_material(f"5/{_NAME}", 12) == f"12/{_NAME}"
        assert storage.link_into_material(f"5/{_NAME}", 12) == f"12/{_NAME}"

    def test_目標已有另一支同名檔則拒絕(self, root) -> None:
        _put(root, f"5/{_NAME}", b"a")
        _put(root, f"12/{_NAME}", b"b")
        with pytest.raises(FileExistsError):
            storage.link_into_material(f"5/{_NAME}", 12)

    def test_來源不存在(self, root) -> None:
        with pytest.raises(FileNotFoundError):
            storage.link_into_material(f"s7/{_NAME}", 12)
        assert not os.path.exists(os.path.join(root, "12")), "來源不在就不該建目錄"

    def test_來源逃出_root_者拒絕(self, root, tmp_path_factory) -> None:
        outside = tmp_path_factory.mktemp("outside")
        (outside / _NAME).write_bytes(b"x")
        with pytest.raises(ValueError):
            storage.link_into_material(str(outside / _NAME), 12)

    def test_來源是連結者拒絕(self, root) -> None:
        """連結指向的可能是他份教材的被引用檔——掛過去等於把那支複製給這份教材。"""
        _put(root, f"5/{_NAME}")
        os.makedirs(os.path.join(root, "s7"))
        os.symlink(os.path.join(root, "5", _NAME), os.path.join(root, "s7", _NAME))
        with pytest.raises(ValueError):
            storage.link_into_material(f"s7/{_NAME}", 12)

    def test_刷新修改時間(self, root) -> None:
        """孤兒清理以 mtime 判寬限期；hard link 共用 inode，不刷新的話剛掛上、交易還沒
        commit 的那個名字可能被當成舊孤兒刪掉。"""
        src = _put(root, f"s7/{_NAME}")
        os.utime(src, (1, 1))
        storage.link_into_material(f"s7/{_NAME}", 12)
        assert os.path.getmtime(os.path.join(root, "12", _NAME)) > 1

    def test_檔案系統不支援_hard_link_時退回複製(self, root, monkeypatch) -> None:
        _put(root, f"s7/{_NAME}", b"payload")

        def no_link(*_a, **_k):
            raise OSError(errno.EXDEV, "cross-device link")

        monkeypatch.setattr(storage.os, "link", no_link)
        rel = storage.link_into_material(f"s7/{_NAME}", 12)

        with open(os.path.join(root, *rel.split("/")), "rb") as f:
            assert f.read() == b"payload"
        assert os.listdir(os.path.join(root, storage.TMP_DIRNAME)) == [], "複製的暫存檔不得殘留"

    def test_絕對路徑的歷史資料也搬得動(self, root) -> None:
        src = _put(root, f"5/{_NAME}")
        assert storage.link_into_material(src, 12) == f"12/{_NAME}"


class TestManagedPath:
    @pytest.mark.parametrize("rel", [f"12/{_NAME}", f"s12/{_NAME}", f".tmp/{_NAME}"])
    def test_系統產生的路徑(self, rel: str) -> None:
        assert is_managed_video_path(rel)

    @pytest.mark.parametrize("rel", [f"s/{_NAME}", f"x12/{_NAME}", storage.OWNERSHIP_FENCE_MARKER])
    def test_非系統產生的路徑(self, rel: str) -> None:
        assert not is_managed_video_path(rel)


class TestRelocationPlan:
    """遷移腳本的待遷移判定（`relocate_videos.plan`）——與播放端圍籬同一套規則。"""

    def test_挑出目錄不等於_MATERIAL_ID_者(self, root) -> None:
        from app.et.material.relocate_videos import VideoPathRow, plan

        _put(root, f"5/{_NAME}")
        _put(root, f"12/{_NAME}")
        result = plan([VideoPathRow(1, 12, f"5/{_NAME}"), VideoPathRow(2, 12, f"12/{_NAME}")], root)

        (item,) = result.relocations
        assert (item.video_id, item.old, item.new, item.source_missing) == (1, f"5/{_NAME}", f"12/{_NAME}", False)

    def test_絕對路徑的歷史資料以解析後位置判定(self, root) -> None:
        from app.et.material.relocate_videos import VideoPathRow, plan

        abs_ok = _put(root, f"12/{_NAME}")
        abs_bad = _put(root, f"5/{'f' * 32}.mp4")
        result = plan([VideoPathRow(1, 12, abs_ok), VideoPathRow(2, 12, abs_bad)], root)

        assert [r.video_id for r in result.relocations] == [2]
        assert result.relocations[0].new == f"12/{'f' * 32}.mp4"

    def test_檔案不存在者標記出來(self, root) -> None:
        from app.et.material.relocate_videos import VideoPathRow, plan

        (item,) = plan([VideoPathRow(1, 12, f"s7/{_NAME}")], root).relocations
        assert item.source_missing

    def test_逃出_root_者只計數(self, root) -> None:
        from app.et.material.relocate_videos import VideoPathRow, plan

        result = plan([VideoPathRow(1, 12, "../../etc/passwd")], root)
        assert result.relocations == [] and result.escaped == 1


def test_標記檔是連結時不算數(root, tmp_path_factory) -> None:
    real = tmp_path_factory.mktemp("elsewhere") / "marker"
    real.write_text("x")
    os.symlink(str(real), os.path.join(root, storage.OWNERSHIP_FENCE_MARKER))
    assert not storage.ownership_fence_enforced(root)


class TestSecurityHardening:
    """Security review（#871）：寫入端不得把錯指的檔合法化、檔案操作不跟隨連結。"""

    def test_來源不在允許的暫存目錄者拒絕(self, root) -> None:
        """一筆錯指到他份教材檔案的 FILE_PATH，不得在「更新」時被掛進本教材目錄而從此通過圍籬。"""
        _put(root, f"13/{_NAME}")
        with pytest.raises(ValueError):
            storage.link_into_material(f"13/{_NAME}", 12, allowed_source_dirs=frozenset({"s7", "7"}))
        assert not os.path.exists(os.path.join(root, "12"))

    def test_來源在允許的暫存目錄者照常掛(self, root) -> None:
        _put(root, f"s7/{_NAME}")
        rel = storage.link_into_material(f"s7/{_NAME}", 12, allowed_source_dirs=frozenset({"s7", "7"}))
        assert rel == f"12/{_NAME}"

    def test_目標目錄是連結者拒絕(self, root, tmp_path_factory) -> None:
        elsewhere = tmp_path_factory.mktemp("elsewhere")
        os.symlink(str(elsewhere), os.path.join(root, "12"))
        _put(root, f"s7/{_NAME}")
        with pytest.raises(ValueError):
            storage.link_into_material(f"s7/{_NAME}", 12)
        assert os.listdir(elsewhere) == [], "不得寫到 root 外"

    def test_promote_目標目錄是連結者拒絕(self, root, tmp_path_factory) -> None:
        elsewhere = tmp_path_factory.mktemp("elsewhere")
        os.symlink(str(elsewhere), os.path.join(root, "12"))
        tmp = _put(root, f"{storage.TMP_DIRNAME}/{_NAME}")
        with pytest.raises(AppError):
            storage.promote(tmp, video_id_hint="12", ext="mp4")
        assert os.listdir(elsewhere) == []

    def test_標記檔位置預先放了連結時不寫穿(self, root, tmp_path_factory) -> None:
        victim = tmp_path_factory.mktemp("elsewhere") / "victim"
        victim.write_text("original")
        os.symlink(str(victim), os.path.join(root, storage.OWNERSHIP_FENCE_MARKER))
        with pytest.raises(OSError):
            storage.mark_ownership_fence_enforced(root)
        assert victim.read_text() == "original"
        assert not storage.ownership_fence_enforced(root)

    def test_link_back_從新路徑掛回舊路徑(self, root) -> None:
        new = _put(root, f"12/{_NAME}")
        storage.link_back(f"12/{_NAME}", f"7/{_NAME}")
        assert os.path.samefile(new, os.path.join(root, "7", _NAME))

    @pytest.mark.parametrize("old", ["../outside.mp4", "/etc/x.mp4"])
    def test_link_back_舊路徑逃出_root_者拒絕(self, root, old: str) -> None:
        _put(root, f"12/{_NAME}")
        with pytest.raises(ValueError):
            storage.link_back(f"12/{_NAME}", old)

    def test_link_back_新路徑是連結者拒絕(self, root, tmp_path_factory) -> None:
        outside = tmp_path_factory.mktemp("elsewhere") / "secret.mp4"
        outside.write_bytes(b"x")
        os.makedirs(os.path.join(root, "12"))
        os.symlink(str(outside), os.path.join(root, "12", _NAME))
        with pytest.raises(ValueError):
            storage.link_back(f"12/{_NAME}", f"7/{_NAME}")
        assert not os.path.exists(os.path.join(root, "7", _NAME))

    def test_放行模式的_warning_同一支只記一次(self, root, caplog) -> None:
        """播放器的 Range 請求會對同一支影片打很多次。"""
        _put(root, f"13/{_NAME}")
        storage._WARNED_UNMIGRATED.clear()
        with caplog.at_level(logging.WARNING):
            for _ in range(5):
                storage.resolve_within_root(f"13/{_NAME}", not_found=_NF, expect_prefix="12")
        assert sum("遷移" in r.getMessage() for r in caplog.records) == 1
