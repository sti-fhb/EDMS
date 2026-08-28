"""`AppError.extra`——讓錯誤帶結構化細節（#204）。

加入的動機是 ET 發布檢核：spec AC 26 要求「提示**具體缺漏項目**」，而錯誤回應原本
只有 `error_code` / `error_message` 兩個字串欄位，塞不下一份清單。

與其在 core 再開一個 ET 專用欄位（繼 `retry_after` 之後的第二個特例），改為一般化：
任何模組都能用 `extra` 帶自己的結構化細節。
"""

import pytest

from app.core.exceptions import AppError

pytestmark = pytest.mark.unit


class TestAppErrorExtra:
    def test_預設為_None(self) -> None:
        assert AppError(status_code=400, detail="壞了").extra is None

    def test_保存傳入的內容(self) -> None:
        blockers = [{"code": "NO_TAG", "message": "至少 1 個標籤"}]
        error = AppError(
            status_code=422, detail="條件未滿足", error_code="ET_PUBLISH_001", extra={"blockers": blockers}
        )
        assert error.extra == {"blockers": blockers}

    @pytest.mark.parametrize("key", ["error_code", "error_message", "retry_after"])
    def test_與標準欄位相撞時建構失敗(self, key: str) -> None:
        """在**建構時**就擋下，而不是等到序列化才發現。

        若放行，`extra` 會在 handler 的 `content.update()` 蓋掉標準欄位——前端拿到的
        `error_code` 就成了呼叫端隨手塞的值，而這種錯誤只會在該條錯誤路徑真的被觸發
        時才浮現，極難追查。
        """
        with pytest.raises(ValueError, match="不得覆寫標準欄位"):
            AppError(status_code=400, detail="壞了", extra={key: "偷換"})

    def test_空_dict_不視為相撞(self) -> None:
        assert AppError(status_code=400, detail="壞了", extra={}).extra == {}

    def test_retry_after_維持獨立參數(self) -> None:
        """`retry_after` 早於 `extra` 存在且已有多處呼叫端，不併入 `extra`。"""
        error = AppError(status_code=429, detail="太頻繁", retry_after=30)
        assert error.retry_after == 30
        assert error.extra is None
