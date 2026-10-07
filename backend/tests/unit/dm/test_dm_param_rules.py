"""DM 模組級參數值域（#528）。

斷言走 `validate_param_value`（DP 實際用的那條路）而非只檢查 registry 有沒有東西：
忘了註冊時回的是 403 `DP_PARAM_008`（查無規則）而非 422 `DP_PARAM_001`，兩者分得開。
"""

import pytest

from app.core.exceptions import AppError
from app.dm.bootstrap import register_dm_module
from app.dm.params import REMIND_THRESHOLD_PARAM_ID
from app.dm.review.center_service import REMIND_THRESHOLD_PARAM
from app.dp.params.param_rules import validate_param_value

pytestmark = pytest.mark.unit

_PARAM = ("DM_REMIND_THRESHOLD", "VALUE")


def test_註冊的_param_id_與讀取端一致():
    """守門掛的鍵若與實際讀取的字串不同，它會守在一個沒有人讀的參數上——靜默失效。

    DM 有三處讀這個參數（簽核中心、催辦排程、個人專區）。前兩處共用
    `center_service.REMIND_THRESHOLD_PARAM`，第三處原本硬寫字串、已於 #528 改為
    import 同一個常數（守門使這個字串變成承重的，第四份副本是分歧風險）。
    """
    assert REMIND_THRESHOLD_PARAM == REMIND_THRESHOLD_PARAM_ID
    assert _PARAM[0] == REMIND_THRESHOLD_PARAM_ID


@pytest.fixture(autouse=True)
def _registered():
    """冪等註冊；`main.py` 於啟動期已呼叫過，此處確保單獨跑本檔時亦成立。"""
    register_dm_module()


@pytest.mark.parametrize("value", ["1", "7", "30"])
def test_合法值通過(value):
    """值域 1–30 由 DM spec 明載（`docs/specs/dm/research.md` 與 `issues.md`），非本次發明。"""
    validate_param_value(*_PARAM, value)


@pytest.mark.parametrize("value", ["0", "-1"])
def test_零與負數被拒(value):
    """這是本 issue 最嚴重的那一條：門檻 ≤ 0 會讓催辦每日轟炸所有待簽核項目。

    `dm/review/repository.py` 以 `cutoff = utcnow() - timedelta(days=threshold_days)`
    取門檻，條件為 `DmReview.submit_date <= cutoff`：

    - `0` → cutoff 就是 now → **所有 PENDING 都符合**
    - `-1` → cutoff 落在明天 → 同樣全中

    而 DM 側沒有 `REMIND_SENT` 之類的防重複旗標（ET 有），排程 `SCHDM002` 每日執行，
    所以每個待簽核項目的審核者**每天都會收到催辦信且不會停**。

    ⚠️ 與 ET 的 `ET_URGENT_REMIND_DAYS` 不同：那支的 0 是刻意的停用語意、必須放行。
    兩個參數的下限本來就不一樣——這正是值域由各模組自己定義（而非 DP 一張表）的理由。
    """
    with pytest.raises(AppError) as exc:
        validate_param_value(*_PARAM, value)
    assert exc.value.status_code == 422
    assert exc.value.error_code == "DP_PARAM_001"


def test_超過上限被拒():
    """設大 → cutoff 落在很久以前 → 幾乎沒有項目符合 → 催辦靜默停擺。"""
    with pytest.raises(AppError) as exc:
        validate_param_value(*_PARAM, "31")
    assert exc.value.error_code == "DP_PARAM_001"
