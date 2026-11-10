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
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from app.core.auth import create_access_token
from app.core.config import settings
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.constants import ITEM_MATERIAL
from app.et.course.models import EtCourse, EtCourseContentStage
from app.et.material import service as material_service
from app.et.material.models import EtMaterial, EtMaterialVideo
from app.et.roles.models import EtUserRole
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
        await db.execute(
            update(EtCourse)
            .where(EtCourse.course_id == ids["course_id"])
            .values(owner_id=other)
            .execution_options(synchronize_session=False)
        )

    pinned = await db.get(EtCourse, ids["course_id"])  # 留住實體，理由見 `test_上傳期間帳號停用或角色被撤`
    during_probe(transfer)
    r = await _upload(client, uid, ids["material_id"])
    assert pinned is not None

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


# ⚠️ 一律 `synchronize_session=False`：正式環境是**別的連線**停用帳號，不會同步本請求 session 裡已載入的
# 物件；預設的同步會順手改掉 identity map 裡的實體，第 3 段若讀到舊物件就看不出來（code review）。
async def _disable_account(db, uid: str) -> None:
    await db.execute(
        update(DpUser)
        .where(DpUser.user_id == uid)
        .values(status="DISABLED")
        .execution_options(synchronize_session=False)
    )


# 🥇 三個時點必須錯開，否則測不出「有沒有把 token 的 auth_time 傳進去」：
#
#   帳號原本的 pwd_changed_date ── token 的 auth_time ── 上傳期間改密碼 ── 重驗當下
#        now-30m                      now-10m              now-5m          now
#
# 正確實作比的是 auth_time（now-10m < now-5m → 擋下）；若改成比 `utcnow()`
# （now < now-5m → 不擋）測試就會紅。**第一版把變更時點設成未來（now+5s），
# 兩種實作都會擋下、全綠，等於沒測到**——變異檢查當場抓到。
_TOKEN_AGE = timedelta(minutes=10)
_PWD_CHANGED_AGE = timedelta(minutes=5)
_ACCOUNT_PWD_AGE = timedelta(minutes=30)


async def _set_pwd_changed(db, uid: str, ago: timedelta) -> None:
    await db.execute(
        update(DpUser)
        .where(DpUser.user_id == uid)
        .values(pwd_changed_date=utcnow() - ago)
        .execution_options(synchronize_session=False)
    )


async def _revoke_teacher(db, uid: str) -> None:
    await db.execute(
        update(EtUserRole)
        .where(EtUserRole.user_id == uid)
        .values(is_active=False)
        .execution_options(synchronize_session=False)
    )


@pytest.mark.parametrize(
    ("published", "revoke"),
    [(False, _disable_account), (True, _disable_account), (False, _revoke_teacher)],
    ids=["草稿課程_帳號停用", "已發布課程_帳號停用", "草稿課程_撤銷教師角色"],
)
async def test_上傳期間帳號停用或角色被撤_第3段擋下並刪檔(
    client, db, promoted, during_probe, published, revoke
) -> None:
    """#905 B1：身分與角色只在請求開頭由 dependency 驗一次，上傳可達數分鐘；
    第 3 段原本只重驗擁有者，期間被停用或撤掉教師角色仍會寫入。"""
    uid = await _user(db, "ZT_UPR12" if published else ("ZT_UPR13" if revoke is _disable_account else "ZT_UPR14"))
    ids = await _course_with_content(client, db, uid)
    if published:
        await _publish(client, db, uid, ids["course_id"])

    # 留住請求開頭載入的實體：identity map 是弱參照，沒人留著時物件被回收，第 3 段重查自然讀到新值、
    # 「讀到舊物件」的錯就看不出來。正式環境只要有任何一層留著它（如日後的 dependency）就會中
    pinned = [await db.get(DpUser, uid), await db.get(EtCourse, ids["course_id"])]
    during_probe(lambda: revoke(db, uid))
    r = await _upload(client, uid, ids["material_id"])
    assert all(p is not None for p in pinned)

    assert r.status_code == 403, r.text
    assert len(promoted) == 1, "前置：檔案確實搬到過正式路徑"
    assert not Path(promoted[0]).exists(), "第 3 段擋下後，正式路徑的檔必須刪掉"
    if published:
        assert await _stage_rows(db, ids["course_id"]) == 0, "擋下時不可留下暫存區"
    else:
        videos = await db.scalar(
            select(func.count()).select_from(EtMaterialVideo).where(EtMaterialVideo.material_id == ids["material_id"])
        )
        assert videos == 0


async def test_上傳期間密碼被變更_第3段擋下並刪檔(client, db, promoted, during_probe) -> None:
    """#941：密碼變更使變更前簽發的 token 失效，第 3 段的重驗一併比對密碼變更時點。

    與上一條同一個空窗（串流寫檔 + `ffprobe`，上限 30 秒），差別只在失效的原因與狀態碼：
    停用 / 撤角色是 403，token 失效是 **401**（與其他無效 token 同一個 `DP_AUTH_002`，
    不替拿著舊 token 的一方指出「密碼剛被改過」）。

    ⚠️ 本條**不在上一條的 parametrize 內**：那組斷言寫死 403，混進去會逼它改成也吃 401，
    反而讓「停用該回 403」失去守門。
    """
    uid = await _user(db, "ZT_UPR17")
    ids = await _course_with_content(client, db, uid)

    # 帳號原本的變更時點要早於 token 的 auth_time，否則請求開頭的 dependency 就先擋下，
    # 根本走不到第 3 段——那樣測的是另一道閘。
    await _set_pwd_changed(db, uid, _ACCOUNT_PWD_AGE)
    old_token = create_access_token(sub=uid, ttl_minutes=15, auth_time=utcnow() - _TOKEN_AGE)

    # 留住請求開頭載入的實體：理由同上一條（identity map 是弱參照，沒人留著就看不出讀到舊物件）
    pinned = [await db.get(DpUser, uid), await db.get(EtCourse, ids["course_id"])]
    during_probe(lambda: _set_pwd_changed(db, uid, _PWD_CHANGED_AGE))
    r = await client.post(
        f"/api/et/materials/{ids['material_id']}/videos",
        files={"file": ("lesson.mp4", _FIXTURE.read_bytes(), "video/mp4")},
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert all(p is not None for p in pinned)

    assert r.status_code == 401, r.text
    assert r.json()["error_code"] == "DP_AUTH_002"
    assert len(promoted) == 1, "前置：檔案確實搬到過正式路徑"
    assert not Path(promoted[0]).exists(), "第 3 段擋下後，正式路徑的檔必須刪掉"
    videos = await db.scalar(
        select(func.count()).select_from(EtMaterialVideo).where(EtMaterialVideo.material_id == ids["material_id"])
    )
    assert videos == 0


@pytest.mark.parametrize("published", [False, True], ids=["草稿課程", "已發布課程（暫存模式）"])
async def test_兩個分頁同時上傳同名檔_後到者在第3段擋下並刪檔(client, db, promoted, during_probe, published) -> None:
    """#905 B2：第 1 段的同名檢查不持鎖，兩個分頁同時上傳同名檔原本都會通過。

    以「本次上傳的 `ffprobe` 期間，另一個分頁完成了同名上傳」模擬：後到者在第 3 段取鎖後重查、回 409。
    """
    uid = await _user(db, "ZT_UPR15" if published else "ZT_UPR16")
    ids = await _course_with_content(client, db, uid)
    if published:
        await _publish(client, db, uid, ids["course_id"])

    other_tab: list[int] = []

    async def other_tab_uploads() -> None:
        if other_tab:  # 另一個分頁的上傳也會經過這個 ffprobe，只觸發一次
            return
        other_tab.append(0)
        r = await _upload(client, uid, ids["material_id"])
        other_tab[0] = r.status_code

    during_probe(other_tab_uploads)
    r = await _upload(client, uid, ids["material_id"])

    assert other_tab == [201], "前置：另一個分頁的同名上傳先完成"
    assert r.status_code == 409, r.text
    assert r.json()["error_code"] == "ET_MATERIAL_005"
    assert len(promoted) == 2, "前置：兩支都搬到過正式路徑"
    assert Path(promoted[0]).exists(), "先完成的那支保留"
    assert not Path(promoted[1]).exists(), "後到者擋下後，正式路徑的檔必須刪掉"


async def test_上傳期間草稿課程被發布_影片進暫存區不進活表(client, db, promoted, during_probe) -> None:
    """第 1 段判定「草稿」之後課程被發布：第 3 段必須以發布後的狀態解析、走暫存區。
    沿用舊判定直接寫活表的話，已發布課程憑空多一支影片、學員立刻看得到（code review MEDIUM）。

    ⚠️ 本測試的發布發生在第 3 段**之前**；「發布恰好落在第 3 段判定與取鎖之間」需要兩個並行的交易，
    單一 session 的測試重現不了，鎖內重新解析那一步靠讀程式碼確認。
    """
    uid = await _user(db, "ZT_UPR17")
    ids = await _course_with_content(client, db, uid)
    pinned = await db.get(EtCourse, ids["course_id"])  # 留住實體，理由見 `test_上傳期間帳號停用或角色被撤`

    async def publish() -> None:
        await _publish(client, db, uid, ids["course_id"])

    during_probe(publish)
    r = await _upload(client, uid, ids["material_id"])

    assert pinned is not None
    assert r.status_code == 201, r.text
    assert r.json()["video_id"] < 0, "已發布課程的上傳應進暫存區（對外是負數 id）"
    live = await db.scalar(
        select(func.count()).select_from(EtMaterialVideo).where(EtMaterialVideo.material_id == ids["material_id"])
    )
    assert live == 0, "不可繞過暫存區直接寫進已發布課程的活表"
