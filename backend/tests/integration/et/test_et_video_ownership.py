"""ET 影片檔案歸屬圍籬（#871）：暫存上傳 → 按「更新」掛回正式目錄 → 播放端驗歸屬。

🔴 **儲存根目錄一律改指 `tmp_path`**（同 `test_et_orphan_video_sweep.py`）：本機的測試與開發共用
`ET_VIDEO_STORAGE_ROOT`，而本檔會寫歸屬圍籬的標記檔、跑孤兒清理——對真的目錄做，會改變開發
環境的播放行為、刪掉開發環境的影片。

`ffprobe` 在本檔 mock 掉：要驗的是落盤目錄與歸屬，不是長度探測（那條由 `test_et_video.py`
以真的 ffprobe 守著）。
"""

import json
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.et.course.models import EtCourseContentStage, EtItem
from app.et.course.stage_rules import ENTITY_MATERIAL_VIDEO
from app.et.material import storage
from app.et.material.models import EtMaterialVideo
from app.et.material.orphan_sweep import EtOrphanVideoSweeper
from app.et.material.rules import ORPHAN_GRACE_SECONDS
from tests.integration.et.test_et_staged_write_paths import (
    ITEM_MATERIAL,
    _bearer,
    _course_with_content,
    _publish,
    _user,
)

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "sample_3s.mp4"
_COURSES = "/api/et/courses"


@pytest.fixture
def root(tmp_path, monkeypatch) -> str:
    monkeypatch.setattr(settings, "ET_VIDEO_STORAGE_ROOT", str(tmp_path))
    return os.path.realpath(str(tmp_path))


@pytest.fixture(autouse=True)
def _no_ffprobe(monkeypatch) -> None:
    async def fake_probe(_path: str) -> int:
        return 3

    monkeypatch.setattr("app.et.material.service.probe_duration_sec", fake_probe)


def _files(root: str) -> set[str]:
    return {os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/") for d, _, fs in os.walk(root) for f in fs}


async def _upload(client, uid: str, material_id: int, name: str = "lesson.mp4") -> dict:
    r = await client.post(
        f"/api/et/materials/{material_id}/videos",
        files={"file": (name, _FIXTURE.read_bytes(), "video/mp4")},
        headers=_bearer(uid),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _apply(client, db, uid: str, course_id: int) -> None:
    r = await client.post(f"{_COURSES}/{course_id}/content/apply", headers=_bearer(uid))
    assert r.status_code == 200, r.text
    await db.commit()


async def _play(client, uid: str, video_id: int):
    ticket = await client.post(f"/api/et/videos/{video_id}/ticket", headers=_bearer(uid))
    assert ticket.status_code == 200, ticket.text
    return await client.get(f"/api/et/videos/{video_id}/file", params={"t": ticket.json()["ticket"]})


async def _staged_new_material(client, db, uid: str) -> dict:
    """已發布課程裡、暫存模式新增一份教材（對外 id 為負數），回傳各層 id。"""
    ids = await _course_with_content(client, db, uid)
    await _publish(client, db, uid, ids["course_id"])
    await db.commit()
    item = await client.post(
        f"/api/et/chapters/{ids['chapter_id']}/items",
        json={"item_type": ITEM_MATERIAL, "title": "暫存新教材"},
        headers=_bearer(uid),
    )
    assert item.status_code == 201, item.text
    staged_mid = item.json()["material_id"]
    assert staged_mid < 0, "前置：暫存模式新增的教材對外為負數 id"
    return ids | {"staged_material_id": staged_mid}


async def _live_video_of_new_material(db, ids: dict) -> EtMaterialVideo:
    """更新後「暫存新教材」的那支活表影片（該章節中、`教材甲` 以外唯一一份教材）。"""
    material_ids = set(
        await db.scalars(
            select(EtItem.material_id).where(
                EtItem.chapter_id == ids["chapter_id"],
                EtItem.material_id.is_not(None),
                EtItem.material_id != ids["material_id"],
                EtItem.deleted == 0,
            )
        )
    )
    assert len(material_ids) == 1, "前置：更新後暫存新教材應進活表"
    video = await db.scalar(select(EtMaterialVideo).where(EtMaterialVideo.material_id == material_ids.pop()))
    assert video is not None
    return video


class TestDirectoryNaming:
    """驗收條件 1：目錄名唯一對應正式 `MATERIAL_ID`（暫存上傳、既有教材上傳、發布後）。"""

    async def test_暫存新增教材上傳落在暫存命名空間(self, client, db, root) -> None:
        uid = await _user(db, "ZT_VO1")
        ids = await _staged_new_material(client, db, uid)

        before = _files(root)
        await _upload(client, uid, ids["staged_material_id"])
        (uploaded,) = _files(root) - before

        assert uploaded.split("/")[0] == f"s{-ids['staged_material_id']}"

    async def test_既有教材上傳落在_MATERIAL_ID_目錄(self, client, db, root) -> None:
        uid = await _user(db, "ZT_VO2")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await db.commit()

        before = _files(root)
        await _upload(client, uid, ids["material_id"])
        (uploaded,) = _files(root) - before

        assert uploaded.split("/")[0] == str(ids["material_id"])

    async def test_更新後掛回正式目錄且可播放(self, client, db, root) -> None:
        uid = await _user(db, "ZT_VO3")
        ids = await _staged_new_material(client, db, uid)
        before = _files(root)
        await _upload(client, uid, ids["staged_material_id"])
        (staged_path,) = _files(root) - before

        await _apply(client, db, uid, ids["course_id"])

        video = await _live_video_of_new_material(db, ids)
        assert video.file_path.split("/")[0] == str(video.material_id)
        assert os.path.samefile(os.path.join(root, video.file_path), os.path.join(root, staged_path))

        storage.mark_ownership_fence_enforced(root)
        r = await _play(client, uid, video.video_id)
        assert r.status_code == 200, r.text
        assert r.content == _FIXTURE.read_bytes()


class TestPlaybackFence:
    """驗收條件 3：影片檔落在他份教材目錄 → 404 且不外洩路徑。"""

    async def _video_in_other_dir(self, client, db, uid: str, root: str) -> tuple[int, str]:
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        foreign = f"{ids['material_id'] + 1_000_000}/{uuid.uuid4().hex}.mp4"
        os.makedirs(os.path.join(root, foreign.split("/")[0]))
        with open(os.path.join(root, foreign), "wb") as f:
            f.write(_FIXTURE.read_bytes())
        video = EtMaterialVideo(
            material_id=ids["material_id"],
            file_path=foreign,
            file_name="誤植.mp4",
            duration_sec=3,
            file_size_bytes=1,
            sort_order=9,
            created_user=uid,
            created_date=utcnow(),
            deleted=0,
        )
        db.add(video)
        await db.commit()
        return video.video_id, foreign

    async def test_圍籬生效後回_404_且不外洩路徑(self, client, db, root) -> None:
        uid = await _user(db, "ZT_VO4")
        video_id, foreign = await self._video_in_other_dir(client, db, uid, root)
        storage.mark_ownership_fence_enforced(root)

        r = await _play(client, uid, video_id)

        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_LEARN_001"
        assert foreign not in r.text and foreign.split("/")[1] not in r.text and root not in r.text

    async def test_遷移完成前既有影片仍可播放(self, client, db, root) -> None:
        """合併即安全：沒有標記檔時只記 log，不擋。"""
        uid = await _user(db, "ZT_VO5")
        video_id, _ = await self._video_in_other_dir(client, db, uid, root)

        r = await _play(client, uid, video_id)

        assert r.status_code == 200, r.text


class TestOrphanSweepAfterApply:
    """驗收條件 4：孤兒清理不因命名調整而誤刪被引用檔。"""

    async def test_只清掉暫存目錄的舊名字_正式目錄的檔保留(self, client, db, root) -> None:
        uid = await _user(db, "ZT_VO6")
        ids = await _staged_new_material(client, db, uid)
        before = _files(root)
        await _upload(client, uid, ids["staged_material_id"])
        (staged_path,) = _files(root) - before
        await _apply(client, db, uid, ids["course_id"])
        video = await _live_video_of_new_material(db, ids)

        old = os.path.getmtime(os.path.join(root, staged_path)) - ORPHAN_GRACE_SECONDS - 60
        os.utime(os.path.join(root, staged_path), (old, old))  # 同一個 inode，兩個名字一起變舊
        result = await EtOrphanVideoSweeper().run(db, root=root)

        assert result.aborted is None
        assert staged_path not in _files(root), "暫存目錄的舊名字已無列指向，應被清掉"
        assert video.file_path in _files(root), "被引用的正式目錄檔不得被刪"
        with open(os.path.join(root, video.file_path), "rb") as f:
            assert f.read() == _FIXTURE.read_bytes(), "刪的只是一個名字，內容仍在"

    async def test_更新前暫存目錄的檔受暫存列保護(self, client, db, root) -> None:
        uid = await _user(db, "ZT_VO7")
        ids = await _staged_new_material(client, db, uid)
        before = _files(root)
        await _upload(client, uid, ids["staged_material_id"])
        (staged_path,) = _files(root) - before
        await db.commit()

        old = os.path.getmtime(os.path.join(root, staged_path)) - ORPHAN_GRACE_SECONDS - 60
        os.utime(os.path.join(root, staged_path), (old, old))
        await EtOrphanVideoSweeper().run(db, root=root)

        assert staged_path in _files(root)


async def _staged_video_row(db, course_id: int) -> EtCourseContentStage:
    db.expire_all()
    return await db.scalar(
        select(EtCourseContentStage).where(
            EtCourseContentStage.course_id == course_id,
            EtCourseContentStage.entity_type == ENTITY_MATERIAL_VIDEO,
        )
    )


class TestApplyEdgeCases:
    """發布（按「更新」）時掛檔的邊界：交易回滾、升級前的暫存列、掛不上。"""

    async def test_更新交易回滾後暫存列與檔案仍一致_重試可成功(self, client, db, root, monkeypatch) -> None:
        """選 hard link 而非搬移的核心理由：回滾後暫存列仍指向原路徑，檔案必須還在。"""
        uid = await _user(db, "ZT_VO8")
        ids = await _staged_new_material(client, db, uid)
        before = _files(root)
        await _upload(client, uid, ids["staged_material_id"])
        (staged_path,) = _files(root) - before
        await db.commit()

        async def boom(*_a, **_k):
            raise AppError(status_code=409, detail="模擬套用後段失敗", error_code="ET_LOCK_001")

        monkeypatch.setattr("app.et.course.stage_apply._require_retest_for_flagged", boom)
        r = await client.post(f"{_COURSES}/{ids['course_id']}/content/apply", headers=_bearer(uid))
        assert r.status_code == 409, r.text
        await db.rollback()

        stage = await _staged_video_row(db, ids["course_id"])
        assert json.loads(stage.payload)["file_path"] == staged_path, "回滾後暫存列仍指向原路徑"
        assert os.path.isfile(os.path.join(root, staged_path)), "原路徑的檔案必須還在"

        monkeypatch.undo()
        monkeypatch.setattr(settings, "ET_VIDEO_STORAGE_ROOT", root)
        await _apply(client, db, uid, ids["course_id"])
        video = await _live_video_of_new_material(db, ids)
        storage.mark_ownership_fence_enforced(root)
        assert (await _play(client, uid, video.video_id)).status_code == 200

    async def test_升級前上傳的舊式暫存列_更新時同樣掛回正式目錄(self, client, db, root) -> None:
        """#871 之前暫存上傳的影片落在 `{abs(暫存 id)}/`；部署時正在編輯的課程，暫存列帶的就是這種路徑。"""
        uid = await _user(db, "ZT_VO9")
        ids = await _staged_new_material(client, db, uid)
        before = _files(root)
        await _upload(client, uid, ids["staged_material_id"])
        (staged_path,) = _files(root) - before
        legacy = f"{-ids['staged_material_id']}/{staged_path.split('/')[1]}"
        os.makedirs(os.path.join(root, legacy.split("/")[0]), exist_ok=True)
        os.replace(os.path.join(root, staged_path), os.path.join(root, legacy))
        stage = await _staged_video_row(db, ids["course_id"])
        stage.payload = json.dumps(json.loads(stage.payload) | {"file_path": legacy}, ensure_ascii=False)
        await db.commit()
        storage.mark_ownership_fence_enforced(root)

        await _apply(client, db, uid, ids["course_id"])

        video = await _live_video_of_new_material(db, ids)
        assert video.file_path.split("/")[0] == str(video.material_id)
        assert (await _play(client, uid, video.video_id)).status_code == 200

    async def test_來源檔不存在時不擋更新_保留原路徑(self, client, db, root) -> None:
        uid = await _user(db, "ZT_VO10")
        ids = await _staged_new_material(client, db, uid)
        before = _files(root)
        await _upload(client, uid, ids["staged_material_id"])
        (staged_path,) = _files(root) - before
        os.remove(os.path.join(root, staged_path))
        await db.commit()
        storage.mark_ownership_fence_enforced(root)

        await _apply(client, db, uid, ids["course_id"])

        video = await _live_video_of_new_material(db, ids)
        assert video.file_path == staged_path

    async def test_檔案系統錯誤_圍籬生效後中止更新(self, client, db, root, monkeypatch) -> None:
        """保留原路徑等於寫進一支學員必然 404 的影片，而遷移腳本已跑完、沒有人會再撈到它。"""
        uid = await _user(db, "ZT_VO11")
        ids = await _staged_new_material(client, db, uid)
        await _upload(client, uid, ids["staged_material_id"])
        await db.commit()
        storage.mark_ownership_fence_enforced(root)

        def denied(*_a, **_k):
            raise PermissionError("模擬目錄權限錯誤")

        monkeypatch.setattr(storage, "link_into_material", denied)
        r = await client.post(f"{_COURSES}/{ids['course_id']}/content/apply", headers=_bearer(uid))

        assert r.status_code == 500
        assert r.json()["error_code"] == "ET_STAGE_002"
        assert root not in r.text

    async def test_檔案系統錯誤_圍籬未生效時不擋更新(self, client, db, root, monkeypatch) -> None:
        uid = await _user(db, "ZT_VO12")
        ids = await _staged_new_material(client, db, uid)
        before = _files(root)
        await _upload(client, uid, ids["staged_material_id"])
        (staged_path,) = _files(root) - before
        await db.commit()

        def denied(*_a, **_k):
            raise PermissionError("模擬目錄權限錯誤")

        monkeypatch.setattr(storage, "link_into_material", denied)
        await _apply(client, db, uid, ids["course_id"])

        video = await _live_video_of_new_material(db, ids)
        assert video.file_path == staged_path, "保留原路徑，留給遷移腳本處理"
        assert (await _play(client, uid, video.video_id)).status_code == 200


class TestApplyDoesNotLegitimize:
    """Security review（#871）：「更新」不得把錯指到他份教材的檔掛進本教材目錄。"""

    async def test_新增影片的路徑指向他份教材目錄_不掛過來_圍籬生效後仍擋(self, client, db, root) -> None:
        uid = await _user(db, "ZT_VO13")
        ids = await _staged_new_material(client, db, uid)
        await _upload(client, uid, ids["staged_material_id"])
        foreign = f"{ids['material_id']}/{uuid.uuid4().hex}.mp4"  # 本課程另一份教材（教材甲）的目錄
        os.makedirs(os.path.join(root, str(ids["material_id"])), exist_ok=True)
        with open(os.path.join(root, foreign), "wb") as f:
            f.write(b"other-material")
        stage = await _staged_video_row(db, ids["course_id"])
        stage.payload = json.dumps(json.loads(stage.payload) | {"file_path": foreign}, ensure_ascii=False)
        await db.commit()
        storage.mark_ownership_fence_enforced(root)

        await _apply(client, db, uid, ids["course_id"])

        video = await _live_video_of_new_material(db, ids)
        assert video.file_path == foreign, "不在本教材暫存目錄的檔，保留原路徑、不掛過來"
        assert (await _play(client, uid, video.video_id)).status_code == 404
