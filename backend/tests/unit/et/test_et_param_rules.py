"""ET 模組級參數值域（#528）。

斷言走 `validate_param_value`（DP 實際用的那條路）而非只檢查 registry 有沒有東西：
忘了註冊時回的是 403 `DP_PARAM_008`（查無規則）而非 422 `DP_PARAM_001`，兩者分得開。
"""

import pytest

from app.core.exceptions import AppError
from app.dp.params.param_rules import validate_param_value
from app.et.bootstrap import register_et_module
from app.et.params import URGENT_REMIND_DAYS_PARAM_ID
from app.et.schedules.service import _URGENT_PARAM_ID as _SCHEDULES_PARAM_ID
from app.et.stats.service import _URGENT_PARAM_ID as _STATS_PARAM_ID

pytestmark = pytest.mark.unit

_PARAM = ("ET_URGENT_REMIND_DAYS", "VALUE")


@pytest.fixture(autouse=True)
def _registered():
    """冪等註冊；`main.py` 於啟動期已呼叫過，此處確保單獨跑本檔時亦成立。"""
    register_et_module()


@pytest.mark.parametrize("value", ["0", "1", "3", "30"])
def test_合法值通過(value):
    validate_param_value(*_PARAM, value)


def test_零是刻意保留的停用語意():
    """`urgent_days = 0` 等於停用加急提醒，是有文件記載的功能，不可被值域守門擋掉。

    依據 `app/et/schedules/rules.py` 的 `needs_urgent_remind` docstring：

        `urgent_days = 0` 因「已到期」閘而等於停用加急提醒（窗口寬度為零，且訖止當下
        已被前一個閘擋下）——這是合理的停用語意，不該變成「全部都寄」。

    ⚠️ #528 的 AC1 原文是「至少擋負數與零」，本條刻意偏離（已於該 issue 留言記錄裁示）。
    把下限改成 1 會讓這條紅——那正是它的用途。
    """
    validate_param_value(*_PARAM, "0")


def test_註冊的_param_id_與讀取端一致():
    """守門掛的鍵若與實際讀取的字串不同，它會守在一個沒有人讀的參數上——靜默失效。

    ET 有兩處各自寫了同一個 PARAM_ID（排程 `SCHET002` 與教師統計），本條把三者釘在一起。
    改任一處的字串而沒改其他處，這條就紅。
    """
    assert _SCHEDULES_PARAM_ID == URGENT_REMIND_DAYS_PARAM_ID
    assert _STATS_PARAM_ID == URGENT_REMIND_DAYS_PARAM_ID
    assert _PARAM[0] == URGENT_REMIND_DAYS_PARAM_ID


@pytest.mark.parametrize("value", ["-1", "31"])
def test_非法值被拒(value):
    """負數：同樣是靜默停用，但沒有任何文件說它該這樣，是重複且令人困惑的第二條停用路徑。

    超過 30：窗口大於課程長度時，所有課程一開課就收到「即將截止」；且超過一個月已經
    不是「加急」。
    """
    with pytest.raises(AppError) as exc:
        validate_param_value(*_PARAM, value)
    assert exc.value.status_code == 422
    assert exc.value.error_code == "DP_PARAM_001"
