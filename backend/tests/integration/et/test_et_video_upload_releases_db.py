"""ET 影片上傳在寫檔與 `ffprobe` 期間不佔 DB 連線（#833 A1）。

`upload_video` 先查教材與限制、再把最大 500 MB 的檔寫進儲存區、跑 `ffprobe`，最後才寫 DB。
中間那兩段可達數分鐘，原本交易一直開著（idle in transaction）、佔住一條連線——連線池上限
15 條（`DB_POOL_SIZE` 5 + `DB_MAX_OVERFLOW` 10），兩三位教師同時上傳就佔掉一大半，而查詢逾時
（#827）只管單一查詢、管不到閒置的交易。

本檔以 conftest 的 `db` session 觀察：測試時 app 與測試共用這個 session（savepoint 模式），
寫檔與 `ffprobe` 被呼叫的當下 `db.in_transaction()` 必須為 False。

⚠️ 這只證明**交易已結束**。測試的 session 綁在 fixture 的固定連線上，觀察不到「連線還回連線池」；
正式環境還得回去，靠的是 `get_db` 的 session 綁 engine、且 `expire_on_commit=False`（commit 後
讀既有物件不會再借連線）——那兩件事不在本檔的驗證範圍。

拆段之後授權在第 3 段重新做一次，「上傳到一半資料被改」也在本檔：第 3 段必須擋下、並把已搬到
正式路徑的檔刪掉。

⚠️ 本檔的上傳走真的 `ffprobe`（比照 `test_et_video.py`），需執行環境有 ffmpeg。
"""

from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from app.core.config import settings
from app.et.constants import ITEM_MATERIAL
from app.et.course.models import EtCourse, EtCourseContentStage
from app.et.material import service as material_service
from app.et.material.models import EtMaterial, EtMaterialVideo
from tests.integration.et.test_et_staged_write_paths import _bearer, _course_with_content, _publish, _user

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "sample_3s.mp4"


@pytest.fixture(autouse=True)
def _root(tmp_path, monkeypatch):
    """儲存根目錄改指 tmp_path，不寫進開發環境的影片目錄（比照 `test_et_orphan_video_sweep.py`）。"""
    monkeypatch.setattr(settings, "ET_VIDEO_STORAGE_ROOT", str(tmp_path))


@pytest.fixture
def in_transaction_during_io(db, monkeypatch) -> dict[str, list[bool]]:
    """記錄「寫檔」與「`ffprobe`」被呼叫當下，session 是否仍在交易中。"""
    seen: dict[str, list[bool]] = {"save": [], "probe": []}
    original_save = material_service.storage.save_video_stream
    original_probe = material_service.probe_duration_sec

    async def save(*args, **kwargs):
        seen["save"].append(db.in_transaction())
        return await original_save(*args, **kwargs)

    async def probe(*args, **kwargs):
        seen["probe"].append(db.in_transaction())
        return await original_probe(*args, **kwargs)

    monkeypatch.setattr(material_service.storage, "save_video_stream", save)
    monkeypatch.setattr(material_service, "probe_duration_sec", probe)
    return seen


async def _upload(client, uid: str, material_id: int, content: bytes | None = None):
    return await client.post(
        f"/api/et/materials/{material_id}/videos",
        files={"file": ("lesson.mp4", content if content is not None else _FIXTURE.read_bytes(), "video/mp4")},
        headers=_bearer(uid),
    )


async def _stage_rows(db, course_id: int) -> int:
    return await db.scalar(
        select(func.count()).select_from(EtCourseContentStage).where(EtCourseContentStage.course_id == course_id)
    )


@pytest.mark.parametrize("published", [False, True], ids=["草稿課程", "已發布課程（暫存模式）"])
async def test_寫檔與_ffprobe_期間交易已結束(client, db, in_transaction_during_io, published) -> None:
    uid = await _user(db, "ZT_UPR1" if published else "ZT_UPR2")
    ids = await _course_with_content(client, db, uid)
    if published:
        await _publish(client, db, uid, ids["course_id"])

    r = await _upload(client, uid, ids["material_id"])

    assert r.status_code == 201, r.text
    # 正向錨點：兩個函式確實被呼叫到——下面的 False 不是因為根本沒走到那裡
    assert in_transaction_during_io == {"save": [False], "probe": [False]}, "寫檔／ffprobe 期間仍持有交易與連線"
    if published:
        # 上傳結果仍進了暫存區（拆段之後寫入照常完成）
        assert await _stage_rows(db, ids["course_id"]) > 0


async def test_已發布課程上傳失敗不留下暫存區(client, db) -> None:
    """寫檔前不可有任何 DB 寫入：第一次上傳會把活表複製進暫存區，若在寫檔前就 commit，
    之後 `ffprobe` 失敗、上傳被拒，那份「沒有任何修改的暫存」會留下來——編輯頁以「暫存區存在」
    判定有未更新的變更，教師明明什麼都沒改，卻被提示「有尚未更新的變更」。
    """
    uid = await _user(db, "ZT_UPR3")
    ids = await _course_with_content(client, db, uid)
    await _publish(client, db, uid, ids["course_id"])
    assert await _stage_rows(db, ids["course_id"]) == 0, "前置：發布後暫存區是空的"

    r = await _upload(client, uid, ids["material_id"], content=b"not a video")

    assert r.status_code == 422, r.text
    assert await _stage_rows(db, ids["course_id"]) == 0


@pytest.mark.parametrize("new_material", [False, True], ids=["既有教材", "本次新增的教材（負數 id）"])
async def test_暫存模式第二次上傳同名影片_比對暫存區並在寫檔前擋下(
    client, db, in_transaction_during_io, new_material
) -> None:
    """第 1 段要比對的是**暫存區**的影片：教師這次剛上傳的那支只在暫存區，比活表就擋不到，
    按「更新」時兩支同名影片一起進活表。

    兩條路徑各一：既有教材（第一次上傳把它複製進暫存區，第二次走 `node_of`）、本次編輯新增
    的教材（負數 id，走 `resolve_new`）。
    """
    uid = await _user(db, "ZT_UPR10" if new_material else "ZT_UPR11")
    ids = await _course_with_content(client, db, uid)
    await _publish(client, db, uid, ids["course_id"])
    material_id = ids["material_id"]
    if new_material:
        created = await client.post(
            f"/api/et/chapters/{ids['chapter_id']}/items",
            json={"item_type": ITEM_MATERIAL, "title": "暫存教材"},
            headers=_bearer(uid),
        )
        assert created.status_code == 201, created.text
        material_id = created.json()["material_id"]
        assert material_id < 0, "前置：已發布課程新增的教材在暫存區、對外是負數 id"

    first = await _upload(client, uid, material_id)
    assert first.status_code == 201, first.text

    second = await _upload(client, uid, material_id)

    assert second.status_code == 409, second.text
    assert second.json()["error_code"] == "ET_MATERIAL_005"
    assert in_transaction_during_io["save"] == [False], "第二次在寫檔前就該擋下，只有第一次寫過檔"


# ── 上傳到一半資料被改：第 3 段重新授權 ─────────────────────────────────────


@pytest.fixture
def promoted(monkeypatch) -> list[str]:
    """記錄搬到正式路徑的檔——正向錨點：檔確實寫到過那裡，「事後不存在」才代表被刪掉了。"""
    paths: list[str] = []
    original = material_service.storage.promote

    def promote(*args, **kwargs):
        final_abs, final_rel = original(*args, **kwargs)
        paths.append(final_abs)
        return final_abs, final_rel

    monkeypatch.setattr(material_service.storage, "promote", promote)
    return paths


@pytest.fixture
def during_probe(monkeypatch) -> Callable[[Callable[[], Awaitable[None]]], None]:
    """在 `ffprobe` 被呼叫時（第 1 段已 commit、第 3 段還沒開始）執行一段資料變動。"""

    def install(mutate: Callable[[], Awaitable[None]]) -> None:
        original = material_service.probe_duration_sec

        async def probe(*args, **kwargs):
            await mutate()
            return await original(*args, **kwargs)

        monkeypatch.setattr(material_service, "probe_duration_sec", probe)

    return install


@pytest.mark.parametrize("published", [False, True], ids=["草稿課程", "已發布課程（暫存模式）"])
async def test_上傳期間課程換了擁有者_第3段擋下並刪檔(client, db, promoted, during_probe, published) -> None:
    uid = await _user(db, "ZT_UPR4" if published else "ZT_UPR5")
    other = await _user(db, "ZT_UPR6" if published else "ZT_UPR7")
    ids = await _course_with_content(client, db, uid)
    if published:
        await _publish(client, db, uid, ids["course_id"])

    async def transfer() -> None:
        await db.execute(update(EtCourse).where(EtCourse.course_id == ids["course_id"]).values(owner_id=other))

    during_probe(transfer)
    r = await _upload(client, uid, ids["material_id"])

    assert r.status_code == 403, r.text
    assert len(promoted) == 1, "前置：檔案確實搬到過正式路徑"
    assert not Path(promoted[0]).exists(), "第 3 段擋下後，正式路徑的檔必須刪掉"


async def test_上傳期間教材被刪_第3段回404並刪檔(client, db, promoted, during_probe) -> None:
    uid = await _user(db, "ZT_UPR8")
    ids = await _course_with_content(client, db, uid)

    async def soft_delete() -> None:
        await db.execute(update(EtMaterial).where(EtMaterial.material_id == ids["material_id"]).values(deleted=1))

    during_probe(soft_delete)
    r = await _upload(client, uid, ids["material_id"])

    assert r.status_code == 404, r.text
    assert len(promoted) == 1, "前置：檔案確實搬到過正式路徑"
    assert not Path(promoted[0]).exists()
    videos = await db.scalar(
        select(func.count()).select_from(EtMaterialVideo).where(EtMaterialVideo.material_id == ids["material_id"])
    )
    assert videos == 0


async def test_暫存區已刪掉的教材_寫檔前就回404(client, db, in_transaction_during_io) -> None:
    """已發布課程在這次編輯中刪掉了教材，再對它上傳要在**寫檔之前**就 404。

    暫存區有這門課、卻查不到這份教材的節點，就是被刪了（`ref_for_source` 的「查不到有兩種」）。
    第 1 段若把它當成「暫存區還沒有這份教材」改比活表，就會放行——500 MB 寫完、`ffprobe`
    跑完才在第 3 段 404，教師的等待全部白費。
    """
    uid = await _user(db, "ZT_UPR9")
    ids = await _course_with_content(client, db, uid)
    await _publish(client, db, uid, ids["course_id"])
    deleted = await client.delete(f"/api/et/items/{ids['material_item_id']}", headers=_bearer(uid))
    assert deleted.status_code in (200, 204), deleted.text
    assert await _stage_rows(db, ids["course_id"]) > 0, "前置：刪除發生在暫存區"

    r = await _upload(client, uid, ids["material_id"])

    assert r.status_code == 404, r.text
    assert in_transaction_during_io == {"save": [], "probe": []}, "教材已刪，不該開始寫檔"
