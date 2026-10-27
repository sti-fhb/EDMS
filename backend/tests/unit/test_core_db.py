"""engine 連線設定的單元測試（#483 第 3 項：時區；#810 第 2 項：查詢逾時）。

## 為何這些斷言不放在整合測試

`tests/integration/test_core_db_timezone.py` 連真 DB 驗 `date()` 的日界，但那條**在開發機上
擋不住回歸**——本專案開發機的 PostgreSQL server 預設本來就是 `Asia/Taipei`，把
`create_app_engine` 的設定整段拔掉，該檔三條仍全數通過（已實測）。

能無條件擋住的只有「設定有沒有被組進 connect_args」這件事本身，而它不需要 DB
（`sti-testing.md`：拿掉真 DB 還驗得了 → 寫 unit）。
"""

import ast
from pathlib import Path

import pytest

from app.core.config import Settings, settings
from app.core.db import _build_connect_args

pytestmark = pytest.mark.unit


def test_未指定時帶入台灣時區():
    """預設情況下 `server_settings.timezone` 必為 `Asia/Taipei`。"""
    assert _build_connect_args(None)["server_settings"]["timezone"] == "Asia/Taipei"


def test_呼叫端既有的_server_settings_不被蓋掉():
    """合併而非覆寫——呼叫端另外設定的連線參數要留著。"""
    merged = _build_connect_args({"server_settings": {"application_name": "edms-worker"}})

    assert merged["server_settings"] == {
        "timezone": "Asia/Taipei",
        "statement_timeout": str(settings.DB_STATEMENT_TIMEOUT_MS),
        "application_name": "edms-worker",
    }


def test_呼叫端顯式指定的時區優先():
    """顯式覆寫才蓋得掉預設值；測試要模擬其他部署環境時靠的就是這條。"""
    assert _build_connect_args({"server_settings": {"timezone": "UTC"}})["server_settings"]["timezone"] == "UTC"


def test_不就地修改傳入的_dict():
    """回傳新物件（專案 immutability 規範）；呼叫端的 dict 不得被動到。"""
    original: dict = {"server_settings": {"application_name": "x"}}

    _build_connect_args(original)

    assert original == {"server_settings": {"application_name": "x"}}


def test_未指定時帶入查詢逾時():
    """單一查詢最多跑 `DB_STATEMENT_TIMEOUT_MS`（#810）。不設的話，一個慢查詢可佔住連線到它跑完為止，
    連線池只有 15 條；而 nginx 逾時回 504 之後後端仍會跑完，nginx 那層保護不了連線池。"""
    assert _build_connect_args(None)["server_settings"]["statement_timeout"] == str(settings.DB_STATEMENT_TIMEOUT_MS)


def test_查詢逾時預設為_60_秒():
    """預設值本身也釘住：改成更短會讓正常但慢的操作（匯出、對大量學員發布）出錯，要有意識地改。"""
    # 讀欄位的預設值而非執行期的 settings：本機 .env 設了別的值時這條不該紅（review LOW）
    assert Settings.model_fields["DB_STATEMENT_TIMEOUT_MS"].default == 60_000


def test_呼叫端顯式指定的查詢逾時優先():
    """migration 靠這條關掉逾時（見下一條）。"""
    merged = _build_connect_args({"server_settings": {"statement_timeout": "0"}})

    assert merged["server_settings"]["statement_timeout"] == "0"


def test_migration_的_engine_關閉查詢逾時():
    """回填大量資料的 migration 可能單句超過 60 秒；被中斷的話部署卡在半途。

    `alembic/env.py` 也經 `create_app_engine` 建 engine（為了日界一致，#483），會吃到預設逾時，
    故必須顯式傳 `statement_timeout: "0"`。以 AST 檢查，不靠字串比對：註解或別的呼叫裡出現同一段字
    不算數。
    """
    env = Path(__file__).resolve().parents[2] / "alembic" / "env.py"
    calls = [
        n
        for n in ast.walk(ast.parse(env.read_text(encoding="utf-8")))
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "create_app_engine"
    ]
    assert calls, "正向錨點：alembic/env.py 應以 create_app_engine 建 engine"

    def statement_timeout(call: ast.Call):
        kw = next((k for k in call.keywords if k.arg == "connect_args"), None)
        if kw is None:
            return None
        return ast.literal_eval(kw.value).get("server_settings", {}).get("statement_timeout")

    assert [statement_timeout(c) for c in calls] == ["0"] * len(calls)
