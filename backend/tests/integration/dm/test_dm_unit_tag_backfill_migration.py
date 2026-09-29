"""`dm_add_unit_tag_pair`（a9a9b0d378c5）之回填正確性（#437）。

測試**直接執行 migration 模組匯出的 `BACKFILL_DOC_TAG` / `BACKFILL_VERSION_TAG`**，而非在測試裡
重抄一份——重抄會 drift，屆時測試綠燈但實際 migration 是另一套邏輯（作法比照
`test_dm_version_tag_backfill_migration.py`）。

表以 `CREATE TEMP TABLE ... ON COMMIT DROP` 建立：PostgreSQL 的 temp schema 排在 `search_path`
之前，故 SQL 裡未加 schema 限定的表名會落在暫存表上，不會動到真實資料。回填只做 UPDATE ... FROM，
不需唯一索引，故約束一律不建（少了 FK / UQ 不會掩蓋任何缺陷）。

為何非測不可：正式環境的回填目標是「migration 執行當下既有的文件標籤」，而測試 DB 每次都是全新
migrate、該目標恆為空——是**測不到**，不是規則授權省略（`sti-alembic-rules.md` 免除的是 schema
驗收，不含回填的業務語意）。回填錯誤的後果是既有文件可見範圍改變，且不會有任何錯誤訊息。
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

_MIGRATION = (
    Path(__file__).resolve().parents[3] / "alembic" / "versions" / "20260929_1404_a9a9b0d378c5_dm_add_unit_tag_pair.py"
)

_ALL_UNITS_ID = 990  # 暫存資料中代表「全單位」標籤的 TAG_ID
_ROLE_TAG_ID = 10  # AUDIENCE 組（職位）
_RETRIEVAL_TAG_ID = 20  # RETRIEVAL 組（檢索標籤，無單位維度）


def _load_migration():
    """以路徑載入 migration 模組（alembic/versions 非 package，不能 import）。"""
    spec = importlib.util.spec_from_file_location("_mig_dm_unit_tag_backfill", _MIGRATION)
    assert spec and spec.loader, f"找不到 migration：{_MIGRATION}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def _create_temp_tables(db) -> None:
    """建立回填涉及的三張表之暫存版（僅含本回填會讀寫的欄位）。"""
    await db.execute(
        text(
            'CREATE TEMP TABLE "DM_TAG" ('
            '  "TAG_ID" bigint,'
            '  "TAG_GROUP_CODE" varchar(20)'
            ") ON COMMIT DROP"
        )
    )
    await db.execute(
        text(
            'CREATE TEMP TABLE "DM_DOC_TAG" ('
            '  "DOC_ID" varchar(20),'
            '  "TAG_ID" bigint,'
            '  "UNIT_TAG_ID" bigint,'
            '  "DELETED" integer DEFAULT 0'
            ") ON COMMIT DROP"
        )
    )
    await db.execute(
        text(
            'CREATE TEMP TABLE "DM_VERSION_TAG" ('
            '  "VERSION_ID" bigint,'
            '  "TAG_ID" bigint,'
            '  "UNIT_TAG_ID" bigint,'
            '  "DELETED" integer DEFAULT 0'
            ") ON COMMIT DROP"
        )
    )
    # 標籤主檔：一個職位（AUDIENCE）、一個檢索（RETRIEVAL）、一個單位（UNIT）
    for tag_id, group in ((_ROLE_TAG_ID, "AUDIENCE"), (_RETRIEVAL_TAG_ID, "MODULE"), (_ALL_UNITS_ID, "UNIT")):
        await db.execute(
            text('INSERT INTO "DM_TAG" ("TAG_ID", "TAG_GROUP_CODE") VALUES (:t, :g)'),
            {"t": tag_id, "g": group},
        )


async def _doc_tag(db, doc_id: str, tag_id: int, unit_tag_id: int | None = None, deleted: int = 0) -> None:
    await db.execute(
        text(
            'INSERT INTO "DM_DOC_TAG" ("DOC_ID", "TAG_ID", "UNIT_TAG_ID", "DELETED") VALUES (:d, :t, :u, :del)'
        ),
        {"d": doc_id, "t": tag_id, "u": unit_tag_id, "del": deleted},
    )


async def _version_tag(db, version_id: int, tag_id: int, unit_tag_id: int | None = None, deleted: int = 0) -> None:
    await db.execute(
        text(
            'INSERT INTO "DM_VERSION_TAG" ("VERSION_ID", "TAG_ID", "UNIT_TAG_ID", "DELETED") '
            "VALUES (:v, :t, :u, :del)"
        ),
        {"v": version_id, "t": tag_id, "u": unit_tag_id, "del": deleted},
    )


async def _run_backfill(db) -> None:
    mod = _load_migration()
    await db.execute(text(mod.BACKFILL_DOC_TAG), {"all_units_id": _ALL_UNITS_ID})
    await db.execute(text(mod.BACKFILL_VERSION_TAG), {"all_units_id": _ALL_UNITS_ID})


async def _doc_snapshot(db) -> set[tuple[str, int, int | None]]:
    rows = await db.execute(text('SELECT "DOC_ID", "TAG_ID", "UNIT_TAG_ID" FROM "DM_DOC_TAG" ORDER BY 1, 2'))
    return {(r[0], r[1], r[2]) for r in rows.all()}


async def _version_snapshot(db) -> set[tuple[int, int, int | None]]:
    rows = await db.execute(text('SELECT "VERSION_ID", "TAG_ID", "UNIT_TAG_ID" FROM "DM_VERSION_TAG" ORDER BY 1, 2'))
    return {(r[0], r[1], r[2]) for r in rows.all()}


async def test_職位標籤補上全單位_檢索標籤維持_null(db):
    """AUDIENCE 組列回填「全單位」使可見範圍不變；RETRIEVAL 組無單位維度，維持 NULL。"""
    await _create_temp_tables(db)
    await _doc_tag(db, "DM-SOP-000001", _ROLE_TAG_ID)
    await _doc_tag(db, "DM-SOP-000001", _RETRIEVAL_TAG_ID)

    await _run_backfill(db)

    assert await _doc_snapshot(db) == {
        ("DM-SOP-000001", _ROLE_TAG_ID, _ALL_UNITS_ID),
        ("DM-SOP-000001", _RETRIEVAL_TAG_ID, None),
    }


async def test_軟刪除的職位標籤同樣回填(db):
    """軟刪列一併回填——差異式覆寫會復活既有列，若留 NULL 復活後即成語意錯誤的配對。"""
    await _create_temp_tables(db)
    await _doc_tag(db, "DM-SOP-000001", _ROLE_TAG_ID, deleted=1)

    await _run_backfill(db)

    assert await _doc_snapshot(db) == {("DM-SOP-000001", _ROLE_TAG_ID, _ALL_UNITS_ID)}


async def test_已有單位者不被覆寫(db):
    """重跑 migration 不得改動已指定單位之列（`WHERE UNIT_TAG_ID IS NULL` 保證 idempotent）。"""
    await _create_temp_tables(db)
    await _doc_tag(db, "DM-SOP-000001", _ROLE_TAG_ID, unit_tag_id=777)

    await _run_backfill(db)

    assert await _doc_snapshot(db) == {("DM-SOP-000001", _ROLE_TAG_ID, 777)}


async def test_版本層快照同樣回填(db):
    """`DM_VERSION_TAG` 之在途草稿快照亦須回填，否則送簽檢核與核准套用的配對缺單位。"""
    await _create_temp_tables(db)
    await _version_tag(db, 1, _ROLE_TAG_ID)
    await _version_tag(db, 1, _RETRIEVAL_TAG_ID)
    await _version_tag(db, 2, _ROLE_TAG_ID, unit_tag_id=777)

    await _run_backfill(db)

    assert await _version_snapshot(db) == {
        (1, _ROLE_TAG_ID, _ALL_UNITS_ID),
        (1, _RETRIEVAL_TAG_ID, None),
        (2, _ROLE_TAG_ID, 777),
    }
