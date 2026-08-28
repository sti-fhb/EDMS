from fastapi import HTTPException


class AppError(HTTPException):
    """統一錯誤處理，禁止自訂其他例外 class。

    Args:
        status_code: HTTP 狀態碼。
        detail: 錯誤訊息（內部 debug 用，同時作為 error_message 回傳）。
        error_code: 標準化錯誤代碼（依 docs/ref/error-codes.md），預設 "UNKNOWN"。
        retry_after: 選填；限流 / 冷卻類 429 的「可重試剩餘秒數」，供前端倒數。有值時由
            app_error_handler 併入回應 body。
        extra: 選填；併入回應 body 的額外欄位。用於「錯誤本身帶結構化細節」的情境——
            例如 ET 發布檢核未通過時，除了訊息還要回傳**具體缺漏項目清單**
            （`ET_PUBLISH_001`，spec AC 26 要求）。

            key 不得與 `error_code` / `error_message` / `retry_after` 相撞，否則會蓋掉
            標準欄位；`_STANDARD_KEYS` 於建構時即擋下，不留到執行期才發現。

            > `retry_after` 早於本參數存在且已有多處呼叫端，維持獨立參數不併入 `extra`。

    Raises:
        ValueError: `extra` 的 key 與標準欄位相撞。
    """

    #: 回應 body 的標準欄位；`extra` 不得覆寫。
    _STANDARD_KEYS = frozenset({"error_code", "error_message", "retry_after"})

    def __init__(
        self,
        status_code: int,
        detail: str,
        error_code: str = "UNKNOWN",
        *,
        retry_after: int | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)
        if extra:
            clashing = self._STANDARD_KEYS & extra.keys()
            if clashing:
                raise ValueError(f"AppError.extra 不得覆寫標準欄位：{sorted(clashing)}")
        self.error_code = error_code
        self.retry_after = retry_after
        self.extra = extra
