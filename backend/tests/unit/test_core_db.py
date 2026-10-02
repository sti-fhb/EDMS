"""engine 連線設定的單元測試（#483 第 3 項）。

## 為何這些斷言不放在整合測試

`tests/integration/test_core_db_timezone.py` 連真 DB 驗 `date()` 的日界，但那條**在開發機上
擋不住回歸**——本專案開發機的 PostgreSQL server 預設本來就是 `Asia/Taipei`，把
`create_app_engine` 的設定整段拔掉，該檔三條仍全數通過（已實測）。

能無條件擋住的只有「設定有沒有被組進 connect_args」這件事本身，而它不需要 DB
（`sti-testing.md`：拿掉真 DB 還驗得了 → 寫 unit）。
"""

import pytest

from app.core.db import _build_connect_args

pytestmark = pytest.mark.unit


def test_未指定時帶入台灣時區():
    """預設情況下 `server_settings.timezone` 必為 `Asia/Taipei`。"""
    assert _build_connect_args(None)["server_settings"]["timezone"] == "Asia/Taipei"


def test_呼叫端既有的_server_settings_不被蓋掉():
    """合併而非覆寫——呼叫端另外設定的連線參數要留著。"""
    merged = _build_connect_args({"server_settings": {"application_name": "edms-worker"}})

    assert merged["server_settings"] == {"timezone": "Asia/Taipei", "application_name": "edms-worker"}


def test_呼叫端顯式指定的時區優先():
    """顯式覆寫才蓋得掉預設值；測試要模擬其他部署環境時靠的就是這條。"""
    assert _build_connect_args({"server_settings": {"timezone": "UTC"}})["server_settings"]["timezone"] == "UTC"


def test_不就地修改傳入的_dict():
    """回傳新物件（專案 immutability 規範）；呼叫端的 dict 不得被動到。"""
    original: dict = {"server_settings": {"application_name": "x"}}

    _build_connect_args(original)

    assert original == {"server_settings": {"application_name": "x"}}
