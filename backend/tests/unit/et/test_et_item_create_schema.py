"""`ItemCreateReq` 的名稱必填（#414）。

2026-09-23 手測回報：教師把測驗編輯到一半、名稱還沒填就離開，那個沒有名稱的項目
留在章節裡。

追查結果**不是** `QuizDialog` 的驗證漏掉——它有驗（`handleSaveSettings` 第一行就擋
空名稱）。問題在更上游：按下「新增項目」的當下就以空名稱在 DB 建了空殼，而前端的
清理只掛在「取消」上，換頁 / 重新整理 / 按「儲存草稿」都會把它留下。

本檔把門檻釘在建立當下。**前端另有一道**（建立前先問名稱），兩者方向不同：前端擋的
是誤用、後端擋的是繞過。
"""

import pytest
from pydantic import ValidationError

from app.et.course.schemas import ITEM_TITLE_MAX_LEN, ItemCreateReq

pytestmark = pytest.mark.unit


class TestItemCreateReqTitle:
    def test_有名稱者照常建立(self) -> None:
        req = ItemCreateReq(item_type="QUIZ", title="第一章小考")
        assert req.title == "第一章小考"

    def test_前後空白被去除(self) -> None:
        assert ItemCreateReq(item_type="MATERIAL", title="  採血流程  ").title == "採血流程"

    def test_未帶名稱即拒絕(self) -> None:
        """2026-08-27 起 `title` 有 `default=""`，本次（#414）收回。

        ⛔ 不要把 `default` 加回來——那等於把「沒有名稱的項目」重新變成建得出來的狀態。
        """
        with pytest.raises(ValidationError):
            ItemCreateReq(item_type="QUIZ")  # type: ignore[call-arg]

    def test_空字串即拒絕(self) -> None:
        with pytest.raises(ValidationError):
            ItemCreateReq(item_type="QUIZ", title="")

    def test_全空白即拒絕(self) -> None:
        """🔴 `min_length=1` 擋不掉「   」——它有長度。

        而全空白與留空對教師、對發布檢核（`BLOCK_ITEM_NO_TITLE` 判的是 `strip()`）
        都沒有差別，故 `_strip_title` 要在 strip 之後再判一次。
        """
        with pytest.raises(ValidationError):
            ItemCreateReq(item_type="MATERIAL", title="   ")

    def test_超過長度上限即拒絕(self) -> None:
        with pytest.raises(ValidationError):
            ItemCreateReq(item_type="MATERIAL", title="ｘ" * (ITEM_TITLE_MAX_LEN + 1))

    def test_恰好等於長度上限可通過(self) -> None:
        # 邊界的另一側——只驗超過會讓 `max_length` 寫成 `-1` 也照樣綠
        title = "ｘ" * ITEM_TITLE_MAX_LEN
        assert ItemCreateReq(item_type="MATERIAL", title=title).title == title
