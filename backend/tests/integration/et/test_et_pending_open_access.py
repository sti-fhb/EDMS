"""尚未開放之課程的學員端存取守門（#374）。

## 這一檔為什麼存在

`OPEN_START_AT` **在此之前沒有任何存取守門**。`grep` 整個 `app/et/` 只會在 models、
schemas、publish_*、`enrollment/rules` 與通知文案裡看到它——`learning/` 與 `progress/`
一次都沒有。也就是說：擋住學員的從來只是「我的課程清單上沒有那張卡、沒有連結可點」。

而 #363 讓那張卡出現了（尚未開放者改為顯示、不可點擊），於是深連結變得更好猜。

## 為什麼不只是存取控制問題

沒有守門時，學員在課程開放前可以：看教材 → 觸發 `ET_PROGRESS` 寫入 → 作答測驗 →
**達成完課**。對教育訓練紀錄系統，那會產生「訓練完成日早於課程開放日」的自相矛盾
紀錄，而系統不會有任何異常訊號。這是資料正確性問題，不只是「提前看到內容」。

## 與「已關閉」的處置**相反**，兩檔要對照著看

| | 讀 | 寫 |
|---|---|---|
| 已關閉（`test_et_closed_course_behaviours.py`）| ✅ 唯讀回看 | ⛔ 全停 |
| 尚未開放（本檔）| ⛔ | ⛔ |

關閉後讀得到，是因為學員**曾經學過**、那是他的歷史紀錄；尚未開放的課程他從未學過。
任何把兩者統一成同一種處置的改動都會弄壞其中一邊。

helper 沿用關閉那一檔（同一種課程骨架、同一組端點），避免兩邊各維護一份而漂移。
"""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core.utils import utcnow
from app.et.course.models import EtCourse
from app.et.progress.models import EtProgress

from .test_et_closed_course_behaviours import _COURSES, _bearer, _ready

pytestmark = pytest.mark.integration


async def _set_start_in_future(db, course_id: int, *, days: int = 7) -> None:
    """把閱課起始時間改到未來——沒有產品路徑能造出這個狀態。

    課程一旦發布，`OPEN_START_AT` 只能由教師改排程（`ensure_schedule_not_cleared`），
    而那條路徑不保證能設到未來且不影響其他欄位。此處直接改 DB，比照關閉那一檔造
    `expired` 的做法。
    """
    await db.execute(
        update(EtCourse).where(EtCourse.course_id == course_id).values(open_start_at=utcnow() + timedelta(days=days))
    )
    await db.flush()


class TestLearningBlocked:
    """`learning/`：尚未開放者不得進入（403 `ET_LEARN_005`）。"""

    async def test_學員進不去(self, client, db) -> None:
        """⚠️ 與關閉相反——關閉是 200 唯讀，尚未開放是 403。

        回 **403 而非 404**：課程的存在對在籍學員不是秘密（他自己加入的、卡片就在
        我的課程清單上），要告訴他的是「還沒開始」而非「查無此課」。
        """
        ctx = await _ready(client, db, "po1")
        await _set_start_in_future(db, ctx["course_id"])

        got = await client.get(f"{_COURSES}/{ctx['course_id']}/learn", headers=_bearer(ctx["student"]))

        assert got.status_code == 403, got.text
        assert got.json()["error_code"] == "ET_LEARN_005"

    async def test_擁有者仍可預覽(self, client, db) -> None:
        """#255 裁示 Q1：教師預覽刻意放行，守門必須豁免擁有者。

        漏掉豁免的後果是**教師被鎖在自己的課外面**——而課程尚未開放正是他最需要預覽的
        時候（確認影片能不能播、PDF 內嵌會不會爆版）。
        """
        ctx = await _ready(client, db, "po2")
        await _set_start_in_future(db, ctx["course_id"])

        got = await client.get(f"{_COURSES}/{ctx['course_id']}/learn", headers=_bearer(ctx["teacher"]))

        assert got.status_code == 200, got.text
        assert len(got.json()["chapters"]) == 1

    async def test_起始到達後即可進入_不需任何動作(self, client, db) -> None:
        """守門以請求當下的 `now` 判定，故時間一到自動放行。

        這條釘的是「不需學員或教師做任何動作」——若哪天有人把判定結果快取進 DB 欄位，
        這裡會紅。

        ⚠️ **本測試安排了兩次請求，其中第一次預期失敗，所以前置必須 `commit`。**
        `_ready` 只 `flush`，而失敗請求的交易回滾會連帶把測試自己建的選課列一起清掉
        ——第二次請求就會拿到 `ET_LEARN_002`「您尚未加入此課程」而非預期的 200，看起來
        像守門沒放行，實際上是前置資料不見了。
        """
        ctx = await _ready(client, db, "po3")
        await _set_start_in_future(db, ctx["course_id"])
        await db.commit()

        assert (
            await client.get(f"{_COURSES}/{ctx['course_id']}/learn", headers=_bearer(ctx["student"]))
        ).status_code == 403

        await db.execute(
            update(EtCourse)
            .where(EtCourse.course_id == ctx["course_id"])
            .values(open_start_at=utcnow() - timedelta(minutes=1))
        )
        await db.commit()

        got = await client.get(f"{_COURSES}/{ctx['course_id']}/learn", headers=_bearer(ctx["student"]))
        assert got.status_code == 200, got.text


class TestProgressBlocked:
    """`progress/`：尚未開放者不得累積進度（409 `ET_PROGRESS_003`）。"""

    async def test_標記已檢視被擋(self, client, db) -> None:
        ctx = await _ready(client, db, "po4")
        await _set_start_in_future(db, ctx["course_id"])

        got = await client.post(f"/api/et/items/{ctx['item_id']}/viewed", headers=_bearer(ctx["student"]))

        assert got.status_code == 409, got.text
        assert got.json()["error_code"] == "ET_PROGRESS_003"

    async def test_不留下任何進度列(self, client, db) -> None:
        """⭐ 這條才是本 issue 的核心：**完課紀錄不得早於課程開放日**。

        只回 409 而仍寫入一列的話，稽核上會看到「訓練完成日早於課程開放日」，而畫面
        與 API 都不會有任何異常訊號。
        """
        ctx = await _ready(client, db, "po5")
        await _set_start_in_future(db, ctx["course_id"])

        await client.post(f"/api/et/items/{ctx['item_id']}/viewed", headers=_bearer(ctx["student"]))

        rows = (await db.scalars(select(EtProgress).where(EtProgress.course_id == ctx["course_id"]))).all()
        assert rows == [], "課程尚未開放卻留下進度列——完課日會早於開放日"


class TestAttemptBlocked:
    """`attempt/`：尚未開放者不得開新作答（409 `ET_ATTEMPT_007`）。"""

    async def test_開始作答被擋(self, client, db) -> None:
        ctx = await _ready(client, db, "po6", with_quiz=True)
        await _set_start_in_future(db, ctx["course_id"])

        got = await client.post(f"/api/et/quizzes/{ctx['quiz_id']}/attempts", headers=_bearer(ctx["student"]))

        assert got.status_code == 409, got.text
        assert got.json()["error_code"] == "ET_ATTEMPT_007"
