"""`et_remove_owner_self_enrollment`（b4e7c9a1d2f3）之清理正確性（#520）。

測試**直接執行 migration 模組匯出的 SQL**，而非在測試裡重抄一份——重抄會 drift，
屆時測試綠燈但實際 migration 是另一套邏輯（作法比照
`test_et_backfill_last_activity_migration.py` 與 `test_file_path_to_relative_migration.py`）。

兩張表以 `CREATE TEMP TABLE ... ON COMMIT DROP` 建立：PostgreSQL 的 temp schema 排在
`search_path` 之前，故 SQL 裡未加 schema 限定的表名會落在暫存表上，不會動到真實資料。

暫存表**刻意不建 `UQ_ET_ENROLLMENT_USER_COURSE`**——本 migration 只做 `UPDATE`、
不插入，唯一性不影響其行為；而少建約束讓每條測試只需填自己關心的欄位。
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "20261005_1500_b4e7c9a1d2f3_et_remove_owner_self_enrollment.py"
)


def _load_migration():
    """以路徑載入 migration 模組（alembic/versions 非 package，不能 import）。"""
    spec = importlib.util.spec_from_file_location("_mig_et_remove_owner_self", _MIGRATION)
    assert spec and spec.loader, f"找不到 migration：{_MIGRATION}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def _create_temp_tables(db) -> None:
    await db.execute(
        text('CREATE TEMP TABLE "ET_COURSE" (  "COURSE_ID" bigint,  "OWNER_ID" varchar(20)) ON COMMIT DROP')
    )
    await db.execute(
        text(
            'CREATE TEMP TABLE "ET_ENROLLMENT" ('
            '  "ENROLLMENT_ID" bigint,'
            '  "USER_ID" varchar(20),'
            '  "COURSE_ID" bigint,'
            '  "IS_REMOVED" boolean,'
            '  "DELETED" integer,'
            '  "UPDATED_USER" varchar(20),'
            '  "UPDATED_DATE" timestamptz'
            ") ON COMMIT DROP"
        )
    )


async def _course(db, course_id: int, owner_id: str) -> None:
    await db.execute(
        text('INSERT INTO "ET_COURSE" ("COURSE_ID", "OWNER_ID") VALUES (:cid, :owner)'),
        {"cid": course_id, "owner": owner_id},
    )


async def _enrollment(
    db, eid: int, user_id: str, course_id: int, *, is_removed: bool = False, deleted: int = 0
) -> None:
    await db.execute(
        text(
            'INSERT INTO "ET_ENROLLMENT" '
            '("ENROLLMENT_ID", "USER_ID", "COURSE_ID", "IS_REMOVED", "DELETED", "UPDATED_USER", "UPDATED_DATE") '
            "VALUES (:eid, :uid, :cid, :removed, :deleted, NULL, NULL)"
        ),
        {"eid": eid, "uid": user_id, "cid": course_id, "removed": is_removed, "deleted": deleted},
    )


async def _row(db, eid: int) -> dict:
    result = await db.execute(
        text('SELECT "IS_REMOVED", "UPDATED_USER" FROM "ET_ENROLLMENT" WHERE "ENROLLMENT_ID" = :eid'),
        {"eid": eid},
    )
    is_removed, updated_user = result.one()
    return {"is_removed": is_removed, "updated_user": updated_user}


async def _run(db) -> None:
    await db.execute(_load_migration()._REMOVE_OWNER_SELF_ENROLLMENT)


async def test_migration_chains_to_expected_parent() -> None:
    """鏈結正確性——與回填內容無關，但接錯 parent 會讓整條鏈在別人的環境分岔。"""
    mod = _load_migration()
    assert mod.revision == "b4e7c9a1d2f3"
    assert mod.down_revision == "34da4449e681"


async def test_downgrade_is_intentional_noop() -> None:
    """downgrade 刻意不實作（`IS_REMOVED=true` 無法與手動移除區分）。

    釘住這個決定，避免日後被當成漏寫而「補上」——補上的那個會把管理者手動移除的
    學員改回在籍，那是**製造**一筆不該存在的資料。
    """
    mod = _load_migration()
    assert mod.downgrade() is None


async def test_擁有者在自己課程的在籍列被標為已移除(db) -> None:
    await _create_temp_tables(db)
    await _course(db, 1, "t_owner")
    await _enrollment(db, 10, "t_owner", 1)

    await _run(db)

    row = await _row(db, 10)
    assert row["is_removed"] is True
    assert row["updated_user"] == "SYSTEM", "稽核上要看得出這是系統批次，不是某人按的"


async def test_擁有者在他人課程的在籍列不受影響(db) -> None:
    """🔴 與上一條**成對**：少了它，把條件寫成「只要是教師就移除」也會通過上一條。

    教師以邀請碼 / Email 邀請加入他人課程是合法的，不在清理範圍。
    """
    await _create_temp_tables(db)
    await _course(db, 1, "t_owner")
    await _course(db, 2, "t_other")
    await _enrollment(db, 10, "t_owner", 1)  # 自己的課 → 要清
    await _enrollment(db, 11, "t_owner", 2)  # 他人的課 → 不可動

    await _run(db)

    assert (await _row(db, 10))["is_removed"] is True
    assert (await _row(db, 11))["is_removed"] is False, "教師加入他人課程被誤清了"


async def test_一般學員不受影響(db) -> None:
    await _create_temp_tables(db)
    await _course(db, 1, "t_owner")
    await _enrollment(db, 12, "s_student", 1)

    await _run(db)

    assert (await _row(db, 12))["is_removed"] is False


async def test_已被移除者不重複改動(db) -> None:
    """`WHERE IS_REMOVED = false` 的作用：重跑不覆蓋 `UPDATED_*`。

    少了那個條件，重複執行會把「教師本人當初手動移除自己」的稽核痕跡蓋成 SYSTEM。
    """
    await _create_temp_tables(db)
    await _course(db, 1, "t_owner")
    await _enrollment(db, 13, "t_owner", 1, is_removed=True)
    await db.execute(
        text('UPDATE "ET_ENROLLMENT" SET "UPDATED_USER" = \'t_owner\' WHERE "ENROLLMENT_ID" = 13'),
    )

    await _run(db)

    assert (await _row(db, 13))["updated_user"] == "t_owner", "已移除者被重複改動，稽核痕跡被覆蓋"


async def test_軟刪除的列不受影響(db) -> None:
    await _create_temp_tables(db)
    await _course(db, 1, "t_owner")
    await _enrollment(db, 14, "t_owner", 1, deleted=1)

    await _run(db)

    assert (await _row(db, 14))["is_removed"] is False


async def test_殘留查詢在清理後為零(db) -> None:
    """🔴 `LEFTOVER_QUERY` 與 `UPDATE` 的 `WHERE` 刻意同義——本條驗兩者沒有分岔。

    若有人只改其中一個，殘留查詢會對著一個比實際寬鬆的條件回報「清乾淨了」。
    """
    mod = _load_migration()
    await _create_temp_tables(db)
    await _course(db, 1, "t_owner")
    await _course(db, 2, "t_other")
    await _enrollment(db, 10, "t_owner", 1)
    await _enrollment(db, 11, "t_owner", 2)
    await _enrollment(db, 12, "s_student", 1)

    before = await db.scalar(mod.LEFTOVER_QUERY)
    assert before == 1, "錨點失敗：清理前應有 1 筆待清，否則下面的 0 沒有意義"

    await _run(db)

    assert await db.scalar(mod.LEFTOVER_QUERY) == 0
