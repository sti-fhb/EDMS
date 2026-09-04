"""ET05 學習進度整合測試（US5 / #274）。

覆蓋率的四條核心規則（聯集去重、倍速、跳躍、normalize 不改變結果）已於
`tests/unit/et/test_progress_rules.py` 以**純函式**驗完。此處只驗**需要真 DB 才驗得了**
的事：

1. 區段真的落到 `ET_PROGRESS_INTERVAL`，且 normalize 真的減少列數
2. 覆蓋率回寫 → 項目完成 → **下一章解鎖**這條鏈接得起來
3. 兩條 #255 裁示的執行（關閉擋寫 / 擁有者預覽靜默）——**這是本 issue 的行為核心**
4. 「上次看到哪一項 + 影片內第幾秒」兩段資訊都取得回來

## 為何 setup 之後要 `commit()`

`client` fixture 的 `get_db` override 對**任何例外**（含 `AppError`）rollback。預期失敗的
測試若把 setup 留在未 commit 的狀態，那次失敗會把使用者 / 課程一起清掉，後續請求變成
401——一個看起來像「認證壞了」的假根因。測試 session 採 savepoint 隔離，commit 是安全的
（見 `tests/integration/conftest.py` 之 `db` fixture）。
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

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
from app.et.material.models import EtMaterialVideo
from app.et.progress.models import EtEnrollment, EtProgressInterval
from app.et.roles.models import EtUserRole

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"

#: 測試影片長度。600 秒讓 80% 門檻落在好算的 480 秒上。
_DURATION = 600


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


async def _chapter_with_item(client, db, teacher: str, course_id: int, *, name: str, with_video: bool) -> dict:
    """一章一項目；`with_video=False` 用於「純文件 / 說明文字」的開啟即完成路徑。

    影片直接寫 DB（不走上傳端點）：上傳需要真實檔案與 ffprobe，而本檔驗的是進度累積。
    """
    ch = await client.post(f"{_COURSES}/{course_id}/chapters", json={"chapter_name": name}, headers=_bearer(teacher))
    assert ch.status_code == 201, ch.text
    chapter_id = ch.json()["chapter_id"]

    item = await client.post(
        f"/api/et/chapters/{chapter_id}/items", json={"item_type": ITEM_MATERIAL}, headers=_bearer(teacher)
    )
    assert item.status_code == 201, item.text
    result = {
        "chapter_id": chapter_id,
        "item_id": item.json()["item_id"],
        "material_id": item.json()["material_id"],
        "video_id": None,
    }
    if with_video:
        video = EtMaterialVideo(
            material_id=result["material_id"],
            file_path="dummy/not-a-real-file.mp4",
            file_name="示範影片.mp4",
            duration_sec=_DURATION,
            file_size_bytes=1024,
            sort_order=1,
            created_user=teacher,
            created_date=utcnow(),
            deleted=0,
        )
        db.add(video)
        await db.flush()
        result["video_id"] = video.video_id
    return result


async def _published_course(client, db, teacher: str, *, chapters: list[bool], code: str) -> dict:
    """建立已發布課程；`chapters` 逐章指定「該章的項目是否含影片」。"""
    created = await client.post(_COURSES, json={"course_name": "採血作業教育"}, headers=_bearer(teacher))
    assert created.status_code == 201, created.text
    course_id = created.json()["course_id"]

    built = [
        await _chapter_with_item(client, db, teacher, course_id, name=f"第 {i + 1} 章", with_video=with_video)
        for i, with_video in enumerate(chapters)
    ]
    await db.execute(
        update(EtCourse)
        .where(EtCourse.course_id == course_id)
        .values(
            status=COURSE_PUBLISHED,
            invitation_code=code,
            # `open_start_at` 為 NULL 的已發布課程對學員**完全不可見**
            # （`publish_rules.is_visible_to_student` 對空值取較安全的那一側），
            # 於是「我的課程」會是空清單。設一個已到的起始時間。
            open_start_at=utcnow() - timedelta(hours=1),
        )
    )
    await db.flush()
    return {"course_id": course_id, "chapters": built}


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


async def _interval_count(db, user_id: str, video_id: int) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(EtProgressInterval)
        .where(EtProgressInterval.user_id == user_id, EtProgressInterval.video_id == video_id)
    )


def _report(video_id: int) -> str:
    return f"/api/et/videos/{video_id}/intervals"


def _items_by_id(structure: dict) -> dict[int, dict]:
    return {item["item_id"]: item for ch in structure["chapters"] for item in ch["items"]}


class TestIntervalWrite:
    """區段寫入與 normalize——只有真 DB 驗得了「列數」這件事。"""

    async def test_上報區段寫入_interval(self, client, db) -> None:
        teacher = await _user(db, "t_prog01", ROLE_TEACHER)
        student = await _user(db, "s_prog01")
        course = await _published_course(client, db, teacher, chapters=[True], code="31000001")
        await _enroll(db, student, course["course_id"])
        video_id = course["chapters"][0]["video_id"]

        r = await client.post(
            _report(video_id),
            json={"segments": [{"start_sec": 0, "end_sec": 120}], "last_position_sec": 120},
            headers=_bearer(student),
        )

        assert r.status_code == 200, r.text
        assert r.json()["coverage_pct"] == 20  # 120 / 600
        assert await _interval_count(db, student, video_id) == 1

    async def test_normalize_合併重疊區段且不改變覆蓋率(self, client, db) -> None:
        """AC 2 / AC 4：合併後列數減少，但覆蓋率一模一樣。

        `[0,300]` 與 `[150,450]` 的 `SUM` 為 600（= 100%），**聯集為 450（= 75%）**。
        這條同時釘住「normalize 不改變結果」與「重複觀看不加成」在真實寫入路徑上成立。
        """
        teacher = await _user(db, "t_prog02", ROLE_TEACHER)
        student = await _user(db, "s_prog02")
        course = await _published_course(client, db, teacher, chapters=[True], code="31000002")
        await _enroll(db, student, course["course_id"])
        video_id = course["chapters"][0]["video_id"]
        h = _bearer(student)

        first = await client.post(_report(video_id), json={"segments": [{"start_sec": 0, "end_sec": 300}]}, headers=h)
        second = await client.post(
            _report(video_id), json={"segments": [{"start_sec": 150, "end_sec": 450}]}, headers=h
        )
        assert await _interval_count(db, student, video_id) == 2
        before = second.json()["coverage_pct"]

        r = await client.post(f"/api/et/videos/{video_id}/normalize", headers=h)

        assert r.status_code == 200, r.text
        assert first.json()["coverage_pct"] == 50
        assert before == 75, "聯集 450 / 600；若得到 100 表示改用了 SUM"
        assert r.json()["coverage_pct"] == before, "normalize 是儲存壓縮，不得改變覆蓋率"
        assert await _interval_count(db, student, video_id) == 1

    async def test_異常離開未_normalize_覆蓋率仍正確(self, client, db) -> None:
        """AC 3：強制關閉 / 斷網沒跑到 normalize，重疊區段留在表裡。

        覆蓋率一律先聯集再算，所以**沒有補做也已經是對的**——這條驗的正是「不需要靠
        normalize 有沒有跑成功」。
        """
        teacher = await _user(db, "t_prog03", ROLE_TEACHER)
        student = await _user(db, "s_prog03")
        course = await _published_course(client, db, teacher, chapters=[True], code="31000003")
        await _enroll(db, student, course["course_id"])
        chapter = course["chapters"][0]
        h = _bearer(student)

        await client.post(
            _report(chapter["video_id"]), json={"segments": [{"start_sec": 0, "end_sec": 300}]}, headers=h
        )
        await client.post(
            _report(chapter["video_id"]), json={"segments": [{"start_sec": 150, "end_sec": 450}]}, headers=h
        )
        # 此處刻意**不呼叫 normalize**，模擬瀏覽器當掉
        r = await client.get(f"/api/et/materials/{chapter['material_id']}/content", headers=h)

        assert r.status_code == 200, r.text
        assert r.json()["videos"][0]["coverage_pct"] == 75
        assert await _interval_count(db, student, chapter["video_id"]) == 2, "未 normalize，列數應仍為 2"


class TestUnlock:
    """覆蓋率 → 項目完成 → 下一章解鎖（AC 5 / AC 6）。"""

    async def test_達八十解鎖下一章(self, client, db) -> None:
        teacher = await _user(db, "t_prog04", ROLE_TEACHER)
        student = await _user(db, "s_prog04")
        course = await _published_course(client, db, teacher, chapters=[True, True], code="31000004")
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)

        r = await client.post(
            _report(course["chapters"][0]["video_id"]),
            json={"segments": [{"start_sec": 0, "end_sec": 480}]},
            headers=h,
        )
        assert r.json()["coverage_pct"] == 80

        structure = await client.get(f"{_COURSES}/{course['course_id']}/learn", headers=h)
        items = _items_by_id(structure.json())
        assert items[course["chapters"][0]["item_id"]]["completed"] is True
        assert items[course["chapters"][1]["item_id"]]["locked"] is False

    async def test_未達八十下一章仍鎖定(self, client, db) -> None:
        """AC 6：覆蓋率 79% 也不放行——門檻是 80，不是「差不多」。"""
        teacher = await _user(db, "t_prog05", ROLE_TEACHER)
        student = await _user(db, "s_prog05")
        course = await _published_course(client, db, teacher, chapters=[True, True], code="31000005")
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)

        r = await client.post(
            _report(course["chapters"][0]["video_id"]),
            json={"segments": [{"start_sec": 0, "end_sec": 474}]},
            headers=h,
        )
        assert r.json()["coverage_pct"] == 79

        structure = await client.get(f"{_COURSES}/{course['course_id']}/learn", headers=h)
        items = _items_by_id(structure.json())
        assert items[course["chapters"][0]["item_id"]]["completed"] is False
        assert items[course["chapters"][1]["item_id"]]["locked"] is True


class TestItemViewed:
    """純文件 / 說明文字項目的「開啟即完成」與定位（AC 10 / AC 11）。"""

    async def test_無影片教材開啟即完成且解鎖下一章(self, client, db) -> None:
        teacher = await _user(db, "t_prog06", ROLE_TEACHER)
        student = await _user(db, "s_prog06")
        course = await _published_course(client, db, teacher, chapters=[False, True], code="31000006")
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)

        r = await client.post(f"/api/et/items/{course['chapters'][0]['item_id']}/viewed", headers=h)

        assert r.status_code == 200, r.text
        assert r.json()["completed"] is True
        structure = await client.get(f"{_COURSES}/{course['course_id']}/learn", headers=h)
        assert _items_by_id(structure.json())[course["chapters"][1]["item_id"]]["locked"] is False

    async def test_含影片教材不因開啟而完成(self, client, db) -> None:
        """否則學員點一下就跳過了 80% 的要求——這是最容易被寫成後門的一條。"""
        teacher = await _user(db, "t_prog07", ROLE_TEACHER)
        student = await _user(db, "s_prog07")
        course = await _published_course(client, db, teacher, chapters=[True, True], code="31000007")
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)

        r = await client.post(f"/api/et/items/{course['chapters'][0]['item_id']}/viewed", headers=h)

        assert r.status_code == 200, r.text
        assert r.json()["completed"] is False
        structure = await client.get(f"{_COURSES}/{course['course_id']}/learn", headers=h)
        assert _items_by_id(structure.json())[course["chapters"][1]["item_id"]]["locked"] is True

    async def test_重新進入定位至上次項目(self, client, db) -> None:
        """AC 11 的前半：上次看到**哪一項**（SA Q1 裁示 B 之 `LAST_ITEM_ID`）。"""
        teacher = await _user(db, "t_prog08", ROLE_TEACHER)
        student = await _user(db, "s_prog08")
        course = await _published_course(client, db, teacher, chapters=[False, False], code="31000008")
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)

        fresh = await client.get(f"{_COURSES}/{course['course_id']}/learn", headers=h)
        assert fresh.json()["last_item_id"] is None, "還沒看過任何項目 → 前端定位第 1 章第 1 項"

        # 依序：先完成第 1 章（純文件、開啟即完成），第 2 章才解鎖
        await client.post(f"/api/et/items/{course['chapters'][0]['item_id']}/viewed", headers=h)
        second = await client.post(f"/api/et/items/{course['chapters'][1]['item_id']}/viewed", headers=h)
        assert second.status_code == 200, second.text
        again = await client.get(f"{_COURSES}/{course['course_id']}/learn", headers=h)

        assert again.json()["last_item_id"] == course["chapters"][1]["item_id"]

    async def test_回傳上次播放秒數(self, client, db) -> None:
        """AC 11 的後半：該項若為影片，再跳至影片內的第幾秒。"""
        teacher = await _user(db, "t_prog09", ROLE_TEACHER)
        student = await _user(db, "s_prog09")
        course = await _published_course(client, db, teacher, chapters=[True], code="31000009")
        await _enroll(db, student, course["course_id"])
        chapter = course["chapters"][0]
        h = _bearer(student)

        await client.post(
            _report(chapter["video_id"]),
            json={"segments": [{"start_sec": 0, "end_sec": 120}], "last_position_sec": 118},
            headers=h,
        )
        # normalize 不帶位置——**不可把續看點清掉**
        await client.post(f"/api/et/videos/{chapter['video_id']}/normalize", headers=h)
        r = await client.get(f"/api/et/materials/{chapter['material_id']}/content", headers=h)

        assert r.json()["videos"][0]["last_position_sec"] == 118


class TestMyCoursesProgress:
    """「我的課程」卡片的 `progress_pct`（#274 填實 #247 留下的接點）。"""

    async def test_完成一半項目時卡片顯示五十(self, client, db) -> None:
        """完成項目數 ÷ 總項目數，與 ET05 側欄的課程進度條同一定義。"""
        teacher = await _user(db, "t_prog20", ROLE_TEACHER)
        student = await _user(db, "s_prog20")
        course = await _published_course(client, db, teacher, chapters=[False, False], code="31000020")
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)

        before = await client.get("/api/et/my-courses", headers=h)
        assert before.json()["courses"][0]["progress_pct"] == 0

        # 兩個純文件項目完成其一
        await client.post(f"/api/et/items/{course['chapters'][0]['item_id']}/viewed", headers=h)
        after = await client.get("/api/et/my-courses", headers=h)

        assert after.json()["courses"][0]["progress_pct"] == 50

    async def test_已完成項目被刪除後不計入分子(self, client, db) -> None:
        """**分子必須一起濾掉軟刪除的項目**。

        `ET_PROGRESS` 的列在項目被刪除後仍然留著（那是學習歷史，刻意不連帶刪）。分母
        縮小、分子沒縮小的話，教師刪掉一章就會讓學員的進度虛高。

        ⚠️ 這裡刻意用「3 項完成 2 項，再刪掉其中一個**已完成**的」而不是「刪到超過
        100%」——後者會被 `min(100, ...)` 的上限吸收掉，測試照樣綠，什麼都沒驗到。
        本組合下有濾是 50%、沒濾是 100%，兩者分得開。
        """
        teacher = await _user(db, "t_prog21", ROLE_TEACHER)
        student = await _user(db, "s_prog21")
        course = await _published_course(client, db, teacher, chapters=[False, False, False], code="31000021")
        await _enroll(db, student, course["course_id"])
        h = _bearer(student)

        # 依序完成前兩項（純文件，開啟即完成）
        for chapter in course["chapters"][:2]:
            await client.post(f"/api/et/items/{chapter['item_id']}/viewed", headers=h)
        # 教師刪掉第 1 章的項目——學員對它的完成紀錄仍在
        await db.execute(update(EtItem).where(EtItem.item_id == course["chapters"][0]["item_id"]).values(deleted=1))
        await db.flush()

        r = await client.get("/api/et/my-courses", headers=h)

        # 剩 2 項、其中 1 項已完成 → 50%（沒濾掉已刪除的分子會變成 100%）
        assert r.json()["courses"][0]["progress_pct"] == 50


class TestWriteGuards:
    """兩條 #255 裁示在此第一次真正被執行——本 issue 的行為核心。"""

    async def test_關閉課程上報被拒(self, client, db) -> None:
        """#255 裁示 Q2：關閉 = 讀照舊、寫全停（AC 12）。"""
        teacher = await _user(db, "t_prog10", ROLE_TEACHER)
        student = await _user(db, "s_prog10")
        course = await _published_course(client, db, teacher, chapters=[True], code="31000010")
        await _enroll(db, student, course["course_id"])
        video_id = course["chapters"][0]["video_id"]
        await db.execute(update(EtCourse).where(EtCourse.course_id == course["course_id"]).values(status=COURSE_CLOSED))
        # 預期失敗 → 先 commit，否則 rollback 會把使用者一起清掉、下一個請求變成 401
        await db.commit()

        r = await client.post(
            _report(video_id), json={"segments": [{"start_sec": 0, "end_sec": 120}]}, headers=_bearer(student)
        )

        assert r.status_code == 409, r.text
        assert r.json()["error_code"] == "ET_PROGRESS_001"
        assert await _interval_count(db, student, video_id) == 0

    async def test_關閉課程仍可讀取內容(self, client, db) -> None:
        """同一條裁示的另一半——擋的是寫入，不是閱讀。"""
        teacher = await _user(db, "t_prog11", ROLE_TEACHER)
        student = await _user(db, "s_prog11")
        course = await _published_course(client, db, teacher, chapters=[True], code="31000011")
        await _enroll(db, student, course["course_id"])
        await db.execute(update(EtCourse).where(EtCourse.course_id == course["course_id"]).values(status=COURSE_CLOSED))
        await db.flush()

        r = await client.get(
            f"/api/et/materials/{course['chapters'][0]['material_id']}/content", headers=_bearer(student)
        )

        assert r.status_code == 200, r.text
        assert len(r.json()["videos"]) == 1

    async def test_擁有者預覽不累積進度(self, client, db) -> None:
        """#255 裁示 Q1（AC 13）：回 **200 但不寫入**。

        不回錯誤——他沒做錯事，跳一個錯誤只會讓他以為預覽壞了。
        """
        teacher = await _user(db, "t_prog12", ROLE_TEACHER)
        course = await _published_course(client, db, teacher, chapters=[True], code="31000012")
        video_id = course["chapters"][0]["video_id"]

        r = await client.post(
            _report(video_id), json={"segments": [{"start_sec": 0, "end_sec": 600}]}, headers=_bearer(teacher)
        )

        assert r.status_code == 200, r.text
        assert r.json()["coverage_pct"] == 0
        assert await _interval_count(db, teacher, video_id) == 0

    async def test_擁有者預覽已關閉的課程仍是靜默而非四零九(self, client, db) -> None:
        """**守門 2 必須排在守門 3 之前**——這條釘住那個順序。

        教師預覽一門已關閉的課程時，該給他「什麼都沒發生」而不是「此課程已關閉」：
        後者暗示他做錯了什麼，但他只是在看自己的課。順序若被調換，其餘測試都不會發現
        （`test_關閉課程上報被拒` 用的是學員、`test_擁有者預覽不累積進度` 用的是未關閉課程）。
        """
        teacher = await _user(db, "t_prog19", ROLE_TEACHER)
        course = await _published_course(client, db, teacher, chapters=[True], code="31000019")
        video_id = course["chapters"][0]["video_id"]
        await db.execute(update(EtCourse).where(EtCourse.course_id == course["course_id"]).values(status=COURSE_CLOSED))
        await db.flush()

        r = await client.post(
            _report(video_id), json={"segments": [{"start_sec": 0, "end_sec": 600}]}, headers=_bearer(teacher)
        )

        assert r.status_code == 200, r.text
        assert r.json()["coverage_pct"] == 0
        assert await _interval_count(db, teacher, video_id) == 0

    async def test_擁有者預覽不套用鎖定(self, client, db) -> None:
        """預覽的用途是「確認每一段內容在學員視角長什麼樣」。

        照學員規則算會把教師鎖在第 1 章第 1 項——他沒有進度可累積，於是永遠解不開，
        預覽就失去意義。
        """
        teacher = await _user(db, "t_prog13", ROLE_TEACHER)
        course = await _published_course(client, db, teacher, chapters=[True, True], code="31000013")

        r = await client.get(f"{_COURSES}/{course['course_id']}/learn", headers=_bearer(teacher))

        assert r.json()["is_owner"] is True
        assert all(not item["locked"] for item in _items_by_id(r.json()).values())

    async def test_未解鎖項目之_viewed_被擋(self, client, db) -> None:
        """**H1 迴歸**：解鎖判定必須在後端執行，不能只靠前端不給點。

        `spec_us5` AC 9 寫的是「系統阻擋」。只靠前端判 `locked`，任何人都能直接
        `POST /items/{第 2 章的文件項目}/viewed` 拿到 `completed=true`——而
        `locked_item_ids` 的「已完成永不鎖定」會讓那一項自我解鎖、第 3 章跟著開，
        第 1 章一項都不必碰。對教育訓練系統而言那等於可以偽造依序完訓的紀錄。
        """
        teacher = await _user(db, "t_prog16", ROLE_TEACHER)
        student = await _user(db, "s_prog16")
        course = await _published_course(client, db, teacher, chapters=[True, False], code="31000016")
        await _enroll(db, student, course["course_id"])
        await db.commit()

        # 第 1 章的影片一秒都沒看 → 第 2 章鎖定
        r = await client.post(f"/api/et/items/{course['chapters'][1]['item_id']}/viewed", headers=_bearer(student))

        # **404 而非 403**：與其餘以 id 定址的端點一致，不讓回應差異變成存在性 oracle
        assert r.status_code == 404, r.text
        assert r.json()["error_code"] == "ET_LEARN_001"

    async def test_未解鎖影片之區段上報被擋(self, client, db) -> None:
        """同上，另一條能產生進度的路徑——擋了 `viewed` 卻放行 `intervals` 等於沒擋。"""
        teacher = await _user(db, "t_prog17", ROLE_TEACHER)
        student = await _user(db, "s_prog17")
        course = await _published_course(client, db, teacher, chapters=[True, True], code="31000017")
        await _enroll(db, student, course["course_id"])
        locked_video = course["chapters"][1]["video_id"]
        await db.commit()

        r = await client.post(
            _report(locked_video), json={"segments": [{"start_sec": 0, "end_sec": 600}]}, headers=_bearer(student)
        )

        assert r.status_code == 404, r.text
        assert await _interval_count(db, student, locked_video) == 0

    async def test_上次播放秒數超過影片長度時被裁切(self, client, db) -> None:
        """`LAST_POSITION_SEC` 是 INT4 且**不經 `clamp_segment`**。

        不裁切的話上報一個 999 億會讓 asyncpg 在寫入時炸成 500，連同該次的區段一起回滾
        ——任何在籍學員都能重複觸發的可用性擾動。
        """
        teacher = await _user(db, "t_prog18", ROLE_TEACHER)
        student = await _user(db, "s_prog18")
        course = await _published_course(client, db, teacher, chapters=[True], code="31000018")
        await _enroll(db, student, course["course_id"])
        chapter = course["chapters"][0]

        r = await client.post(
            _report(chapter["video_id"]),
            json={"segments": [{"start_sec": 0, "end_sec": 120}], "last_position_sec": 99_999_999},
            headers=_bearer(student),
        )

        assert r.status_code == 200, r.text
        assert r.json()["last_position_sec"] == _DURATION

    async def test_非在籍者上報回四零四(self, client, db) -> None:
        """以 id 定址的資源一律 404——回 403 等於確認「這個 video_id 存在」。"""
        teacher = await _user(db, "t_prog14", ROLE_TEACHER)
        outsider = await _user(db, "s_prog14")
        course = await _published_course(client, db, teacher, chapters=[True], code="31000014")
        video_id = course["chapters"][0]["video_id"]
        await db.commit()

        r = await client.post(
            _report(video_id), json={"segments": [{"start_sec": 0, "end_sec": 120}]}, headers=_bearer(outsider)
        )

        assert r.status_code == 404, r.text
        assert r.json()["error_code"] == "ET_LEARN_001"

    async def test_全部區段超出影片長度回四二二(self, client, db) -> None:
        """單段超界會被裁切吸收，**全部**超界則代表前端上報到錯的影片或時間軸算錯。

        靜默接受會讓那種 bug 表現成「怎麼看都沒有進度」——沒有任何訊號的故障。
        """
        teacher = await _user(db, "t_prog15", ROLE_TEACHER)
        student = await _user(db, "s_prog15")
        course = await _published_course(client, db, teacher, chapters=[True], code="31000015")
        await _enroll(db, student, course["course_id"])
        video_id = course["chapters"][0]["video_id"]
        await db.commit()

        r = await client.post(
            _report(video_id),
            json={"segments": [{"start_sec": 900, "end_sec": 1000}]},
            headers=_bearer(student),
        )

        assert r.status_code == 422, r.text
        assert r.json()["error_code"] == "ET_PROGRESS_002"
