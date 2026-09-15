"""SCHET002 的批次容錯：單筆失敗不得波及其餘（US14 / #325）。

## 為何寫在 unit 而不是 integration

要驗的行為是「第 1 筆丟例外後，第 2 筆仍被處理」，而正確的實作必須在 `except` 內
`rollback()`。integration 的 session 採 `join_transaction_mode="create_savepoint"`
（見 `tests/integration/conftest.py`），被測程式呼叫 `rollback()` 會一路回到該 savepoint
——**連測試自己建的課程與使用者都被清掉**，於是第 2 圈根本查不到資料，斷言會因為一個
與待測行為無關的理由而紅。

（同一條限制在本專案已有前例：「一條測試只能安排一次預期失敗的呼叫」。）

## 這個保證為何重要

整批共用一個 `AsyncSession`。任一筆觸發 DB 層例外後 session 即進入待回滾狀態，不
`rollback()` 就續跑的話，**排在它後面的每一筆都會跟著失敗**（`PendingRollbackError`），
還各自記一行看似獨立的錯誤，把「只有第一筆是根因」蓋掉。而掃描是 `order_by(id)`，
於是同一筆壞資料會讓它之後的所有課程 / 作答**每天連坐**。
"""

import pytest

from app.et.schedules.service import EtScheduleService

pytestmark = pytest.mark.unit


class _FakeSession:
    """只記錄 commit / rollback 次數——本檔完全不碰 DB。"""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _FakeScheduleRepo:
    def __init__(self, course_ids: list[int], attempt_ids: list[int]) -> None:
        self._course_ids = course_ids
        self._attempt_ids = attempt_ids

    async def expired_published_course_ids(self, db, now) -> list[int]:
        return self._course_ids

    async def stale_in_progress_attempt_ids(self, db, now) -> list[int]:
        return self._attempt_ids


class _ExplodingCourses:
    """`get()` 對指定 id 丟例外，其餘回 `None`（讓 `_close_one` 早退、不需真資料）。"""

    def __init__(self, boom_id: int) -> None:
        self._boom_id = boom_id
        self.seen: list[int] = []

    async def get(self, db, course_id: int):
        self.seen.append(course_id)
        if course_id == self._boom_id:
            raise RuntimeError("模擬 DB 層例外")
        return None


class _ExplodingAttempts:
    def __init__(self, boom_id: int) -> None:
        self._boom_id = boom_id
        self.seen: list[int] = []

    async def get_attempt(self, db, attempt_id: int):
        self.seen.append(attempt_id)
        if attempt_id == self._boom_id:
            raise RuntimeError("模擬 DB 層例外")
        return None


class TestCloseBatchIsolation:
    async def test_第一筆例外後仍處理其餘(self) -> None:
        courses = _ExplodingCourses(boom_id=1)
        service = EtScheduleService(repository=_FakeScheduleRepo([1, 2, 3], []), courses=courses)

        closed = await service.close_expired_courses(_FakeSession())

        assert courses.seen == [1, 2, 3], "第一筆失敗後必須繼續掃完其餘"
        assert closed == 0

    async def test_例外時呼叫rollback(self) -> None:
        """不 rollback 的話，整批在第一次失敗之後全數連坐。"""
        session = _FakeSession()
        service = EtScheduleService(repository=_FakeScheduleRepo([1], []), courses=_ExplodingCourses(boom_id=1))

        await service.close_expired_courses(session)

        assert session.rollbacks == 1
        assert session.commits == 0


class TestSettleBatchIsolation:
    async def test_第一筆例外後仍處理其餘(self) -> None:
        attempts = _ExplodingAttempts(boom_id=10)
        service = EtScheduleService(repository=_FakeScheduleRepo([], [10, 20, 30]), attempts=attempts)

        settled = await service.settle_stale_attempts(_FakeSession())

        assert attempts.seen == [10, 20, 30], "第一筆失敗後必須繼續掃完其餘"
        assert settled == 0

    async def test_例外時呼叫rollback(self) -> None:
        session = _FakeSession()
        service = EtScheduleService(repository=_FakeScheduleRepo([], [10]), attempts=_ExplodingAttempts(boom_id=10))

        await service.settle_stale_attempts(session)

        assert session.rollbacks == 1
        assert session.commits == 0


class TestNoWriteNoCommit:
    """沒有實際寫入的一圈不應 commit——空 commit 會讓「這圈做了什麼」在日誌上不可辨。"""

    async def test_課程查無時不commit(self) -> None:
        session = _FakeSession()
        service = EtScheduleService(repository=_FakeScheduleRepo([1], []), courses=_ExplodingCourses(boom_id=999))

        await service.close_expired_courses(session)

        assert session.commits == 0
        assert session.rollbacks == 1
