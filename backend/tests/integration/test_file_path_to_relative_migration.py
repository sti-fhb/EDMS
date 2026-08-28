r"""`common_file_path_to_relative`（676114dc0672）之資料轉換正確性（#233 AC4）。

測試**直接執行 migration 模組匯出的 `TARGETS` SQL**，而非在測試裡重抄一份——
重抄會 drift，屆時測試綠燈但實際 migration 是另一套邏輯。

轉換的關鍵設計是「切點取自列自身的識別碼、不讀 settings」，故本測試也不需要設定
storage root，這本身就是該設計的驗證：同一份 SQL 在任何工作目錄下結果都一樣。
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260828_1546_676114dc0672_common_file_path_to_relative.py"
)


def _load_migration():
    """以路徑載入 migration 模組（alembic/versions 非 package，不能 import）。"""
    spec = importlib.util.spec_from_file_location("_mig_file_path_to_relative", _MIGRATION)
    assert spec and spec.loader, f"找不到 migration：{_MIGRATION}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_file_exists_and_chains_to_expected_parent():
    """migration 存在且接在既有 head 之後（避免無意間造出第二個 head）。"""
    mod = _load_migration()
    assert mod.revision == "676114dc0672"
    assert mod.down_revision == "1a85b7fe2cff"


def test_downgrade_is_intentional_noop():
    """downgrade 刻意留空——相對→絕對需要「當時的 root」，假還原會產生錯誤路徑。"""
    mod = _load_migration()
    assert mod.downgrade() is None


@pytest.mark.parametrize(
    ("stored", "doc_id", "expected"),
    [
        pytest.param(
            r"C:\Users\dev\TBMS_git\_dm_files_dev\DM-MANUAL-900010\7793.pdf",
            "DM-MANUAL-900010",
            "DM-MANUAL-900010/7793.pdf",
            id="windows-絕對路徑",
        ),
        pytest.param(
            "/srv/edms/dm_files/DM-TRAINING-000006/e809.pdf",
            "DM-TRAINING-000006",
            "DM-TRAINING-000006/e809.pdf",
            id="posix-絕對路徑",
        ),
        pytest.param(
            r"C:\Users\dev\TBMS_git\worktrees\feature-dm-editor\backend\var\dm_files\DM-MANUAL-900002\2b29.pdf",
            "DM-MANUAL-900002",
            "DM-MANUAL-900002/2b29.pdf",
            id="已刪-worktree-的絕對路徑",
        ),
        pytest.param(
            "DM-MANUAL-900010/7793.pdf",
            "DM-MANUAL-900010",
            "DM-MANUAL-900010/7793.pdf",
            id="已是相對路徑-冪等",
        ),
        pytest.param(
            r"DM-MANUAL-900010\7793.pdf",
            "DM-MANUAL-900010",
            "DM-MANUAL-900010/7793.pdf",
            id="已是相對路徑但反斜線-須正規化",
        ),
        pytest.param(
            # Code Review 抓到的缺陷：識別碼在路徑中出現兩次時，
            # 以「首次出現處」為切點會切成 DM-X/DM-X/f.pdf
            "/srv/DM-X/DM-X/f.pdf",
            "DM-X",
            "DM-X/f.pdf",
            id="識別碼出現兩次-不得從首次出現處切",
        ),
    ],
)
async def test_dm_version_path_converted(db, stored, doc_id, expected):
    """各種絕對路徑皆能以列自身 DOC_ID 為切點轉為相對片段；已是相對者不變（冪等）。"""
    mod = _load_migration()
    await db.execute(
        text('CREATE TEMP TABLE "DM_DOC_VERSION" ("DOC_ID" varchar(20), "FILE_PATH" varchar(500)) ON COMMIT DROP')
    )
    await db.execute(text('INSERT INTO "DM_DOC_VERSION" VALUES (:d, :p)'), {"d": doc_id, "p": stored})
    await db.execute(text(dict(mod.TARGETS)["DM_DOC_VERSION.FILE_PATH"]))
    got = (await db.execute(text('SELECT "FILE_PATH" FROM "DM_DOC_VERSION"'))).scalar_one()
    assert got == expected


async def test_path_without_own_doc_id_left_untouched(db):
    """路徑不含自身 DOC_ID → 切不出來，原樣保留（不設 NULL，保住「曾有檔」的事實）。"""
    mod = _load_migration()
    await db.execute(
        text('CREATE TEMP TABLE "DM_DOC_VERSION" ("DOC_ID" varchar(20), "FILE_PATH" varchar(500)) ON COMMIT DROP')
    )
    await db.execute(
        text('INSERT INTO "DM_DOC_VERSION" VALUES (:d, :p)'),
        {"d": "DM-MANUAL-900010", "p": "/nonexistent/test.pdf"},
    )
    await db.execute(text(dict(mod.TARGETS)["DM_DOC_VERSION.FILE_PATH"]))
    got = (await db.execute(text('SELECT "FILE_PATH" FROM "DM_DOC_VERSION"'))).scalar_one()
    assert got == "/nonexistent/test.pdf"


async def test_null_path_left_null(db):
    """草稿允許無檔（FILE_PATH 為 NULL）——轉換不得把 NULL 變成別的東西。"""
    mod = _load_migration()
    await db.execute(
        text('CREATE TEMP TABLE "DM_DOC_VERSION" ("DOC_ID" varchar(20), "FILE_PATH" varchar(500)) ON COMMIT DROP')
    )
    await db.execute(text("INSERT INTO \"DM_DOC_VERSION\" VALUES ('DM-OTHER-000009', NULL)"))
    await db.execute(text(dict(mod.TARGETS)["DM_DOC_VERSION.FILE_PATH"]))
    got = (await db.execute(text('SELECT "FILE_PATH" FROM "DM_DOC_VERSION"'))).scalar_one()
    assert got is None


@pytest.mark.parametrize(
    ("material_id", "stored", "expected"),
    [
        pytest.param(
            11,
            r"C:\Users\dev\TBMS_git\worktrees\feature-et\backend\var\et_videos\11\29ef.mp4",
            "11/29ef.mp4",
            id="一般情形",
        ),
        pytest.param(
            # Code Review 實測抓到的缺陷：路徑含 srv2，以「首次出現處」為切點會
            # 命中 srv2 的 2，切出 2/et_videos/2/29ef.mp4——錯誤但 position()>0 成立，
            # 「切不出來」的盤點條件抓不到，會被靜默寫入錯誤值。
            2,
            r"\data\srv2\et_videos\2\29ef.mp4",
            "2/29ef.mp4",
            id="短識別碼-前綴目錄含同數字",
        ),
        pytest.param(
            1,
            r"\srv1\v1\et_videos\1\abc.mp4",
            "1/abc.mp4",
            id="短識別碼-多處碰撞",
        ),
    ],
)
async def test_et_video_path_converted_by_material_id(db, material_id, stored, expected):
    """ET 影片以最後兩段取相對片段——短數字 MATERIAL_ID 特別容易被前綴目錄誤命中。"""
    mod = _load_migration()
    await db.execute(
        text('CREATE TEMP TABLE "ET_MATERIAL_VIDEO" ("MATERIAL_ID" bigint, "FILE_PATH" varchar(500)) ON COMMIT DROP')
    )
    await db.execute(text('INSERT INTO "ET_MATERIAL_VIDEO" VALUES (:m, :p)'), {"m": material_id, "p": stored})
    await db.execute(text(dict(mod.TARGETS)["ET_MATERIAL_VIDEO.FILE_PATH"]))
    got = (await db.execute(text('SELECT "FILE_PATH" FROM "ET_MATERIAL_VIDEO"'))).scalar_one()
    assert got == expected


async def test_leftover_query_flags_rows_that_failed_the_guard(db):
    """未通過守門的列須被盤點查詢抓到——「切出來但切錯」也算，不只「完全切不出來」。"""
    mod = _load_migration()
    await db.execute(
        text('CREATE TEMP TABLE "DM_DOC_VERSION" ("DOC_ID" varchar(20), "FILE_PATH" varchar(500)) ON COMMIT DROP')
    )
    await db.execute(
        text('CREATE TEMP TABLE "DM_REVIEW" ("DOC_ID" varchar(20), "OBSOLETE_FILE_PATH" varchar(500)) ON COMMIT DROP')
    )
    await db.execute(
        text('CREATE TEMP TABLE "ET_MATERIAL_VIDEO" ("MATERIAL_ID" bigint, "FILE_PATH" varchar(500)) ON COMMIT DROP')
    )
    await db.execute(
        text('INSERT INTO "DM_DOC_VERSION" VALUES (:d, :p)'),
        {"d": "DM-MANUAL-900010", "p": "/nonexistent/test.pdf"},  # 最後兩段是 nonexistent/test.pdf → 對不上
    )
    counts = {row.col: row.n for row in (await db.execute(text(mod.LEFTOVER_SQL))).all()}
    assert counts["DM_DOC_VERSION.FILE_PATH"] == 1
    assert counts["DM_REVIEW.OBSOLETE_FILE_PATH"] == 0
    assert counts["ET_MATERIAL_VIDEO.FILE_PATH"] == 0


async def test_obsolete_attachment_path_converted(db):
    """廢止附件沿用 save_upload 之 {doc_id}/ 佈局，切點同為 DOC_ID。"""
    mod = _load_migration()
    await db.execute(
        text('CREATE TEMP TABLE "DM_REVIEW" ("DOC_ID" varchar(20), "OBSOLETE_FILE_PATH" varchar(500)) ON COMMIT DROP')
    )
    await db.execute(
        text('INSERT INTO "DM_REVIEW" VALUES (:d, :p)'),
        {"d": "DM-SOP-000900", "p": r"C:\srv\dm_files\DM-SOP-000900\abc.pdf"},
    )
    await db.execute(text(dict(mod.TARGETS)["DM_REVIEW.OBSOLETE_FILE_PATH"]))
    got = (await db.execute(text('SELECT "OBSOLETE_FILE_PATH" FROM "DM_REVIEW"'))).scalar_one()
    assert got == "DM-SOP-000900/abc.pdf"
