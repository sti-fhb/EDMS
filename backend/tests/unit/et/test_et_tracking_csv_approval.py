"""學員清單 CSV 的「核可狀態」格（#577）。

整合測試（`test_et_tracking.py::TestCsvApprovalColumn`）以真資料驗四種狀態與畫面一致；
本檔只釘住**對照表本身**——不需 DB。
"""

import pytest

from app.et.approval import rules as approval_rules
from app.et.tracking.service import APPROVAL_STATUS_LABEL, _approval_cell

pytestmark = pytest.mark.unit


def test_對照表涵蓋核可規則的每一個狀態常數() -> None:
    """日後 `approval.rules` 新增狀態時，這條會紅——否則 CSV 會印出英文代碼。

    以模組上 `STATUS_` 開頭的常數為母體，不手抄清單：手抄的清單跟對照表一起漏改時，
    這條照樣綠。
    """
    statuses = {v for k, v in vars(approval_rules).items() if k.startswith("STATUS_")}
    assert statuses, "找不到任何 STATUS_ 常數——母體為空時本測試恆真"
    assert set(APPROVAL_STATUS_LABEL) == statuses


def test_不需核可的課程填破折號_不是空字串也不是任何核可狀態() -> None:
    """`None` ＝ 課程不需核可（#577 Q1 裁示 A）。"""
    cell = _approval_cell(None)
    assert cell == "—"
    assert cell != ""
    assert cell not in APPROVAL_STATUS_LABEL.values()


@pytest.mark.parametrize(
    ("status", "text"),
    [("NOT_ELIGIBLE", "未達核可資格"), ("PENDING", "待核可"), ("PASSED", "已通過"), ("FAILED", "未通過")],
)
def test_四種狀態的文字與畫面相同(status: str, text: str) -> None:
    """文字對照 `frontend/src/et/students/StudentListBlock.tsx`；兩邊改字時要同步。"""
    assert _approval_cell(status) == text
