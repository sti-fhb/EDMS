"""孤兒影片檔清理（#775）：SCHET002 第 5 批。

孤兒＝磁碟上有檔、**沒有任何資料列指向它**。已發布課程的影片上傳後先進暫存區，暫存被
丟掉（沒按更新就離開、按「取消」、上傳後又在暫存區刪掉再更新）時，檔案就沒有任何列指向。

🔴 **儲存根目錄一律改指 `tmp_path`。** 本機的測試與開發共用 `ET_VIDEO_STORAGE_ROOT`，而
測試 DB 看不到開發 DB 的列——對真的目錄跑清理，會把開發環境的影片全部當成孤兒刪掉。

⚠️ 本檔的上傳走真的 `ffprobe`（比照 `test_et_video.py`），需執行環境有 ffmpeg。
"""

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.utils import utcnow
from app.et.material.models import EtMaterialVideo
from app.et.material.orphan_sweep import EtOrphanVideoSweeper
from app.et.material.rules import ORPHAN_GRACE_SECONDS
from tests.integration.et.test_et_staged_write_paths import _bearer, _course_with_content, _publish, _user

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "sample_3s.mp4"
_COURSES = "/api/et/courses"


@pytest.fixture
def root(tmp_path, monkeypatch) -> str:
    monkeypatch.setattr(settings, "ET_VIDEO_STORAGE_ROOT", str(tmp_path))
    return str(tmp_path)


def _age(root: str, rel: str) -> None:
    """把檔案的修改時間推到寬限期之前——模擬「放了一天以上」。"""
    old = os.path.getmtime(os.path.join(root, rel)) - ORPHAN_GRACE_SECONDS - 60
    os.utime(os.path.join(root, rel), (old, old))


async def _upload(client, uid: str, material_id: int, name: str) -> dict:
    r = await client.post(
        f"/api/et/materials/{material_id}/videos",
        files={"file": (name, _FIXTURE.read_bytes(), "video/mp4")},
        headers=_bearer(uid),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _another_referenced_video(db, material_id: int) -> None:
    """白名單裡要有別的影片——空白名單會觸發斷路器（`orphan_sweep` 的中止條件），清理整輪不跑。

    正式環境不會是空的；測試 DB 在同一個 worker 裡可能剛好沒有其他影片列。
    """
    db.add(
        EtMaterialVideo(
            material_id=material_id,
            file_path=f"{material_id}/{uuid.uuid4().hex}.mp4",
            file_name="kept.mp4",
            duration_sec=3,
            file_size_bytes=1,
            sort_order=99,
            created_user="ZT_OV",
            created_date=utcnow(),
            deleted=1,
        )
    )
    await db.commit()


def _files(root: str) -> set[str]:
    return {os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/") for d, _, fs in os.walk(root) for f in fs}


class TestOrphanPaths:
    """驗收條件 1：會產生孤兒的路徑逐一實測。"""

    async def test_已發布課程上傳後未更新即丟棄暫存_檔案成為孤兒並被清掉(self, client, db, root) -> None:
        uid = await _user(db, "ZT_OV1")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await db.commit()
        before = _files(root)

        await _upload(client, uid, ids["material_id"], "lesson.mp4")
        new_files = _files(root) - before
        assert len(new_files) == 1, "前置：上傳應落地一支檔"
        (orphan,) = new_files
        # 路徑 A：沒按更新就離開，下次進編輯頁丟掉未保留的暫存
        r = await client.delete(f"{_COURSES}/{ids['course_id']}/content/stage/unkept", headers=_bearer(uid))
        assert r.status_code == 204, r.text
        await db.commit()
        assert orphan in _files(root), "丟棄暫存不刪檔——檔案此刻沒有任何列指向，即為孤兒"

        await _another_referenced_video(db, ids["material_id"])

        _age(root, orphan)
        result = await EtOrphanVideoSweeper().run(db, root=root)

        assert result.aborted is None
        assert orphan not in _files(root)
        assert result.deleted == 1

    async def _staged_upload(self, client, db, uid: str, root: str) -> tuple[dict, str]:
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await db.commit()
        before = _files(root)
        video = await _upload(client, uid, ids["material_id"], "lesson.mp4")
        (uploaded,) = _files(root) - before
        return ids | {"video": video}, uploaded

    async def _assert_orphan_then_swept(self, db, root: str, uploaded: str, material_id: int) -> None:
        assert uploaded in _files(root), "前置：丟棄暫存不刪檔"
        await _another_referenced_video(db, material_id)
        _age(root, uploaded)
        result = await EtOrphanVideoSweeper().run(db, root=root)
        assert result.aborted is None
        assert uploaded not in _files(root)

    async def test_路徑B_按取消放棄整輪編輯(self, client, db, root) -> None:
        uid = await _user(db, "ZT_OV5")
        ids, uploaded = await self._staged_upload(client, db, uid, root)

        r = await client.delete(f"{_COURSES}/{ids['course_id']}/content/stage", headers=_bearer(uid))
        assert r.status_code == 204, r.text
        await db.commit()

        await self._assert_orphan_then_swept(db, root, uploaded, ids["material_id"])

    async def test_路徑C_暫存區刪掉剛上傳的影片後按更新(self, client, db, root) -> None:
        """它從沒進過活表；暫存列隨套用清掉後，就沒有任何列指向那支檔。"""
        uid = await _user(db, "ZT_OV6")
        ids, uploaded = await self._staged_upload(client, db, uid, root)
        mid = ids["material_id"]
        detail = (await client.get(f"/api/et/materials/{mid}", headers=_bearer(uid))).json()
        keep = [v["video_id"] for v in detail["videos"] if v["video_id"] != ids["video"]["video_id"]]
        r = await client.put(
            f"/api/et/materials/{mid}",
            json={
                "material_name": detail["material_name"],
                # 刪掉這支後教材要仍有媒材（ET_MATERIAL_002），補一段說明文字
                "description_html": detail["description_html"] or "<p>說明</p>",
                "doc_ids": [d["doc_id"] for d in detail["docs"]],
                "video_ids": keep,
                "version": detail["version"],
            },
            headers=_bearer(uid),
        )
        assert r.status_code == 204, r.text
        r = await client.post(f"{_COURSES}/{ids['course_id']}/content/apply", headers=_bearer(uid))
        assert r.status_code == 200, r.text
        await db.commit()

        await self._assert_orphan_then_swept(db, root, uploaded, ids["material_id"])

    async def test_更新後成為活表的影片不被清掉(self, client, db, root) -> None:
        """正向錨點：同一條上傳路徑，按了「更新」就有活表列指向，清理不得碰它。"""
        uid = await _user(db, "ZT_OV2")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await db.commit()
        before = _files(root)
        await _upload(client, uid, ids["material_id"], "lesson.mp4")
        (uploaded,) = _files(root) - before
        r = await client.post(f"{_COURSES}/{ids['course_id']}/content/apply", headers=_bearer(uid))
        assert r.status_code == 200, r.text
        await db.commit()
        assert await db.scalar(select(EtMaterialVideo).where(EtMaterialVideo.file_path == uploaded)) is not None

        _age(root, uploaded)
        await EtOrphanVideoSweeper().run(db, root=root)

        assert uploaded in _files(root)


class TestSweepKeepsReferenced:
    """驗收條件 3：仍被引用的檔不得誤刪——活表（含已軟刪）與暫存區（含已軟刪）都算引用。"""

    async def test_活表已軟刪的影片檔保留(self, client, db, root) -> None:
        """軟刪除的語意是可回復（`test_et_video.py::test_刪除後保留磁碟檔案`），清理不可推翻它。"""
        uid = await _user(db, "ZT_OV3")
        ids = await _course_with_content(client, db, uid)  # 草稿課程：上傳直寫活表
        before = _files(root)
        video = await _upload(client, uid, ids["material_id"], "lesson.mp4")
        (uploaded,) = _files(root) - before
        row = await db.scalar(select(EtMaterialVideo).where(EtMaterialVideo.video_id == video["video_id"]))
        row.deleted = 1
        await db.commit()

        _age(root, uploaded)
        await EtOrphanVideoSweeper().run(db, root=root)

        assert uploaded in _files(root)

    async def test_仍在暫存區的影片檔保留(self, client, db, root) -> None:
        """編輯中、還沒按更新的影片只有暫存列指向——那不是孤兒，教師下一步可能就按更新。"""
        uid = await _user(db, "ZT_OV4")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await db.commit()
        before = _files(root)
        await _upload(client, uid, ids["material_id"], "lesson.mp4")
        (uploaded,) = _files(root) - before
        await db.commit()

        _age(root, uploaded)
        await EtOrphanVideoSweeper().run(db, root=root)

        assert uploaded in _files(root)

    async def test_DB_存絕對路徑的歷史資料_指向的檔保留(self, client, db, root) -> None:
        """migration 676114dc0672 轉不出來的列保留絕對路徑，讀取端仍接受落在根目錄內的絕對路徑
        （code review HIGH 3）。只比字串的話，這支仍在使用中的影片會被當成孤兒刪掉。"""
        uid = await _user(db, "ZT_OV7")
        ids = await _course_with_content(client, db, uid)  # 草稿：上傳直寫活表
        before = _files(root)
        video = await _upload(client, uid, ids["material_id"], "lesson.mp4")
        (uploaded,) = _files(root) - before
        row = await db.scalar(select(EtMaterialVideo).where(EtMaterialVideo.video_id == video["video_id"]))
        row.file_path = os.path.join(root, *uploaded.split("/"))  # 模擬歷史資料：絕對路徑
        await db.commit()

        _age(root, uploaded)
        result = await EtOrphanVideoSweeper().run(db, root=root)

        assert result.aborted is None
        assert uploaded in _files(root)

    async def test_寬限期內的無主檔不刪(self, db, root) -> None:
        """上傳是先落檔、後寫列；掃描當下剛落地、列還沒 commit 的檔不可刪。"""
        # 系統產生的檔名格式，否則它會因「不是本作業管的檔」而留下，驗不到寬限期
        fresh = f"99/{uuid.uuid4().hex}.mp4"
        os.makedirs(os.path.join(root, "99"))
        Path(root, fresh).write_bytes(b"x")

        await EtOrphanVideoSweeper().run(db, root=root)

        assert fresh in _files(root)
