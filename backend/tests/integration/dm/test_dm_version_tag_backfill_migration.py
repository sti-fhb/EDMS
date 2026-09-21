"""`dm_add_version_tag_snapshot`（2bf2384687c8）之回填正確性（#377）。

測試**直接執行 migration 模組匯出的 `BACKFILL_INFLIGHT`**，而非在測試裡重抄一份——
重抄會 drift，屆時測試綠燈但實際 migration 是另一套邏輯（作法比照
`tests/integration/et/test_et_backfill_last_activity_migration.py`）。

三張表都以 `CREATE TEMP TABLE ... ON COMMIT DROP` 建立：PostgreSQL 的 temp schema 排在
`search_path` 之前，故 SQL 裡未加 schema 限定的表名會落在暫存表上，不會動到真實資料。

**唯獨 `DM_VERSION_TAG` 的 UQ(VERSION_ID, TAG_ID) 必須建**——`ON CONFLICT` 需要對應的
唯一索引才能執行；這也正是本回填的關鍵前提。其餘約束刻意不建：回填只做 INSERT ... SELECT，
少了 FK / PK 不會掩蓋任何缺陷。欄位型別逐欄對齊真實 schema（`DELETED` 為 integer）。

為何非測不可：正式環境的回填目標是「migration 執行當下既有的在途草稿」，而測試 DB 每次
都是全新 migrate、該目標恆為空——是**測不到**，不是規則授權省略。兩者都導向「不寫測試」，
但前者是能力限制、後者是被授權，混為一談會讓省略看起來有依據。
"""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "20260918_1723_2bf2384687c8_dm_add_version_tag_snapshot.py"
)


def _load_migration():
    """以路徑載入 migration 模組（alembic/versions 非 package，不能 import）。"""
    spec = importlib.util.spec_from_file_location("_mig_dm_version_tag_backfill", _MIGRATION)
    assert spec and spec.loader, f"找不到 migration：{_MIGRATION}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def _create_temp_tables(db, *, doc_tag_unique: bool = True) -> None:
    """建立回填涉及的三張表之暫存版（僅含本回填會讀寫的欄位）。

    Args:
        doc_tag_unique: 是否於來源 `DM_DOC_TAG` 建 UQ(DOC_ID, TAG_ID)。預設 True（對齊真實 schema）；
            傳 False 以模擬「該約束被改為 partial index」後來源可出現重複的情形。
    """
    await db.execute(
        text(
            'CREATE TEMP TABLE "DM_DOC_VERSION" ('
            '  "VERSION_ID" bigint,'
            '  "DOC_ID" varchar(20),'
            '  "STATUS" varchar(20),'
            '  "DELETED" integer DEFAULT 0'
            ") ON COMMIT DROP"
        )
    )
    uq = ', CONSTRAINT "uq_tmp_doc_tag" UNIQUE ("DOC_ID", "TAG_ID")' if doc_tag_unique else ""
    await db.execute(
        text(
            'CREATE TEMP TABLE "DM_DOC_TAG" ('
            '  "DOC_ID" varchar(20),'
            '  "TAG_ID" bigint,'
            f'  "DELETED" integer DEFAULT 0{uq}'
            ") ON COMMIT DROP"
        )
    )
    # UQ 為 ON CONFLICT 的依據，必須建
    await db.execute(
        text(
            'CREATE TEMP TABLE "DM_VERSION_TAG" ('
            '  "VERSION_ID" bigint,'
            '  "TAG_ID" bigint,'
            '  "CREATED_USER" varchar(20),'
            '  "CREATED_DATE" timestamptz,'
            '  "DELETED" integer DEFAULT 0,'
            '  CONSTRAINT "uq_tmp_version_tag" UNIQUE ("VERSION_ID", "TAG_ID")'
            ") ON COMMIT DROP"
        )
    )


async def _version(db, version_id: int, doc_id: str, status: str, deleted: int = 0) -> None:
    await db.execute(
        text(
            'INSERT INTO "DM_DOC_VERSION" ("VERSION_ID", "DOC_ID", "STATUS", "DELETED")'
            " VALUES (:v, :d, :s, :del)"
        ),
        {"v": version_id, "d": doc_id, "s": status, "del": deleted},
    )


async def _doc_tag(db, doc_id: str, tag_id: int, deleted: int = 0) -> None:
    await db.execute(
        text('INSERT INTO "DM_DOC_TAG" ("DOC_ID", "TAG_ID", "DELETED") VALUES (:d, :t, :del)'),
        {"d": doc_id, "t": tag_id, "del": deleted},
    )


async def _run_backfill(db) -> None:
    mod = _load_migration()
    await db.execute(mod.BACKFILL_INFLIGHT.bindparams(u="SYSTEM", now=datetime.now(timezone.utc)))


async def _snapshot(db) -> set[tuple[int, int]]:
    rows = await db.execute(text('SELECT "VERSION_ID", "TAG_ID" FROM "DM_VERSION_TAG" ORDER BY 1, 2'))
    return {(r[0], r[1]) for r in rows.all()}


async def test_backfills_only_inflight_versions(db):
    """僅回填在途版本（DRAFT / PENDING_REVIEW）；已發布 / 已退回不回填。"""
    await _create_temp_tables(db)
    await _version(db, 1, "DM-SOP-000001", "DRAFT")
    await _version(db, 2, "DM-SOP-000001", "PENDING_REVIEW")
    await _version(db, 3, "DM-SOP-000001", "PUBLISHED")
    await _version(db, 4, "DM-SOP-000001", "REJECTED")
    await _version(db, 5, "DM-SOP-000001", "SUPERSEDED")
    await _doc_tag(db, "DM-SOP-000001", 10)

    await _run_backfill(db)

    assert await _snapshot(db) == {(1, 10), (2, 10)}


async def test_skips_deleted_versions_and_deleted_tags(db):
    """軟刪版本不回填；軟刪之文件層標籤不納入來源。"""
    await _create_temp_tables(db)
    await _version(db, 1, "DM-SOP-000001", "DRAFT")
    await _version(db, 2, "DM-SOP-000001", "DRAFT", deleted=1)  # 已刪草稿
    await _doc_tag(db, "DM-SOP-000001", 10)
    await _doc_tag(db, "DM-SOP-000001", 11, deleted=1)  # 已移除的標籤

    await _run_backfill(db)

    assert await _snapshot(db) == {(1, 10)}


async def test_each_inflight_version_gets_own_snapshot(db):
    """同一文件多人各有在途版本 → 各自取得獨立快照（值相同、列分開）。"""
    await _create_temp_tables(db)
    await _version(db, 1, "DM-SOP-000001", "DRAFT")
    await _version(db, 2, "DM-SOP-000001", "DRAFT")  # 另一位撰寫者
    await _version(db, 3, "DM-SOP-000002", "PENDING_REVIEW")  # 另一份文件
    await _doc_tag(db, "DM-SOP-000001", 10)
    await _doc_tag(db, "DM-SOP-000001", 11)
    await _doc_tag(db, "DM-SOP-000002", 20)

    await _run_backfill(db)

    assert await _snapshot(db) == {(1, 10), (1, 11), (2, 10), (2, 11), (3, 20)}


async def test_backfill_is_idempotent(db):
    """重跑不重複插入（ON CONFLICT DO NOTHING）。"""
    await _create_temp_tables(db)
    await _version(db, 1, "DM-SOP-000001", "DRAFT")
    await _doc_tag(db, "DM-SOP-000001", 10)

    await _run_backfill(db)
    await _run_backfill(db)

    assert await _snapshot(db) == {(1, 10)}
    total = (await db.execute(text('SELECT COUNT(*) FROM "DM_VERSION_TAG"'))).scalar_one()
    assert total == 1


async def test_duplicate_source_rows_absorbed_by_on_conflict(db):
    """來源出現重複 (DOC_ID, TAG_ID) 時仍不爆錯——釘住 ON CONFLICT 的兜底行為。

    今日造不出這種來源：`DM_DOC_TAG` 的 UQ(DOC_ID, TAG_ID) 為**無條件全表唯一**（軟刪列也佔位），
    故對固定 VERSION_ID 每個 TAG_ID 僅一列。本測試刻意在建暫存表時不加該約束，模擬「日後該約束
    被改為 partial index（如 WHERE DELETED=0）」的情形——屆時同一 (DOC_ID, TAG_ID) 可存在多列，
    回填語句即會產生重複鍵。此處釘住的是「那時的行為是什麼」：由 DO NOTHING 吸收、不中斷 migration。

    ⚠️ 留下哪一列無保證。本回填只取 (VERSION_ID, TAG_ID) 兩欄、不帶其他來源欄位，故留哪一列
    不影響結果；若日後回填改為帶入來源的其他欄位，這個「無保證」就會變成真正的問題，需加 ORDER BY。
    """
    await _create_temp_tables(db, doc_tag_unique=False)
    await _version(db, 1, "DM-SOP-000001", "DRAFT")
    await _doc_tag(db, "DM-SOP-000001", 10)
    await _doc_tag(db, "DM-SOP-000001", 10)  # 重複來源列

    await _run_backfill(db)  # 不得拋 UniqueViolation

    assert await _snapshot(db) == {(1, 10)}
