"""ET02 教材影片上傳整合測試（US3 / #203）。

**含一條真的呼叫 `ffprobe` 的測試**（`TestUpload::test_真實影片取得長度`）。

為何不全部 mock 掉 `probe_duration_sec`：mock 之後，ffprobe 的參數打錯、timeout
沒設、輸出解析寫錯，CI 一概不會知道。而這條接線斷掉的症狀是「**所有影片都傳不
上去**」——比純函式邏輯錯誤嚴重得多。純函式部分已由
`tests/unit/et/test_video_probe.py` 完整覆蓋（25 條），此處只補接線。

> ⚠️ 本檔需執行環境有 **ffmpeg**（見 README 環境需求）。缺少時 `ffprobe` 找不到，
> service 會回 `ET_MATERIAL_004` 並記 ERROR log——那條測試會失敗，這是刻意的：
> 環境缺件應該讓 CI 紅燈，而不是靜靜地跳過。
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.params.models import DpParamDetail
from app.dp.users.models import DpUser
from app.et.constants import ITEM_MATERIAL, ROLE_TEACHER
from app.et.material import storage
from app.et.material.models import EtMaterialVideo
from app.et.material.video_probe import probe_duration_sec
from app.et.progress.models import EtProgressInterval, EtProgressVideo
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"
_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "sample_3s.mp4"


async def _user(db, user_id: str) -> str:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local",
            pwd_hash=hash_password("Abcd1234"),
            user_name=f"測試{user_id}",
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=now,
            must_change_pwd=False,
            created_user="admin01",
            created_date=now,
        )
    )
    db.add(
        EtUserRole(
            user_id=user_id, role=ROLE_TEACHER, is_active=True, created_user="SYSTEM", created_date=now, deleted=0
        )
    )
    await db.flush()
    return user_id


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _material(client, uid: str) -> int:
    created = await client.post(_COURSES, json={"course_name": "課程"}, headers=_bearer(uid))
    cid = created.json()["course_id"]
    ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(uid))
    item = await client.post(
        f"/api/et/chapters/{ch.json()['chapter_id']}/items",
        json={"item_type": ITEM_MATERIAL, "title": "教材"},
        headers=_bearer(uid),
    )
    return item.json()["material_id"]


async def _upload(client, uid: str, material_id: int, *, name: str, content: bytes | None = None):
    payload = content if content is not None else _FIXTURE.read_bytes()
    return await client.post(
        f"/api/et/materials/{material_id}/videos",
        files={"file": (name, payload, "video/mp4")},
        headers=_bearer(uid),
    )


async def _set_max_size_mb(db, value: str) -> None:
    """改 `DP_PARAM.ET_VIDEO_MAX_SIZE_MB`——用來驗證大小上限確實生效。

    設 `0` 可讓任何非空檔案都超標，不必真的傳一份 500 MB 的檔案。
    """
    row = await db.scalar(
        select(DpParamDetail).where(
            DpParamDetail.param_id == "ET_VIDEO_MAX_SIZE_MB", DpParamDetail.param_key == "VALUE"
        )
    )
    row.param_value = value
    await db.flush()


async def _put(client, uid: str, mid: int, **overrides):
    """送**完整**教材狀態。`video_ids` 為**要保留的**影片，未列出者視為刪除。"""
    payload = {
        "material_name": "教材",
        "description_html": None,
        "doc_ids": [],
        "video_ids": [],
        "version": 0,
        **overrides,
    }
    return await client.put(f"/api/et/materials/{mid}", json=payload, headers=_bearer(uid))


@pytest.fixture
def discard_spy(monkeypatch):
    """記錄 `storage.discard` 的呼叫（仍實際刪檔），用來驗證失敗路徑有清乾淨。

    ⚠️ **不可改用「比對暫存目錄前後檔案清單」**——那個目錄是全域共用的，而 CI 以
    pytest-xdist 12 個 worker 並行，其他 worker 的上傳會同時在裡面增刪檔案，
    斷言必然飄。2026-08-27 的 CI 就是這樣紅的（單獨跑過、並行跑掛）。

    觀測「清理有沒有被呼叫」則只碰本次請求的狀態，與並行無關。
    """
    calls: list[str] = []
    original = storage.discard

    def spy(path: str) -> None:
        calls.append(path)
        original(path)

    monkeypatch.setattr(storage, "discard", spy)
    return calls


class TestUpload:
    async def test_真實影片取得長度(self, client, db) -> None:
        """⚠️ 這條真的呼叫 ffprobe——接線壞掉時所有影片都會傳不上去。

        fixture 是一支 3.000000 秒的 mp4（32x32、2.4 KB），`DURATION_SEC` 應為 3。
        """
        uid = await _user(db, "ETV_U1")
        mid = await _material(client, uid)
        r = await _upload(client, uid, mid, name="sample.mp4")
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["duration_sec"] == 3, "ffprobe 接線或輸出解析有問題"
        assert body["file_name"] == "sample.mp4"
        assert body["file_size_bytes"] == _FIXTURE.stat().st_size
        assert body["sort_order"] == 1

    async def test_落地路徑在_storage_root_內(self, client, db) -> None:
        """#188 B2：即使 DB 中的路徑有瑕疵，讀取端圍籬也擋得住；寫入端本就不該逃逸。

        #233 起 `FILE_PATH` 存的是相對於 root 之片段，故以圍籬解析後再驗——這同時也驗到
        「寫入端產出的值，讀取端接得起來」這條契約。
        """
        uid = await _user(db, "ETV_U2")
        mid = await _material(client, uid)
        r = await _upload(client, uid, mid, name="sample.mp4")
        video = await db.scalar(select(EtMaterialVideo).where(EtMaterialVideo.video_id == r.json()["video_id"]))
        assert not os.path.isabs(video.file_path), "DB 應存相對片段（#233），存絕對路徑換 root 即失聯"
        resolved = storage.resolve_within_root(
            video.file_path, not_found=AssertionError("寫入端產出的路徑不應被讀取端圍籬擋下")
        )
        root = storage.storage_root()
        assert os.path.commonpath([root, resolved]) == root
        assert os.path.isfile(resolved), "DB 有紀錄但檔案不存在＝學員會拿到 404"

    async def test_多支影片順序自_1_遞增(self, client, db) -> None:
        uid = await _user(db, "ETV_U3")
        mid = await _material(client, uid)
        for i in range(3):
            r = await _upload(client, uid, mid, name=f"v{i}.mp4")
            assert r.status_code == 201, r.text
        rows = await db.scalars(
            select(EtMaterialVideo)
            .where(EtMaterialVideo.material_id == mid, EtMaterialVideo.deleted == 0)
            .order_by(EtMaterialVideo.sort_order)
        )
        assert [v.sort_order for v in rows] == [1, 2, 3]

    async def test_有影片時說明文字可留空(self, client, db) -> None:
        """三類媒材擇一即可——這條把「影片算一類」釘住。"""
        uid = await _user(db, "ETV_U4")
        mid = await _material(client, uid)
        up = await _upload(client, uid, mid, name="sample.mp4")
        r = await _put(client, uid, mid, video_ids=[up.json()["video_id"]])
        assert r.status_code == 204, r.text

    @pytest.mark.parametrize("name", ["sample.avi", "sample.mov", "sample.mkv", "sample.txt", "sample", "sample."])
    async def test_不允許之副檔名被擋(self, client, db, name: str) -> None:
        uid = await _user(db, f"ETV_F{abs(hash(name)) % 1000}")
        mid = await _material(client, uid)
        r = await _upload(client, uid, mid, name=name)
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_MATERIAL_003"

    async def test_超過大小上限被擋且不留半成品(self, client, db, discard_spy) -> None:
        """上限以**實際寫入位元組數**判定，不信 `Content-Length`。"""
        uid = await _user(db, "ETV_S1")
        mid = await _material(client, uid)
        await _set_max_size_mb(db, "0")

        r = await _upload(client, uid, mid, name="sample.mp4")
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_MATERIAL_003"
        assert discard_spy, "超標中止後應刪除半成品暫存檔"
        assert not any(os.path.exists(p) for p in discard_spy)
        rows = list(await db.scalars(select(EtMaterialVideo).where(EtMaterialVideo.material_id == mid)))
        assert rows == [], "被擋下的上傳不應留下 DB 紀錄"

    async def test_非影片內容無法解析長度而拒收(self, client, db, discard_spy) -> None:
        """副檔名對但內容不是影片——ffprobe 讀不出長度，依 data-model 不得存檔。

        這也是「副檔名檢核不足以判定是影片」的補強：真正的內容驗證由 ffprobe 承擔。
        """
        uid = await _user(db, "ETV_P1")
        mid = await _material(client, uid)

        r = await _upload(client, uid, mid, name="fake.mp4", content=b"this is definitely not a video" * 100)
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_MATERIAL_004"
        assert discard_spy, "解析失敗後應刪除暫存檔"
        assert not any(os.path.exists(p) for p in discard_spy)
        rows = list(await db.scalars(select(EtMaterialVideo).where(EtMaterialVideo.material_id == mid)))
        assert rows == [], "長度取不到時不得存檔（覆蓋率分母缺失會使章節永久卡住）"

    async def test_超長檔名回_422_而非_500(self, client, db) -> None:
        """`FILE_NAME` 為 VARCHAR(200)。不設限時超長檔名會在 INSERT 撞
        StringDataRightTruncation，冒成未處理的 500——使用者只看得到「伺服器處理
        失敗」。與 #202 修過的三個「越界回 500」屬同一類。"""
        uid = await _user(db, "ETV_LONG")
        mid = await _material(client, uid)
        r = await _upload(client, uid, mid, name="a" * 250 + ".mp4")
        assert r.status_code == 422
        assert r.json()["error_code"] == "ET_MATERIAL_006"

    async def test_剛好等於上限之檔名可上傳(self, client, db) -> None:
        """邊界值——200 字元應通過，201 才擋。"""
        uid = await _user(db, "ETV_LONG2")
        mid = await _material(client, uid)
        name = "a" * (200 - len(".mp4")) + ".mp4"
        assert len(name) == 200
        r = await _upload(client, uid, mid, name=name)
        assert r.status_code == 201, r.text

    async def test_同名影片重複上傳被擋(self, client, db) -> None:
        uid = await _user(db, "ETV_DUP")
        mid = await _material(client, uid)
        first = await _upload(client, uid, mid, name="sample.mp4")
        assert first.status_code == 201, first.text

        again = await _upload(client, uid, mid, name="sample.mp4")
        assert again.status_code == 409
        assert again.json()["error_code"] == "ET_MATERIAL_005"

    async def test_重複上傳不留下半成品檔案(self, client, db, discard_spy) -> None:
        """在寫檔之前就擋下——不該白做一次 500 MB 的 I/O。"""
        uid = await _user(db, "ETV_DUP2")
        mid = await _material(client, uid)
        await _upload(client, uid, mid, name="sample.mp4")
        await _upload(client, uid, mid, name="sample.mp4")
        assert discard_spy == [], "在寫檔之前就擋下——不該產生任何暫存檔可清"

    async def test_移除後可再次上傳同名影片(self, client, db) -> None:
        """檢核只看未刪除的影片——誤刪後不該永久無法用回原本的檔名。"""
        uid = await _user(db, "ETV_DUP3")
        mid = await _material(client, uid)
        first = await _upload(client, uid, mid, name="sample.mp4")
        await _put(client, uid, mid, description_html="<p>說明</p>", video_ids=[])

        again = await _upload(client, uid, mid, name="sample.mp4")
        assert again.status_code == 201, f"移除後應可再次上傳同名影片：{again.text}"
        assert again.json()["video_id"] != first.json()["video_id"]

    async def test_不同檔名可上傳(self, client, db) -> None:
        uid = await _user(db, "ETV_DUP4")
        mid = await _material(client, uid)
        await _upload(client, uid, mid, name="a.mp4")
        r = await _upload(client, uid, mid, name="b.mp4")
        assert r.status_code == 201, r.text

    async def test_非擁有者不可上傳(self, client, db) -> None:
        owner = await _user(db, "ETV_A1")
        other = await _user(db, "ETV_A2")
        mid = await _material(client, owner)
        r = await _upload(client, other, mid, name="sample.mp4")
        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_COURSE_002"

    async def test_教材不存在回_404(self, client, db) -> None:
        uid = await _user(db, "ETV_A3")
        r = await _upload(client, uid, 999999, name="sample.mp4")
        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_MATERIAL_001"


class TestDelete:
    """影片刪除走 `PUT /materials/{id}` 的 `video_ids`——未列出者視為刪除。

    改成這樣是因為逐筆即時刪除會繞過「至少擇一媒材」的檢核，也讓「取消」失去意義
    （2026-08-26 依實測回饋）。
    """

    async def test_軟刪除影片並連帶學員觀看紀錄(self, client, db) -> None:
        uid = await _user(db, "ETV_D1")
        mid = await _material(client, uid)
        r = await _upload(client, uid, mid, name="sample.mp4")
        vid = r.json()["video_id"]
        now = utcnow()
        audit = {"created_user": uid, "created_date": now, "deleted": 0}
        db.add(EtProgressVideo(user_id="STU01", video_id=vid, coverage_pct=50, **audit))
        db.add(EtProgressInterval(user_id="STU01", video_id=vid, start_sec=0, end_sec=2, **audit))
        await db.flush()

        # 移除影片但補上說明文字，否則會變成空教材而被 ET_MATERIAL_002 擋下
        d = await _put(client, uid, mid, description_html="<p>說明</p>", video_ids=[])
        assert d.status_code == 204, d.text
        video = await db.scalar(select(EtMaterialVideo).where(EtMaterialVideo.video_id == vid))
        assert video.deleted == 1
        for model in (EtProgressVideo, EtProgressInterval):
            rows = list(await db.scalars(select(model).where(model.video_id == vid)))
            assert rows and all(x.deleted == 1 for x in rows), f"{model.__name__} 應連帶軟刪"

    async def test_刪除後保留磁碟檔案(self, client, db) -> None:
        """軟刪除的語意是可回復——把檔案砍了就回復不了。"""
        uid = await _user(db, "ETV_D2")
        mid = await _material(client, uid)
        r = await _upload(client, uid, mid, name="sample.mp4")
        video = await db.scalar(select(EtMaterialVideo).where(EtMaterialVideo.video_id == r.json()["video_id"]))
        # FILE_PATH 為相對片段（#233），須併上 root 才是檔案系統路徑
        path = os.path.join(storage.storage_root(), video.file_path)

        await _put(client, uid, mid, description_html="<p>說明</p>", video_ids=[])
        assert os.path.isfile(path), "軟刪除不應刪磁碟檔案，否則無法回復"

    async def test_刪除後剩餘影片順序遞補(self, client, db) -> None:
        """部分唯一索引若未排除軟刪列，遞補會撞鍵——這條釘住該 migration。"""
        uid = await _user(db, "ETV_D3")
        mid = await _material(client, uid)
        ids = [(await _upload(client, uid, mid, name=f"v{i}.mp4")).json()["video_id"] for i in range(3)]

        d = await _put(client, uid, mid, video_ids=ids[1:])
        assert d.status_code == 204, d.text
        rows = await db.scalars(
            select(EtMaterialVideo)
            .where(EtMaterialVideo.material_id == mid, EtMaterialVideo.deleted == 0)
            .order_by(EtMaterialVideo.sort_order)
        )
        remaining = list(rows)
        assert [v.video_id for v in remaining] == ids[1:]
        assert [v.sort_order for v in remaining] == [1, 2]

    async def test_移除最後一支影片而無其他媒材時被擋(self, client, db) -> None:
        """檢核的是**存檔後的狀態**——逐筆即時刪除會繞過這一條。"""
        uid = await _user(db, "ETV_D4")
        mid = await _material(client, uid)
        r = await _upload(client, uid, mid, name="sample.mp4")
        vid = r.json()["video_id"]

        d = await _put(client, uid, mid, video_ids=[])
        assert d.status_code == 422
        assert d.json()["error_code"] == "ET_MATERIAL_002"
        video = await db.scalar(select(EtMaterialVideo).where(EtMaterialVideo.video_id == vid))
        assert video.deleted == 0, "被擋下的請求須整批回滾"

    async def test_非擁有者不可刪除(self, client, db) -> None:
        owner = await _user(db, "ETV_D5")
        other = await _user(db, "ETV_D6")
        mid = await _material(client, owner)
        await _upload(client, owner, mid, name="sample.mp4")
        d = await _put(client, other, mid, description_html="<p>x</p>", video_ids=[])
        assert d.status_code == 403


class TestLoopIndependence:
    """⚠️ 釘住 2026-08-26 的實測事故：影片上傳在 `fastapi dev` 下必定 500。

    uvicorn 於 `--reload` 或多 worker 時（`use_subprocess=True`）選用
    `SelectorEventLoop`，而 Windows 的 SelectorEventLoop **不實作**
    `_make_subprocess_transport`——原本以 `asyncio.create_subprocess_exec` 呼叫
    ffprobe 的實作因此拋 `NotImplementedError`，冒成未處理的 500。

    整套測試當時全綠卻擋不下它：測試跑在預設（Proactor）迴圈上，而正式環境單 worker
    也是 Proactor。**只有開發模式會壞**——最容易被當成「我這台環境的問題」的形狀。

    現行實作以 `asyncio.to_thread` + 阻塞版 `subprocess.run`，與迴圈實作無關。
    """

    def test_於_selector_事件迴圈下仍可解析長度(self) -> None:
        policy = asyncio.get_event_loop_policy()
        try:
            if sys.platform == "win32":
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            loop = asyncio.new_event_loop()
            try:
                assert loop.run_until_complete(probe_duration_sec(str(_FIXTURE))) == 3
            finally:
                loop.close()
        finally:
            asyncio.set_event_loop_policy(policy)


class TestStorageFence:
    """storage-root 圍籬（#188 B2）——讀取者可能是無任何管理權限的學員。"""

    @pytest.mark.parametrize(
        "path",
        [
            "",
            "../../../etc/passwd",
            "/etc/passwd",
            "C:\\Windows\\win.ini",
        ],
    )
    def test_逃逸路徑被擋(self, path: str) -> None:
        from app.core.exceptions import AppError

        sentinel = AppError(status_code=404, detail="查無此影片", error_code="ET_MATERIAL_001")
        with pytest.raises(AppError) as exc:
            storage.resolve_within_root(path, not_found=sentinel)
        assert exc.value.error_code == "ET_MATERIAL_001"

    def test_root_內路徑通過並回正規化結果(self) -> None:
        inside = os.path.join(storage.storage_root(), "1", "abc.mp4")
        from app.core.exceptions import AppError

        sentinel = AppError(status_code=404, detail="x", error_code="ET_MATERIAL_001")
        assert storage.resolve_within_root(inside, not_found=sentinel) == os.path.realpath(inside)

    def test_非字串一律擋下(self) -> None:
        """fail-closed：`None` 進來時不可當成「沒設路徑所以放行」。"""
        from app.core.exceptions import AppError

        sentinel = AppError(status_code=404, detail="x", error_code="ET_MATERIAL_001")
        with pytest.raises(AppError):
            storage.resolve_within_root(None, not_found=sentinel)  # type: ignore[arg-type]
