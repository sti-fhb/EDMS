"""ET05 章節學習整合測試（US5 / #255）。

規則判定（授權、倍速限縮）已於 `tests/unit/et/test_learning_rules.py` 以純函式涵蓋。
此處只驗**需要真 DB 才驗得了**的事：

1. **四個端點各自的授權**——這是本 issue 的安全核心，影片與 DM 文件是實體檔案
2. 授權反查鏈（`video_id → material → item → chapter → course`）真的接得起來
3. 「先授權、後回報刪除」的順序（無權者不該分辨得出內容曾經存在）
4. 課程關閉**不過濾內容**（#255 裁示 Q2=A）
5. 擁有者可進入自己的課程（#255 裁示 Q1=A）
"""

import pytest
from sqlalchemy import update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.constants import (
    COURSE_CLOSED,
    COURSE_PUBLISHED,
    ITEM_MATERIAL,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_INVITATION_CODE,
)
from app.et.course.models import EtCourse, EtItem
from app.et.learning.video_ticket import TICKET_TTL_SECONDS
from app.et.material.models import EtMaterialVideo
from app.et.progress.models import EtEnrollment
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _user(db, user_id: str, role: str = ROLE_STUDENT) -> str:
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
    db.add(EtUserRole(user_id=user_id, role=role, is_active=True, created_user="SYSTEM", created_date=now, deleted=0))
    await db.flush()
    return user_id


async def _course_with_material(client, db, teacher: str, *, name: str = "採血作業教育") -> dict:
    """建課程 → 章節 → 教材項目 → 影片，回傳各層 id。

    影片直接寫 DB（不走上傳端點）：上傳需要真實檔案與 ffprobe，而本檔要驗的是授權與
    查詢，不是上傳流程。
    """
    created = await client.post(_COURSES, json={"course_name": name}, headers=_bearer(teacher))
    assert created.status_code == 201, created.text
    course_id = created.json()["course_id"]

    ch = await client.post(
        f"{_COURSES}/{course_id}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(teacher)
    )
    assert ch.status_code == 201, ch.text
    chapter_id = ch.json()["chapter_id"]

    item = await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": ITEM_MATERIAL, "title": "教材"},
        headers=_bearer(teacher),
    )
    assert item.status_code == 201, item.text
    item_id = item.json()["item_id"]
    material_id = item.json()["material_id"]

    now = utcnow()
    video = EtMaterialVideo(
        material_id=material_id,
        file_path="dummy/not-a-real-file.mp4",
        file_name="示範影片.mp4",
        duration_sec=600,
        file_size_bytes=1024,
        sort_order=1,
        created_user=teacher,
        created_date=now,
        deleted=0,
    )
    db.add(video)
    await db.flush()

    await db.execute(
        update(EtCourse)
        .where(EtCourse.course_id == course_id)
        .values(status=COURSE_PUBLISHED, invitation_code="30000001")
    )
    await db.flush()
    return {
        "course_id": course_id,
        "chapter_id": chapter_id,
        "item_id": item_id,
        "material_id": material_id,
        "video_id": video.video_id,
    }


async def _second_chapter_material(client, db, teacher: str, course_id: int) -> dict:
    """在既有課程加第二章 + 教材項目 + 影片，回傳該章的各層 id（#424）。

    第二章對「剛加入、第一章還沒完成」的學員而言**是鎖定的**——依序解鎖的章節層規則
    （`spec_us5` AC 9：前一章所有項目完成才解鎖下一章）。本 helper 的存在就是為了造出
    那個狀態；用第一章驗不到任何東西，它對誰都是解鎖的。
    """
    ch = await client.post(
        f"{_COURSES}/{course_id}/chapters", json={"chapter_name": "第二章"}, headers=_bearer(teacher)
    )
    assert ch.status_code == 201, ch.text
    chapter_id = ch.json()["chapter_id"]

    item = await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": ITEM_MATERIAL},
        headers=_bearer(teacher),
    )
    assert item.status_code == 201, item.text

    video = EtMaterialVideo(
        material_id=item.json()["material_id"],
        file_path="dummy/second-chapter.mp4",
        file_name="第二章影片.mp4",
        duration_sec=300,
        file_size_bytes=1024,
        sort_order=1,
        created_user=teacher,
        created_date=utcnow(),
        deleted=0,
    )
    db.add(video)
    await db.flush()
    return {
        "chapter_id": chapter_id,
        "item_id": item.json()["item_id"],
        "material_id": item.json()["material_id"],
        "video_id": video.video_id,
    }


async def _complete_material(client, user_id: str, *, video_id: int, item_id: int, duration_sec: int) -> None:
    """把一個**含影片**的教材項目走到完成（#424 的反向驗收要用）。

    ⚠️ 兩步缺一不可，且順序固定：含影片的教材**不是**「開啟即完成」——`mark_item_viewed`
    對它只更新「上次檢視項目」（見 `progress/service.mark_item_viewed` 的 docstring），
    完成與否由覆蓋率決定。故先上報涵蓋全片的區段，再呼叫 `viewed` 觸發完成判定。

    走真實端點而非直接寫 `IS_COMPLETED`：這幾條測試要驗的是「完成之後解鎖會前進」，
    直接寫 DB 等於跳過產生完成狀態的那段邏輯，測出來的綠燈證明不了學員實際走得通。
    """
    r = await client.post(
        f"/api/et/videos/{video_id}/intervals",
        json={"segments": [{"start_sec": 0, "end_sec": duration_sec}]},
        headers=_bearer(user_id),
    )
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/et/items/{item_id}/viewed", headers=_bearer(user_id))
    assert r.status_code == 200, r.text
    assert r.json()["completed"] is True, "前置條件不成立：教材未被判定為完成，後續的解鎖驗收會失去意義"


async def _enroll(db, user_id: str, course_id: int) -> None:
    db.add(
        EtEnrollment(
            user_id=user_id,
            course_id=course_id,
            join_source=SOURCE_INVITATION_CODE,
            joined_at=utcnow(),
            completion_status="NOT_STARTED",
            is_removed=False,
            created_user=user_id,
            created_date=utcnow(),
            deleted=0,
        )
    )
    await db.flush()


class TestAuthorization:
    """四個端點各自的授權——本 issue 的安全核心。"""

    async def test_非在籍者取不到四個端點之任一(self, client, db) -> None:
        """影片與 DM 文件是**實體檔案**。少一道判定，任何登入者知道 id 就能抓走全站教材。

        四個端點分開驗而不只驗一個：service 的授權是各端點各自呼叫的，共用一次查詢
        結果會讓「新增第五個端點時忘記掛」變成看不出來的遺漏。
        """
        teacher = await _user(db, "t_learn01", ROLE_TEACHER)
        outsider = await _user(db, "s_learn01")
        ids = await _course_with_material(client, db, teacher)
        h = _bearer(outsider)

        r_struct = await client.get(f"{_COURSES}/{ids['course_id']}/learn", headers=h)
        r_content = await client.get(f"/api/et/materials/{ids['material_id']}/content", headers=h)
        r_video = await client.post(f"/api/et/videos/{ids['video_id']}/ticket", headers=h)
        r_doc = await client.get(f"/api/et/materials/{ids['material_id']}/docs/DM-SOP-000001/file", headers=h)

        # 課程層：403 + 可行動的訊息（他可能正要加入）
        assert r_struct.status_code == 403
        assert r_struct.json()["error_code"] == "ET_LEARN_002"
        # 以 id 定址的資源：一律 404，不可分辨「不存在」與「無權」
        # 影片以「發票端點」代表——取檔端點本身憑票放行，授權在發票時完成
        for label, r in [("content", r_content), ("video-ticket", r_video), ("doc", r_doc)]:
            assert r.status_code == 404, f"{label}: {r.status_code} {r.text}"
            assert r.json()["error_code"] == "ET_LEARN_001", label

    async def test_在籍學員可取得結構(self, client, db) -> None:
        teacher = await _user(db, "t_learn02", ROLE_TEACHER)
        student = await _user(db, "s_learn02")
        ids = await _course_with_material(client, db, teacher)
        await _enroll(db, student, ids["course_id"])

        r = await client.get(f"{_COURSES}/{ids['course_id']}/learn", headers=_bearer(student))

        assert r.status_code == 200, r.text
        assert r.json()["is_owner"] is False

    async def test_擁有者可進入自己的課程(self, client, db) -> None:
        """#255 SA Q1 裁示 A。

        教師在 ET02 看到的是編輯視角，不進 ET05 無從確認學員實際看到什麼；而自己加入
        自己的課會被計入完課率分母。
        """
        teacher = await _user(db, "t_learn03", ROLE_TEACHER)
        ids = await _course_with_material(client, db, teacher)

        r = await client.get(f"{_COURSES}/{ids['course_id']}/learn", headers=_bearer(teacher))

        assert r.status_code == 200, r.text
        assert r.json()["is_owner"] is True, "前端據此顯示預覽模式提示"

    async def test_被移除之學員取不到教材(self, client, db) -> None:
        """#247 SA Q1 裁示 C 的延伸——不在籍即不可存取。

        ⚠️ 存取被擋這件事不變，**變的是訊息**：#280 起被移除者收到 `ET_LEARN_004`
        「您已被該課程移除」而非 `ET_LEARN_002`「您尚未加入此課程」（`spec_us6` 場景 28）。
        兩者都是 403，擋的力道完全相同。
        """
        teacher = await _user(db, "t_learn04", ROLE_TEACHER)
        student = await _user(db, "s_learn04")
        ids = await _course_with_material(client, db, teacher)
        await _enroll(db, student, ids["course_id"])
        await db.execute(
            update(EtEnrollment)
            .where(EtEnrollment.user_id == student, EtEnrollment.course_id == ids["course_id"])
            .values(is_removed=True, removed_at=utcnow())
        )
        await db.flush()

        r = await client.get(f"{_COURSES}/{ids['course_id']}/learn", headers=_bearer(student))

        assert r.status_code == 403
        assert r.json()["error_code"] == "ET_LEARN_004"

    async def test_他人教材之_doc_id_不可搭配自己有權的教材(self, client, db) -> None:
        """路徑為 `/materials/{material_id}/docs/{doc_id}/file`，授權由 material 側判定。

        未驗證 `doc_id` 確實被此教材引用的話，在籍任一課程者即可用自己有權的
        `material_id` 搭配任意 `doc_id`，取走全站被引用過的文件。
        """
        teacher = await _user(db, "t_learn05", ROLE_TEACHER)
        student = await _user(db, "s_learn05")
        ids = await _course_with_material(client, db, teacher)
        await _enroll(db, student, ids["course_id"])

        r = await client.get(
            f"/api/et/materials/{ids['material_id']}/docs/DM-SOP-999999/file", headers=_bearer(student)
        )

        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_LEARN_001"


class TestStructure:
    async def test_章節與項目依順序回傳(self, client, db) -> None:
        """AC 1 / AC 2：側欄結構。"""
        teacher = await _user(db, "t_learn06", ROLE_TEACHER)
        ids = await _course_with_material(client, db, teacher)

        body = (await client.get(f"{_COURSES}/{ids['course_id']}/learn", headers=_bearer(teacher))).json()

        assert len(body["chapters"]) == 1
        chapter = body["chapters"][0]
        assert chapter["chapter_name"] == "第一章"
        assert len(chapter["items"]) == 1
        item = chapter["items"][0]
        assert item["item_type"] == ITEM_MATERIAL
        assert item["material_id"] == ids["material_id"]
        assert item["locked"] is False, "解鎖判定屬 ET-5b，本 issue 恆為 False"
        assert item["completed"] is False

    async def test_倍速依參數限縮(self, client, db) -> None:
        """`ET_VIDEO_PLAYBACK_MAX_RATE` seed 值為 2 → 五段全給。"""
        teacher = await _user(db, "t_learn07", ROLE_TEACHER)
        ids = await _course_with_material(client, db, teacher)

        body = (await client.get(f"{_COURSES}/{ids['course_id']}/learn", headers=_bearer(teacher))).json()

        assert body["playback_rates"] == [0.75, 1.0, 1.25, 1.5, 2.0]

    async def test_已關閉課程仍回全部內容(self, client, db) -> None:
        """#255 SA Q2 裁示 A：關閉 = 讀照舊、寫全停，**不過濾任何內容**。

        依據 Canvas（結課唯讀仍可看全部教材）、Moodle（結束日期預設不限制存取）之
        實際做法——沒有平台依學習進度逐項過濾。
        """
        teacher = await _user(db, "t_learn08", ROLE_TEACHER)
        student = await _user(db, "s_learn08")
        ids = await _course_with_material(client, db, teacher)
        await _enroll(db, student, ids["course_id"])
        await db.execute(update(EtCourse).where(EtCourse.course_id == ids["course_id"]).values(status=COURSE_CLOSED))
        await db.flush()

        body = (await client.get(f"{_COURSES}/{ids['course_id']}/learn", headers=_bearer(student))).json()

        assert body["is_closed"] is True, "前端據此顯示唯讀提示（ET-MSG-ET05-005）"
        assert len(body["chapters"][0]["items"]) == 1, "關閉不得過濾內容"


class TestMaterialContent:
    async def test_教材內容含影片清單且不含落盤路徑(self, client, db) -> None:
        teacher = await _user(db, "t_learn09", ROLE_TEACHER)
        ids = await _course_with_material(client, db, teacher)

        r = await client.get(f"/api/et/materials/{ids['material_id']}/content", headers=_bearer(teacher))

        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["videos"]) == 1
        video = body["videos"][0]
        assert video["file_name"] == "示範影片.mp4"
        assert video["duration_sec"] == 600
        # 落盤路徑是取檔端點要保護的東西，不該從內容端點漏出去
        assert "file_path" not in video

    async def test_項目被刪除後對有權者回內容已刪除(self, client, db) -> None:
        """AC 22 / ET-MSG-ET05-004。"""
        teacher = await _user(db, "t_learn10", ROLE_TEACHER)
        ids = await _course_with_material(client, db, teacher)
        await db.execute(update(EtItem).where(EtItem.item_id == ids["item_id"]).values(deleted=1))
        await db.flush()

        r = await client.get(f"/api/et/materials/{ids['material_id']}/content", headers=_bearer(teacher))

        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_LEARN_003"

    async def test_項目被刪除後對無權者不可分辨(self, client, db) -> None:
        """**「先授權、後回報刪除」的順序**。

        若順序相反（刪除判定在授權之前），無權者會收到 `ET_LEARN_003`——等於被確認
        「這個 material_id 曾經存在」。那正是取檔端點統一回 404 要防的枚舉面。
        """
        teacher = await _user(db, "t_learn11", ROLE_TEACHER)
        outsider = await _user(db, "s_learn11")
        ids = await _course_with_material(client, db, teacher)
        await db.execute(update(EtItem).where(EtItem.item_id == ids["item_id"]).values(deleted=1))
        await db.flush()

        r = await client.get(f"/api/et/materials/{ids['material_id']}/content", headers=_bearer(outsider))

        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_LEARN_001", "無權者不得分辨『已刪除』與『不存在』"


class TestVideoFile:
    async def test_實體檔不存在回404而非500(self, client, db) -> None:
        """`FILE_PATH` 指向不存在的檔案（DB↔磁碟不一致）時，圍籬應回乾淨的 404。

        測資的 `file_path` 是假的——這條驗的正是「授權通過、但檔案不在」這條路徑不會
        讓 `FileResponse` 拋出含落盤路徑的 500。
        """
        teacher = await _user(db, "t_learn12", ROLE_TEACHER)
        ids = await _course_with_material(client, db, teacher)

        ticket = await client.post(f"/api/et/videos/{ids['video_id']}/ticket", headers=_bearer(teacher))
        assert ticket.status_code == 200, ticket.text

        r = await client.get(f"/api/et/videos/{ids['video_id']}/file", params={"t": ticket.json()["ticket"]})

        assert r.status_code == 404, r.text
        assert r.json()["error_code"] == "ET_LEARN_001"

    async def test_查無影片回404(self, client, db) -> None:
        teacher = await _user(db, "t_learn13", ROLE_TEACHER)
        await _course_with_material(client, db, teacher)

        r = await client.post("/api/et/videos/99999999/ticket", headers=_bearer(teacher))

        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_LEARN_001"


class TestLockedItemNotReadable:
    """未解鎖項目的**內容不可讀取**（#424）。

    `progress/service.py` 的模組 docstring 主張「解鎖判定**必須在後端執行**，
    `spec_us5` AC 9 寫的是系統阻擋、不是畫面不給點」。那條原則原本只落實在**寫入**側
    （`mark_item_viewed` / `report_intervals` / 開始作答），讀取側三支端點一律沒有判定
    ——於是在籍學員以 `material_id` 直接打 API 就讀得到尚未解鎖的教材，而唯一擋住它的
    是前端的 `openable` 過濾，正是那段 docstring 說「不可以只靠」的東西。

    ⚠️ **這不是「可以偽造依序完訓」**：寫入側早就擋住了，讀了也不會產生完成紀錄。
    本組測試釘的是「提前看到內容」這一側。
    """

    async def test_未解鎖教材的內容不可讀取(self, client, db) -> None:
        teacher = await _user(db, "t_lock01", ROLE_TEACHER)
        student = await _user(db, "s_lock01")
        ids = await _course_with_material(client, db, teacher)
        second = await _second_chapter_material(client, db, teacher, ids["course_id"])
        await _enroll(db, student, ids["course_id"])

        r = await client.get(f"/api/et/materials/{second['material_id']}/content", headers=_bearer(student))

        # 404 而非 403：與本模組既有慣例一致——以 id 定址的資源不讓回應差異變成 oracle
        assert r.status_code == 404, r.text
        assert r.json()["error_code"] == "ET_LEARN_001"

    async def test_已解鎖的第一章教材照常可讀(self, client, db) -> None:
        """⚠️ 與上一條成對：少了它，「全部擋掉」也會讓上一條通過。"""
        teacher = await _user(db, "t_lock02", ROLE_TEACHER)
        student = await _user(db, "s_lock02")
        ids = await _course_with_material(client, db, teacher)
        await _second_chapter_material(client, db, teacher, ids["course_id"])
        await _enroll(db, student, ids["course_id"])

        r = await client.get(f"/api/et/materials/{ids['material_id']}/content", headers=_bearer(student))

        assert r.status_code == 200, r.text

    async def test_擁有者預覽不受解鎖限制(self, client, db) -> None:
        """🔴 這一條是本次變更最容易做壞的地方。

        `is_item_locked` 只吃 `user_id` 算進度，而**擁有者沒有進度**——天真地掛上去會
        讓教師打不開自己課程第二章之後的教材，而且只在「他自己的課」這個情境出現。

        既有的分流可直接沿用：授權通過後「不在籍」等同「擁有者預覽」
        （`material_content` 的既有註解已載明），預覽本來就不累積進度、不受解鎖限制
        （#255 裁示 Q1）。
        """
        teacher = await _user(db, "t_lock03", ROLE_TEACHER)
        ids = await _course_with_material(client, db, teacher)
        second = await _second_chapter_material(client, db, teacher, ids["course_id"])

        r = await client.get(f"/api/et/materials/{second['material_id']}/content", headers=_bearer(teacher))

        assert r.status_code == 200, "擁有者預覽必須看得到全部內容，否則教師檢查不了自己的課"

    async def test_未解鎖教材不可發播放票(self, client, db) -> None:
        """影片走「發票 → 憑票取檔」，授權只在發票時做一次，故判定要掛在發票端。"""
        teacher = await _user(db, "t_lock04", ROLE_TEACHER)
        student = await _user(db, "s_lock04")
        ids = await _course_with_material(client, db, teacher)
        second = await _second_chapter_material(client, db, teacher, ids["course_id"])
        await _enroll(db, student, ids["course_id"])

        r = await client.post(f"/api/et/videos/{second['video_id']}/ticket", headers=_bearer(student))

        assert r.status_code == 404, r.text
        assert r.json()["error_code"] == "ET_LEARN_001"

    async def test_已解鎖教材仍可發播放票(self, client, db) -> None:
        """與上一條成對，理由同 `test_已解鎖的第一章教材照常可讀`。"""
        teacher = await _user(db, "t_lock05", ROLE_TEACHER)
        student = await _user(db, "s_lock05")
        ids = await _course_with_material(client, db, teacher)
        await _second_chapter_material(client, db, teacher, ids["course_id"])
        await _enroll(db, student, ids["course_id"])

        r = await client.post(f"/api/et/videos/{ids['video_id']}/ticket", headers=_bearer(student))

        assert r.status_code == 200, r.text

    def test_三支讀取端點都掛了判定(self) -> None:
        """🔴 **結構性測試**，因為 `doc_file` 的行為測試沒有鑑別力。

        上面兩組（內容、播放票）以 200 vs 404 驗得出來，但 `doc_file` 不行——
        **「項目鎖定」與「該 doc_id 未被此教材引用」同回 404 `ET_LEARN_001`**
        （見 `test_他人教材之_doc_id_不可搭配自己有權的教材`），兩者外部觀察不到差異。
        那是刻意的設計（不讓回應差異變成 oracle），但代價是行為測試分不出判定有沒有跑。

        ⛔ 寫一條「鎖定時回 404」的整合測試會**看起來是覆蓋、實際不是**——拿掉判定
        它照樣綠。與其留一條假證據，不如誠實改用結構性斷言：**每一支吐內容的端點都
        呼叫了 `_ensure_item_unlocked`**。

        比照 #367 的 `test_conftest_gate_ordering`：行為測試不可能時，改驗結構。
        ⚠️ 它驗的是「有沒有掛」，不是「掛對了沒」——掛對了由上面四條行為測試負責。

        兩個刻意的設計：

        1. **用 `ast` 找真正的呼叫節點，不做字串比對**。`inspect.getsource` 拿到的源碼
           含 docstring 與註解，`"_ensure_item_unlocked" in source` 會被一句提到它的
           註解餵成綠燈——而本 issue 的成因正是「註解宣稱的事情程式沒做」。
        2. **清單是 fail-closed 的**：`EtLearningService` 上每一支公開方法都必須落進
           `要掛` 或 `豁免` 其中之一，否則本測試紅。寫死三個名字的話，第四支讀取端點
           漏掛時它不會紅——而那正是最可能發生、也最需要被擋下的情形。
        """
        import ast
        import inspect
        import textwrap

        from app.et.learning.service import EtLearningService

        要掛 = {"material_content", "ensure_video_accessible", "doc_file"}
        豁免 = {
            "structure": "回的是側欄結構與 locked 旗標本身，不含教材內容",
            "video_file_by_ticket": "憑票放行；授權與解鎖判定都在發票端 ensure_video_accessible",
        }
        公開方法 = {name for name in vars(EtLearningService) if not name.startswith("_")}
        assert 公開方法 == 要掛 | set(豁免), (
            f"`EtLearningService` 的公開方法有增減：{公開方法 ^ (要掛 | set(豁免))}。"
            "請把它加進「要掛」或「豁免」（附理由）——新端點若吐得出教材內容卻沒掛判定，"
            "未解鎖的內容就又讀得到了（#424）。"
        )

        for name in sorted(要掛):
            tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(EtLearningService, name))))
            呼叫了 = any(
                isinstance(node.func, ast.Attribute) and node.func.attr == "_ensure_item_unlocked"
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
            )
            assert 呼叫了, f"{name} 未掛解鎖判定——未解鎖的內容會讀得到（#424）"


class TestLockedItemStillReadableWhenItShouldBe:
    """#424 的**反向**驗收：補上判定後，原本讀得到的三種情形仍須讀得到。

    issue 的「⛔ 不要在沒有裁示的情況下直接掛上判定」列了三條代價，三條的症狀都是
    「學員 / 教師突然打不開本來看得到的東西」，而且**只在特定狀態下出現**——平常跑
    一遍看不出來，要等有人回頭複習、或課程關閉之後才炸。故三條各釘一次：

    1. 課程關閉後的唯讀回看（#288 AC 9/10）→ `test_課程關閉後仍讀得到已學過的教材`
    2. 教師預覽（#255 裁示 Q1）→ 已由 `TestLockedItemNotReadable.test_擁有者預覽不受解鎖限制` 涵蓋
    3. 已完成項目永不鎖定 → `test_已完成的項目被排到未完成項目之後仍可讀`

    ⚠️ 這幾條不是在測 `is_item_locked`（那有自己的 unit 測試），而是在測**呼叫端有沒有
    把它接歪**——例如把「不在籍」當成「無權」而擋掉擁有者，或在關閉課程的路徑上提早
    回絕。接歪的表現都是綠燈的 `is_item_locked` 配上打不開的畫面。
    """

    async def test_完成第一章後第二章的教材變成可讀(self, client, db) -> None:
        """解鎖是會**前進**的——擋下未解鎖不能連帶擋死已解鎖的後續章節。

        與 `TestLockedItemNotReadable.test_未解鎖教材的內容不可讀取` 成對：兩條走同一組
        helper 造出同一個狀態，那條驗「完成前 404」、本條驗「完成後 200」。少了本條，
        一個「一律 404」的實作也會讓那條綠。

        ⛔ **不要把「完成前應為 404」加回本條當前置斷言**。整合測試裡一個預期失敗的
        請求會連帶回滾本測試建立的前置資料，後續的上報就會對著空的課程打、回 404——
        症狀看起來像解鎖判定壞了，實際是測試自己把資料清掉了。前後兩態只能分兩條測。
        """
        teacher = await _user(db, "t_lock06", ROLE_TEACHER)
        student = await _user(db, "s_lock06")
        ids = await _course_with_material(client, db, teacher)
        second = await _second_chapter_material(client, db, teacher, ids["course_id"])
        await _enroll(db, student, ids["course_id"])

        await _complete_material(client, student, video_id=ids["video_id"], item_id=ids["item_id"], duration_sec=600)

        after = await client.get(f"/api/et/materials/{second['material_id']}/content", headers=_bearer(student))
        assert after.status_code == 200, after.text

    async def test_已完成的項目被排到未完成項目之後仍可讀(self, client, db) -> None:
        """教師事後在前面插入項目，**不得把學員已學過的內容鎖回去**。

        `is_item_locked` 的「已完成者永不鎖定」捷徑正是為這件事存在。順序規則本身會說
        「你前面有一項沒完成 ⇒ 你被鎖」，若讀取端只問順序不問完成，學員昨天看完的教材
        今天會打不開——而他什麼都沒做錯，教師也不知道自己做了什麼。
        """
        teacher = await _user(db, "t_lock07", ROLE_TEACHER)
        student = await _user(db, "s_lock07")
        ids = await _course_with_material(client, db, teacher)
        await _enroll(db, student, ids["course_id"])
        await _complete_material(client, student, video_id=ids["video_id"], item_id=ids["item_id"], duration_sec=600)

        # 教師在同一章插入一個新項目，並把它排到已完成項目之前。
        inserted = await client.post(
            f"/api/et/chapters/{ids['chapter_id']}/items",
            json={"item_type": ITEM_MATERIAL},
            headers=_bearer(teacher),
        )
        assert inserted.status_code == 201, inserted.text
        await db.execute(update(EtItem).where(EtItem.item_id == inserted.json()["item_id"]).values(sort_order=0))
        await db.flush()

        r = await client.get(f"/api/et/materials/{ids['material_id']}/content", headers=_bearer(student))

        assert r.status_code == 200, "已完成的項目不得因為前面被插入新項目而變得讀不到"

    async def test_課程關閉後仍讀得到已學過的教材(self, client, db) -> None:
        """#288 AC 9/10：關閉後轉唯讀，**回看**不受影響。

        關閉會擋掉寫入（`report_intervals` 回 409），所以這條要先完成、後關閉——順序反了
        會變成在測「關閉擋寫入」，而那是另一條測試的事。
        """
        teacher = await _user(db, "t_lock08", ROLE_TEACHER)
        student = await _user(db, "s_lock08")
        ids = await _course_with_material(client, db, teacher)
        await _enroll(db, student, ids["course_id"])
        await _complete_material(client, student, video_id=ids["video_id"], item_id=ids["item_id"], duration_sec=600)
        await db.execute(update(EtCourse).where(EtCourse.course_id == ids["course_id"]).values(status=COURSE_CLOSED))
        await db.flush()

        r = await client.get(f"/api/et/materials/{ids['material_id']}/content", headers=_bearer(student))

        assert r.status_code == 200, r.text


class TestVideoTicketFlow:
    """播放票流程（#255）——`<video src>` 送不出 Authorization header 的解法。"""

    async def test_無票不可取檔(self, client, db) -> None:
        """取檔端點掛在**沒有 router-level 認證**的 media_router 上，故這條特別重要：
        票是它唯一的門。"""
        teacher = await _user(db, "t_learn14", ROLE_TEACHER)
        ids = await _course_with_material(client, db, teacher)

        r = await client.get(f"/api/et/videos/{ids['video_id']}/file")

        assert r.status_code == 422, "缺少必填的 t 參數"

    async def test_偽造之票不可取檔(self, client, db) -> None:
        teacher = await _user(db, "t_learn15", ROLE_TEACHER)
        ids = await _course_with_material(client, db, teacher)

        r = await client.get(f"/api/et/videos/{ids['video_id']}/file", params={"t": "not-a-real-ticket"})

        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_LEARN_001"

    async def test_在籍學員可取票(self, client, db) -> None:
        teacher = await _user(db, "t_learn16", ROLE_TEACHER)
        student = await _user(db, "s_learn16")
        ids = await _course_with_material(client, db, teacher)
        await _enroll(db, student, ids["course_id"])

        r = await client.post(f"/api/et/videos/{ids['video_id']}/ticket", headers=_bearer(student))

        assert r.status_code == 200, r.text
        assert r.json()["expires_in"] == TICKET_TTL_SECONDS
        assert r.json()["ticket"]
