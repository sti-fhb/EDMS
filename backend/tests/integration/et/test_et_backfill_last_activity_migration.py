"""`et_backfill_last_activity_at`（ee1d5e46c3ad）之回填正確性（#339）。

測試**直接執行 migration 模組匯出的 `BACKFILL_SQL`**，而非在測試裡重抄一份——
重抄會 drift，屆時測試綠燈但實際 migration 是另一套邏輯（作法比照
`tests/integration/test_file_path_to_relative_migration.py`）。

四張表都以 `CREATE TEMP TABLE ... ON COMMIT DROP` 建立：PostgreSQL 的 temp schema
排在 `search_path` 之前，故 `BACKFILL_SQL` 裡未加 schema 限定的表名會落在暫存表上，
不會動到真實資料。也因此每條測試只需建立自己關心的欄位，不必複製完整 DDL。

暫存表**刻意不建真實 schema 的約束**（`ET_SURVEY.SURVEY_ID` 的 PK、`ET_ENROLLMENT`
的 `UQ_ET_ENROLLMENT_USER_COURSE` 等）——不是疏漏：回填靠的是 `MAX()`，而 `MAX()` 對
重複列不敏感，故少了唯一性約束不會掩蓋任何缺陷。欄位**型別**則逐欄對齊真實 schema
（含 `DELETED` 為 `integer` 而非 `smallint`），型別才是會改變比較與聚合行為的部分。
"""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def _ts(day: int, hour: int, minute: int = 0) -> datetime:
    """2026-09-{day} {hour}:{minute} UTC——asyncpg 只吃 datetime，不接受字串。"""
    return datetime(2026, 9, day, hour, minute, tzinfo=timezone.utc)


_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "20260916_1052_ee1d5e46c3ad_et_backfill_last_activity_at.py"
)


def _load_migration():
    """以路徑載入 migration 模組（alembic/versions 非 package，不能 import）。"""
    spec = importlib.util.spec_from_file_location("_mig_et_backfill_last_activity", _MIGRATION)
    assert spec and spec.loader, f"找不到 migration：{_MIGRATION}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def _create_temp_tables(db) -> None:
    """建立回填涉及的四張表之暫存版（僅含本 migration 會讀寫的欄位）。"""
    await db.execute(
        text(
            'CREATE TEMP TABLE "ET_ENROLLMENT" ('
            '  "ENROLLMENT_ID" bigint,'
            '  "USER_ID" varchar(20),'
            '  "COURSE_ID" bigint,'
            '  "LAST_ACTIVITY_AT" timestamptz'
            ") ON COMMIT DROP"
        )
    )
    await db.execute(
        text(
            'CREATE TEMP TABLE "ET_QUIZ_ATTEMPT_M" ('
            '  "USER_ID" varchar(20),'
            '  "COURSE_ID" bigint,'
            '  "SUBMITTED_AT" timestamptz,'
            '  "DELETED" integer DEFAULT 0'
            ") ON COMMIT DROP"
        )
    )
    await db.execute(
        text(
            'CREATE TEMP TABLE "ET_SURVEY" ('
            '  "SURVEY_ID" bigint,'
            '  "COURSE_ID" bigint,'
            '  "DELETED" integer DEFAULT 0'
            ") ON COMMIT DROP"
        )
    )
    await db.execute(
        text(
            'CREATE TEMP TABLE "ET_SURVEY_RESPONSE_M" ('
            '  "USER_ID" varchar(20),'
            '  "SURVEY_ID" bigint,'
            '  "SUBMITTED_AT" timestamptz,'
            '  "DELETED" integer DEFAULT 0'
            ") ON COMMIT DROP"
        )
    )


async def _enrollment(db, user_id: str, course_id: int, last_activity_at: datetime | None = None) -> None:
    await db.execute(
        text(
            'INSERT INTO "ET_ENROLLMENT" ("ENROLLMENT_ID", "USER_ID", "COURSE_ID", "LAST_ACTIVITY_AT")'
            " VALUES (1, :u, :c, :t)"
        ),
        {"u": user_id, "c": course_id, "t": last_activity_at},
    )


async def _attempt(db, user_id: str, course_id: int, submitted_at: datetime | None, deleted: int = 0) -> None:
    await db.execute(
        text(
            'INSERT INTO "ET_QUIZ_ATTEMPT_M" ("USER_ID", "COURSE_ID", "SUBMITTED_AT", "DELETED")'
            " VALUES (:u, :c, :t, :d)"
        ),
        {"u": user_id, "c": course_id, "t": submitted_at, "d": deleted},
    )


async def _survey_response(db, user_id: str, survey_id: int, course_id: int, submitted_at: datetime) -> None:
    await db.execute(
        text('INSERT INTO "ET_SURVEY" ("SURVEY_ID", "COURSE_ID", "DELETED") VALUES (:s, :c, 0)'),
        {"s": survey_id, "c": course_id},
    )
    await db.execute(
        text(
            'INSERT INTO "ET_SURVEY_RESPONSE_M" ("USER_ID", "SURVEY_ID", "SUBMITTED_AT", "DELETED")'
            " VALUES (:u, :s, :t, 0)"
        ),
        {"u": user_id, "s": survey_id, "t": submitted_at},
    )


async def _last_activity(db):
    return (await db.execute(text('SELECT "LAST_ACTIVITY_AT" FROM "ET_ENROLLMENT"'))).scalar_one()


async def _run_backfill(db) -> None:
    """執行 migration 匯出的 `BACKFILL_SQL`，並先確認它會落在暫存表上。

    `_create_temp_tables()` 是「不碰真實資料」的唯一前提，但語言本身不強制它被呼叫——
    新增測試時漏叫的話，SQL 會靜默落到真實表上，那條測試就變成在驗別的東西（資料仍由
    fixture 回滾、DB 也已由 conftest 確認是 test 庫，故無外洩風險，但測試語意已經不同
    且沒有任何徵兆）。這行斷言把該前提變成會出聲的失敗。
    """
    in_temp = (await db.execute(text("""SELECT to_regclass('pg_temp."ET_ENROLLMENT"') IS NOT NULL"""))).scalar_one()
    assert in_temp, "ET_ENROLLMENT 未解析到暫存 schema——請先呼叫 _create_temp_tables()"
    mod = _load_migration()
    await db.execute(text(mod.BACKFILL_SQL))


# --- migration 本身的結構 ---------------------------------------------------


def test_migration_chains_to_expected_parent():
    """接在 ET-16 的 head 之後（避免無意間造出第二個 head）。"""
    mod = _load_migration()
    assert mod.revision == "ee1d5e46c3ad"
    assert mod.down_revision == "d5a81f37c6b2"


def test_downgrade_is_intentional_noop():
    """downgrade 刻意留空——舊值已被覆寫，無從得知回填前是 NULL 還是更早的時間。"""
    mod = _load_migration()
    assert mod.downgrade() is None


# --- 驗收條件 ---------------------------------------------------------------


async def test_quiz_attempt_backfilled(db):
    """AC1：#334 之前已提交測驗者，最後活動不早於該次提交時間。"""
    await _create_temp_tables(db)
    await _enrollment(db, "u1", 100, last_activity_at=None)
    await _attempt(db, "u1", 100, _ts(10, 8))
    await _run_backfill(db)
    got = await _last_activity(db)
    assert got is not None
    assert got == _ts(10, 8)


async def test_survey_response_backfilled_via_survey_join(db):
    """AC2：問卷一併納入——`ET_SURVEY_RESPONSE_M` 無 `COURSE_ID`，須經 `ET_SURVEY` 轉一手。"""
    await _create_temp_tables(db)
    await _enrollment(db, "u1", 100, last_activity_at=None)
    await _survey_response(db, "u1", survey_id=7, course_id=100, submitted_at=_ts(11, 9, 30))
    await _run_backfill(db)
    got = await _last_activity(db)
    assert got is not None
    assert got == _ts(11, 9, 30)


async def test_survey_later_than_quiz_wins(db):
    """AC2 延伸：兩種活動並存時取較晚者（只補測驗會留下另一個不一致）。"""
    await _create_temp_tables(db)
    await _enrollment(db, "u1", 100, last_activity_at=None)
    await _attempt(db, "u1", 100, _ts(10, 8))
    await _survey_response(db, "u1", survey_id=7, course_id=100, submitted_at=_ts(12, 10))
    await _run_backfill(db)
    got = await _last_activity(db)
    assert got == _ts(12, 10)


async def test_multiple_attempts_same_course_takes_latest(db):
    """同一門課多次交卷時取最後一次——`MAX()` 在**單表內**的聚合正確性。

    與 `test_survey_later_than_quiz_wins` 不同：那條驗的是跨表（UNION ALL 之後）取較晚
    者，本條驗的是同一張來源表內有多筆已提交紀錄（測驗可重考，`ATTEMPT_NO` 遞增）。
    """
    await _create_temp_tables(db)
    await _enrollment(db, "u1", 100, last_activity_at=None)
    await _attempt(db, "u1", 100, _ts(10, 8))
    await _attempt(db, "u1", 100, _ts(13, 16))
    await _attempt(db, "u1", 100, _ts(11, 9))
    await _run_backfill(db)
    assert await _last_activity(db) == _ts(13, 16)


async def test_later_existing_value_not_overwritten(db):
    """AC3：既有值較晚時不被覆寫（學員提交測驗後又去看了教材）。"""
    await _create_temp_tables(db)
    await _enrollment(db, "u1", 100, last_activity_at=_ts(14, 12))
    await _attempt(db, "u1", 100, _ts(10, 8))
    await _run_backfill(db)
    got = await _last_activity(db)
    assert got == _ts(14, 12)


async def test_no_activity_stays_null(db):
    """AC4：從未有任何活動者維持 NULL（加入課程不是活動）。"""
    await _create_temp_tables(db)
    await _enrollment(db, "u1", 100, last_activity_at=None)
    await _run_backfill(db)
    assert await _last_activity(db) is None


async def test_unsubmitted_attempt_does_not_count(db):
    """AC4 延伸：作答中（`SUBMITTED_AT` 為 NULL）不算活動，仍維持 NULL。

    `ET_QUIZ_ATTEMPT_M.SUBMITTED_AT` 為 nullable（未交的 attempt），而
    `ET_SURVEY_RESPONSE_M.SUBMITTED_AT` 為 NOT NULL——業務上測驗有「寫到一半」、
    問卷沒有。`MAX()` 忽略 NULL，故不需另外濾 `STATUS`。
    """
    await _create_temp_tables(db)
    await _enrollment(db, "u1", 100, last_activity_at=None)
    await _attempt(db, "u1", 100, None)
    await _run_backfill(db)
    assert await _last_activity(db) is None


async def test_empty_db_is_noop(db):
    """AC5：空資料庫上為 no-op（正式機日後從頭建，不應報錯）。"""
    await _create_temp_tables(db)
    await _run_backfill(db)
    count = (await db.execute(text('SELECT count(*) FROM "ET_ENROLLMENT"'))).scalar_one()
    assert count == 0


# --- 連帶軟刪除與冪等 -------------------------------------------------------


async def test_deleted_attempt_excluded(db):
    """已軟刪除的 attempt 不算活動。

    #339 body 原稱 `DELETED` 在本表恆真，實測不成立：刪除章節 / 項目 / 課程會經
    `EtQuizRepository.soft_delete_cascade`（`quiz/repository.py:312`）把其下 attempt
    一併設為 `DELETED=1`。對齊 `course/models.py:82`「完課率 / 進度統計務必排除
    `DELETED = 1`」。
    """
    await _create_temp_tables(db)
    await _enrollment(db, "u1", 100, last_activity_at=None)
    await _attempt(db, "u1", 100, _ts(10, 8), deleted=1)
    await _run_backfill(db)
    assert await _last_activity(db) is None


async def test_other_course_activity_not_counted(db):
    """同一學員在別門課的活動不得灌進本門課（`COURSE_ID` 必須一起比對）。"""
    await _create_temp_tables(db)
    await _enrollment(db, "u1", 100, last_activity_at=None)
    await _attempt(db, "u1", 999, _ts(10, 8))
    await _run_backfill(db)
    assert await _last_activity(db) is None


async def test_rerun_is_idempotent(db):
    """重跑無副作用——WHERE 守衛使第二次執行不會再更新任何列。"""
    await _create_temp_tables(db)
    await _enrollment(db, "u1", 100, last_activity_at=None)
    await _attempt(db, "u1", 100, _ts(10, 8))
    await _run_backfill(db)
    first = await _last_activity(db)
    await _run_backfill(db)
    assert await _last_activity(db) == first
