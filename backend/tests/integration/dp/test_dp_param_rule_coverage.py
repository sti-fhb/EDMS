"""值域規則涵蓋率掃描（#528）。

`validate_param_value` 的 docstring 宣告「今日不會誤傷任何參數——平台級全在 `_RULES`，
可編輯的模組級由各自 bootstrap 註冊」。那是**會過期的狀態宣告**：下一個人用 migration
新增一列 `EDIT_SCOPE='ADMIN'` 的 VALUE 參數而忘了補規則時，fail-closed 的「立刻現形」
要等到有人在 DP03 上踩到 403 才現形，**不會在 CI 現形**。

本檔把那句話變成可執行的斷言——正是本 issue 自己採取的哲學：文字要求要變成守門，
否則「已經有人確認過」的印象會蓋過實際狀態。
"""

import pytest
from sqlalchemy import select

from app.dp.params.models import DpParamDetail, DpParamMaster
from app.dp.params.param_rules import has_rule

pytestmark = pytest.mark.integration


async def test_每個可編輯的單值參數都查得到值域規則(db):
    """掃 `PARAM_TYPE='VALUE'` ∩ `EDIT_SCOPE='ADMIN'` 的所有明細，逐列斷言有規則。

    這組就是**實際會走到 `validate_param_value` 的全集**：
    - `LIST` 型不進值域檢核（`master.param_type == "VALUE"` 條件）
    - `READONLY` / `HIDDEN` 被 `is_editable_scope` 擋在更前面（403 `DP_PARAM_007`）

    失敗代表有人新增了可編輯的單值參數卻沒給值域——該參數在 DP03 上會是不可編輯的
    （403 `DP_PARAM_008`）。修法是補規則：平台級加進 `param_rules._RULES`，模組級於
    該模組的 `params.py` 定義並在 bootstrap 註冊。
    """
    stmt = (
        select(DpParamDetail.param_id, DpParamDetail.param_key)
        .join(DpParamMaster, DpParamMaster.param_id == DpParamDetail.param_id)
        .where(
            DpParamMaster.param_type == "VALUE",
            DpParamMaster.deleted == 0,
            DpParamDetail.edit_scope == "ADMIN",
            DpParamDetail.deleted == 0,
        )
        .order_by(DpParamDetail.param_id, DpParamDetail.param_key)
    )
    rows = (await db.execute(stmt)).all()

    # 母體不得為空，否則「全部都有規則」會是空集合上的恆真斷言（見 sti-testing 的假陽性）
    assert rows, "掃不到任何可編輯的單值參數——查詢條件或種子有問題，不是『全部合格』"

    missing = [(pid, key) for pid, key in rows if not has_rule(pid, key)]
    assert missing == [], f"以下可編輯的單值參數沒有值域規則，會在 DP03 上不可編輯：{missing}"
