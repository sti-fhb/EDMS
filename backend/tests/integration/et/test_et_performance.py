"""效能驗證（ET-14 / #341 T122 / AC 7、AC 8）。

## 量測口徑（SA 裁示 Q3 = A，2026-09-16）

量的是**後端回應時間**，不含前端渲染。報告與本檔的斷言都以此為準。

⚠️ **這使 AC 7 的字面意義與實測涵蓋範圍不同，必須寫清楚**：

- **AC 7 的字面**：「大量學員（≥ 500 人）加入課程之**列表載入**時間 < 2 秒」
- **實際量到的**：母體 **500 人**時，`GET /courses/{id}/students` **第一頁（100 筆）**
  的後端回應時間

兩處落差：

1. **不含前端渲染。** 後端 200ms 的回應，前端渲染 500 列仍可能超過 2 秒。
   「使用者 2 秒內看得到」**不是**本檔證明的事——那需要 E2E 基礎建設（#57，未開工）
2. **該端點有後端分頁**（`limit` ≤ 100）。所以「500 人的列表」在實作上不存在，
   實際量的是「母體 500 人時第一頁的回應」。這反而是**更有意義**的量測：
   母體大小影響的是聚合查詢的成本，而那正是會隨人數劣化的部分

## 為什麼掛 `slow` marker

建 500 名學員 + 其作答資料要花數十秒，放進每次 CI 會讓所有人多等。
`pyproject.toml` 的 `addopts` 預設帶 `-m "not slow"`，需要時以 `-m slow` 單獨跑。

**代價要講明**：預設不跑代表**效能劣化不會被 CI 擋下**。本檔的定位是「上線前的一次性
驗證 + 日後懷疑變慢時的量測工具」，不是持續的效能守門員。真正的守門需要基準值管理與
穩定的執行環境，不在 ET-14 範圍。

## 門檻的判讀

本機的絕對數字**不可直接外推到 GCP**（機器規格、網路、DB 連線數皆不同）。
斷言用的是一個寬鬆的上限（門檻的數倍），目的是抓「演算法層級的劣化」——例如
N+1 查詢或缺索引造成的全表掃描——而不是微調常數。
"""

import time
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.core.auth import create_access_token
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.constants import (
    COURSE_PUBLISHED,
    ITEM_MATERIAL,
    ROLE_STUDENT,
    ROLE_TEACHER,
    SOURCE_INVITATION_CODE,
)
from app.et.course.models import EtCourse
from app.et.material.models import EtMaterialVideo
from app.et.progress.models import EtEnrollment, EtProgress, EtProgressInterval
from app.et.roles.models import EtUserRole

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_COURSES = "/api/et/courses"

#: AC 7 的母體下限。
_STUDENT_COUNT = 500

#: AC 7 的門檻是 2 秒。本機斷言取其數倍為上限——目的是抓演算法層級的劣化，
#: 不是把某台機器的常數釘死（見檔頭「門檻的判讀」）。
_RESPONSE_BUDGET_SEC = 6.0

#: 一次請求的區段數上限（`progress/schemas.MAX_SEGMENTS_PER_REQUEST`）。
_MAX_SEGMENTS = 200

#: 測試影片長度；需夠長才容納 200 段互相重疊的區段。
_VIDEO_DURATION_SEC = 3600

#: 寫入端自動壓縮的門檻（`progress/service._MAX_INTERVAL_ROWS`）。累積超過此數時
#: `_recompute` 會在寫入路徑上就地合併——寫入成本因此不均勻，見該測試的說明。
_AUTO_COMPACT_ROWS = 500


def _report(label: str, seconds: float, *, extra: str = "") -> None:
    """把量到的數字印出來——效能測試的產出是**數字**，不是綠燈。

    以 `pytest -m slow -s` 取得。只斷言不輸出的話，「還有多少餘裕」這個真正該看的資訊
    就只存在於失敗的那一刻。
    """
    suffix = f" | {extra}" if extra else ""
    print(f"\n[perf] {label}: {seconds * 1000:.0f} ms{suffix}")


async def _measure(client, url: str, headers: dict[str, str], *, runs: int = 3) -> float:
    """量 `url` 的最短回應時間（秒），量測前先暖機一次。

    ⚠️ **暖機是必要的，不是講究**。初版沒暖機，得到「100 人 107 ms、500 人 33 ms、
    倍率 0.3x」——第一次呼叫含連線建立與查詢計畫快取，量到的是暖機成本而非母體規模。
    那條比較因此**通過但什麼都沒證明**。

    取最小值而非平均：我們要的是「這個查詢最快能多快」，離群的慢值來自本機的其他負載，
    不是被測程式的性質。
    """
    await client.get(url, headers=headers)  # 暖機，不計入
    best = float("inf")
    for _ in range(runs):
        started = time.perf_counter()
        r = await client.get(url, headers=headers)
        best = min(best, time.perf_counter() - started)
        assert r.status_code == 200, r.text
    return best


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


async def _teacher(db, user_id: str) -> str:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local",
            pwd_hash=hash_password("Abcd1234"),
            user_name=f"教師{user_id}",
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


async def _course_with_students(client, db, teacher: str, count: int) -> tuple[int, int]:
    """建一門有 `count` 名在籍學員的課程；半數有學習進度。回 `(course_id, item_id)`。

    ⚠️ 學員與進度以 `db.add` 直接建——本檔量的是**讀取**效能，不是寫入路徑的正確性
    （那是 T116 / T117 的事）。走 API 建 500 人會讓準備時間變成數分鐘，且量到的是別的東西。
    """
    created = await client.post(_COURSES, json={"course_name": "大班課程"}, headers=_bearer(teacher))
    assert created.status_code == 201, created.text
    course_id = created.json()["course_id"]

    chapter = await client.post(
        f"{_COURSES}/{course_id}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(teacher)
    )
    item = await client.post(
        f"/api/et/chapters/{chapter.json()['chapter_id']}/items",
        json={"item_type": ITEM_MATERIAL, "title": "教材"},
        headers=_bearer(teacher),
    )
    item_id = item.json()["item_id"]

    now = utcnow()
    for i in range(count):
        uid = f"perf_s{i:04d}"
        db.add(
            DpUser(
                user_id=uid,
                email=f"{uid}@edms.local",
                pwd_hash="x",  # 本檔不登入這些帳號，省去 500 次 bcrypt（每次約 185ms）
                user_name=f"學員{i:04d}",
                status="ACTIVE",
                login_fail_count=0,
                pwd_changed_date=now,
                created_user="admin01",
                created_date=now,
            )
        )
        db.add(
            EtUserRole(
                user_id=uid, role=ROLE_STUDENT, is_active=True, created_user="SYSTEM", created_date=now, deleted=0
            )
        )
        db.add(
            EtEnrollment(
                course_id=course_id,
                user_id=uid,
                join_source=SOURCE_INVITATION_CODE,
                joined_at=now,
                completion_status="NOT_STARTED",
                is_removed=False,
                created_user=uid,
                created_date=now,
                deleted=0,
            )
        )
        if i % 2 == 0:  # 半數有進度——讓即時計算的聚合真的有東西要算
            db.add(
                EtProgress(
                    user_id=uid,
                    course_id=course_id,
                    item_id=item_id,
                    is_completed=True,
                    created_user=uid,
                    created_date=now,
                    deleted=0,
                )
            )
    await db.flush()
    return course_id, item_id


async def test_五百名學員時學員清單第一頁的後端回應時間(client, db) -> None:
    """AC 7（口徑見檔頭）。

    同時驗兩件事——**只驗時間不驗內容會讓一個回空清單的實作輕鬆達標**：

    1. 回應時間在預算內
    2. 回的確實是第一頁 100 筆，且 `meta.total` 等於母體 500
    """
    teacher = await _teacher(db, "t_perf01")
    course_id, _ = await _course_with_students(client, db, teacher, _STUDENT_COUNT)

    started = time.perf_counter()
    r = await client.get(f"{_COURSES}/{course_id}/students", params={"limit": 100}, headers=_bearer(teacher))
    elapsed = time.perf_counter() - started

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["meta"]["total"] == _STUDENT_COUNT, "母體不對，量到的不是 500 人的情境"
    assert len(body["data"]) == 100, "回的不是完整的第一頁"
    _report(
        "500 人母體 / 第一頁 100 筆", elapsed, extra=f"AC 門檻 2000 ms、本機預算 {_RESPONSE_BUDGET_SEC * 1000:.0f} ms"
    )
    assert elapsed < _RESPONSE_BUDGET_SEC, (
        f"第一頁回應耗時 {elapsed:.2f}s，超過本機預算 {_RESPONSE_BUDGET_SEC}s。"
        "AC 7 的門檻是 2 秒；本預算取其數倍，超出通常代表演算法層級的劣化"
        "（N+1 查詢、缺索引的全表掃描），而非機器慢。"
    )


async def test_母體增大時第一頁成本不應等比增加(client, db) -> None:
    """分頁的意義：母體從 100 變成 500，第一頁的成本**不該**跟著變成五倍。

    這條比單純的絕對時間更能抓到劣化——它不受機器規格影響。若 `completion_status` /
    `progress_pct` 的即時計算對**整個母體**做聚合而非只對當頁的 100 人，倍率會直接暴露。

    倍率上限取 3 而非 1：`meta.total` 本來就要數全母體，且聚合查詢有固定成本，
    不可能完全不隨母體成長。
    """
    teacher = await _teacher(db, "t_perf02")
    small_id, _ = await _course_with_students(client, db, teacher, 100)

    small_url = f"{_COURSES}/{small_id}/students?limit=100"
    small_elapsed = await _measure(client, small_url, _bearer(teacher))

    # 第二門課另建 500 人（學員 id 與上一門不重疊，故不共用）
    big_created = await client.post(_COURSES, json={"course_name": "更大班"}, headers=_bearer(teacher))
    big_id = big_created.json()["course_id"]
    now = utcnow()
    for i in range(_STUDENT_COUNT):
        uid = f"perf2_s{i:04d}"
        db.add(
            DpUser(
                user_id=uid,
                email=f"{uid}@edms.local",
                pwd_hash="x",
                user_name=f"學員{i:04d}",
                status="ACTIVE",
                login_fail_count=0,
                pwd_changed_date=now,
                created_user="admin01",
                created_date=now,
            )
        )
        db.add(
            EtEnrollment(
                course_id=big_id,
                user_id=uid,
                join_source=SOURCE_INVITATION_CODE,
                joined_at=now,
                completion_status="NOT_STARTED",
                is_removed=False,
                created_user=uid,
                created_date=now,
                deleted=0,
            )
        )
    await db.flush()

    big_url = f"{_COURSES}/{big_id}/students?limit=100"
    big_elapsed = await _measure(client, big_url, _bearer(teacher))
    verify = await client.get(big_url, headers=_bearer(teacher))
    assert verify.json()["meta"]["total"] == _STUDENT_COUNT

    ratio = big_elapsed / max(small_elapsed, 0.001)
    _report(
        "母體 100 → 500 的第一頁成本", big_elapsed, extra=f"100 人時 {small_elapsed * 1000:.0f} ms、倍率 {ratio:.1f}x"
    )
    assert ratio < 3.0, (
        f"母體 100 → 500（五倍）時第一頁耗時變為 {ratio:.1f} 倍"
        f"（{small_elapsed:.3f}s → {big_elapsed:.3f}s）。"
        "分頁後第一頁的成本不該等比成長；倍率接近 5 代表聚合是對整個母體做的。"
    )


async def test_課程狀態欄位在大班時仍正確(client, db) -> None:
    """效能測試的資料量也是驗正確性的機會——半數學員有進度，聚合結果須反映出來。

    放在本檔而非 tracking 測試：500 人是唯一會讓「聚合寫錯但小樣本看不出來」浮現的規模
    （例如兩個一對多 JOIN 造成的笛卡兒積，在每人 1 筆進度時數字仍然對）。
    """
    teacher = await _teacher(db, "t_perf03")
    course_id, _ = await _course_with_students(client, db, teacher, _STUDENT_COUNT)

    r = await client.get(f"{_COURSES}/{course_id}/students", params={"limit": 100}, headers=_bearer(teacher))
    assert r.status_code == 200, r.text
    rows = r.json()["data"]

    completed = [row for row in rows if row["completion_status"] == "COMPLETED"]
    not_started = [row for row in rows if row["completion_status"] == "NOT_STARTED"]
    assert completed and not_started, "半數有進度，兩種狀態都該出現"
    assert len(completed) + len(not_started) == len(rows), "不該出現第三種狀態"


async def _video_course(client, db, teacher: str) -> dict:
    """建一門已發布、含影片教材的課程。影片直接寫 DB——上傳需要真檔與 ffprobe，
    而本段量的是**區段寫入與合併**，不是上傳。"""
    created = await client.post(_COURSES, json={"course_name": "影片課程"}, headers=_bearer(teacher))
    course_id = created.json()["course_id"]
    chapter = await client.post(
        f"{_COURSES}/{course_id}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(teacher)
    )
    item = await client.post(
        f"/api/et/chapters/{chapter.json()['chapter_id']}/items",
        json={"item_type": ITEM_MATERIAL, "title": "影片教材"},
        headers=_bearer(teacher),
    )
    video = EtMaterialVideo(
        material_id=item.json()["material_id"],
        file_path="dummy/not-a-real-file.mp4",
        file_name="示範影片.mp4",
        duration_sec=_VIDEO_DURATION_SEC,
        file_size_bytes=1024,
        sort_order=1,
        created_user=teacher,
        created_date=utcnow(),
        deleted=0,
    )
    db.add(video)
    await db.flush()
    await db.execute(
        update(EtCourse)
        .where(EtCourse.course_id == course_id)
        .values(status=COURSE_PUBLISHED, open_start_at=utcnow() - timedelta(hours=1))
    )
    await db.flush()
    return {"course_id": course_id, "video_id": video.video_id, "item_id": item.json()["item_id"]}


async def test_影片區段批次寫入與_normalize_的效能(client, db) -> None:
    """AC 8。三個成本來源分開量——混在一起看不出是哪一段慢。

    1. **一般批次寫入**：一次請求最多 200 段（`MAX_SEGMENTS_PER_REQUEST`）
    2. **觸發自動壓縮的那一次寫入**：最壞情況，見下
    3. **`normalize`**：列數越多越慢（讀出全部區段、合併、寫回）

    ## 寫入端有自動壓縮，門檻 `_MAX_INTERVAL_ROWS = 500`

    撰寫本檔時才查到：累積列數超過 500 時，`_recompute` 會在**寫入路徑上**就地合併並
    `replace_intervals`。初版沒考慮它，於是灌三批（600 列）之後列數變成 1，
    normalize 沒東西可壓縮——量到的是空轉。

    這件事對效能的意義很大：**寫入的成本不是均勻的**。多數請求只是 INSERT 200 列，
    但每隔幾次就有一次要把 500+ 列讀出來合併再寫回。那一次才是使用者可能感覺到的卡頓，
    所以本檔把它單獨量出來。

    區段刻意造成**互相重疊**（每段 10 秒、間隔 5 秒）：不相交的區段合併後列數不變，
    壓縮幾乎沒事做，量到的會是最好的情況而非真實情況。
    """
    teacher = await _teacher(db, "t_perf04")
    student = await _teacher(db, "s_perf04")  # 借用 helper；角色不影響本段量測
    course = await _video_course(client, db, teacher)
    db.add(
        EtEnrollment(
            course_id=course["course_id"],
            user_id=student,
            join_source=SOURCE_INVITATION_CODE,
            joined_at=utcnow(),
            completion_status="NOT_STARTED",
            is_removed=False,
            created_user=student,
            created_date=utcnow(),
            deleted=0,
        )
    )
    await db.flush()
    headers = _bearer(student)
    url = f"/api/et/videos/{course['video_id']}/intervals"

    def _batch(offset: int) -> dict:
        """200 段互相重疊一半的區段（每段 10 秒、間隔 5 秒）。"""
        return {
            "segments": [
                {"start_sec": offset + i * 5, "end_sec": min(offset + i * 5 + 10, _VIDEO_DURATION_SEC)}
                for i in range(_MAX_SEGMENTS)
                if offset + i * 5 < _VIDEO_DURATION_SEC
            ]
        }

    async def _post(offset: int) -> None:
        """⚠️ 每一批都要斷言——失敗的請求會讓 get_db 回滾**整個測試交易**，連前面幾批
        與課程 / 在籍列一起消失，後面的量測就變成在空資料上跑。"""
        r = await client.post(url, json=_batch(offset), headers=headers)
        assert r.status_code == 200, r.text

    async def _rows() -> int:
        return await db.scalar(
            select(func.count())
            .select_from(EtProgressInterval)
            .where(EtProgressInterval.video_id == course["video_id"])
        )

    # ── 1. 一般批次寫入（暖機一批後量第二批，此時累積 400 列 < 500，不觸發壓縮）──
    await _post(0)
    started = time.perf_counter()
    await _post(1)
    plain_write = time.perf_counter() - started
    rows = await _rows()
    assert rows == _MAX_SEGMENTS * 2, f"應累積 {_MAX_SEGMENTS * 2} 列，實得 {rows}"
    _report("一般批次寫入（200 段，未觸發壓縮）", plain_write, extra=f"累積 {rows} 列")

    # ── 2. normalize：對 400 列做合併 ──────────────────────────────────────────
    started = time.perf_counter()
    normalized = await client.post(f"/api/et/videos/{course['video_id']}/normalize", headers=headers)
    normalize_elapsed = time.perf_counter() - started
    assert normalized.status_code == 200, normalized.text
    rows_after = await _rows()
    _report("normalize", normalize_elapsed, extra=f"{rows} 列 → {rows_after} 列")
    assert rows_after < rows, "normalize 未壓縮任何列——重疊區段沒被合併，量到的不是它該做的事"

    # ── 3. 觸發自動壓縮的那一次寫入（最壞情況）────────────────────────────────
    #     先灌回 500 列以上，讓下一次寫入必然踩到 _MAX_INTERVAL_ROWS
    for offset in (2, 3):
        await _post(offset)
    before_compact = await _rows()
    # 門檻是「**寫入後**的總數」，故前置只需讓「再加一批」會超過即可
    assert before_compact + _MAX_SEGMENTS > _AUTO_COMPACT_ROWS, (
        f"前置 {before_compact} 列 + 一批 {_MAX_SEGMENTS} 段仍未超過門檻 {_AUTO_COMPACT_ROWS}，"
        "下一次寫入不會觸發壓縮——本段量到的就不是最壞情況了"
    )
    started = time.perf_counter()
    await _post(4)
    compacting_write = time.perf_counter() - started
    after_compact = await _rows()
    _report("觸發自動壓縮的寫入（最壞情況）", compacting_write, extra=f"{before_compact} 列 → {after_compact} 列")
    assert after_compact < before_compact, "未發生自動壓縮，量到的不是最壞情況"

    assert plain_write < _RESPONSE_BUDGET_SEC, f"一般批次寫入耗時 {plain_write:.2f}s"
    assert normalize_elapsed < _RESPONSE_BUDGET_SEC, f"normalize 耗時 {normalize_elapsed:.2f}s"
    assert compacting_write < _RESPONSE_BUDGET_SEC, f"觸發壓縮的寫入耗時 {compacting_write:.2f}s"
