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
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.material.models import EtMaterial, EtMaterialVideo
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

    ch = await client.post(f"{_COURSES}/{course_id}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(teacher))
    assert ch.status_code == 201, ch.text
    chapter_id = ch.json()["chapter_id"]

    item = await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": ITEM_MATERIAL},
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
        update(EtCourse).where(EtCourse.course_id == course_id).values(status=COURSE_PUBLISHED, invitation_code="30000001")
    )
    await db.flush()
    return {
        "course_id": course_id,
        "chapter_id": chapter_id,
        "item_id": item_id,
        "material_id": material_id,
        "video_id": video.video_id,
    }


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
        r_video = await client.get(f"/api/et/videos/{ids['video_id']}/file", headers=h)
        r_doc = await client.get(f"/api/et/materials/{ids['material_id']}/docs/DM-SOP-000001/file", headers=h)

        # 課程層：403 + 可行動的訊息（他可能正要加入）
        assert r_struct.status_code == 403
        assert r_struct.json()["error_code"] == "ET_LEARN_002"
        # 以 id 定址的資源：一律 404，不可分辨「不存在」與「無權」
        for label, r in [("content", r_content), ("video", r_video), ("doc", r_doc)]:
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
        """#247 SA Q1 裁示 C 的延伸——不在籍即不可存取。"""
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
        assert r.json()["error_code"] == "ET_LEARN_002"

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

        r = await client.get(f"/api/et/videos/{ids['video_id']}/file", headers=_bearer(teacher))

        assert r.status_code == 404, r.text
        assert r.json()["error_code"] == "ET_LEARN_001"

    async def test_查無影片回404(self, client, db) -> None:
        teacher = await _user(db, "t_learn13", ROLE_TEACHER)
        await _course_with_material(client, db, teacher)

        r = await client.get("/api/et/videos/99999999/file", headers=_bearer(teacher))

        assert r.status_code == 404
        assert r.json()["error_code"] == "ET_LEARN_001"
