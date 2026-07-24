from fastapi import HTTPException


class AppError(HTTPException):
    """統一錯誤處理，禁止自訂其他例外 class。

    Args:
        status_code: HTTP 狀態碼。
        detail: 錯誤訊息（內部 debug 用，同時作為 error_message 回傳）。
        error_code: 標準化錯誤代碼（依 docs/ref/error-codes.md），預設 "UNKNOWN"。
        retry_after: 選填；限流 / 冷卻類 429 的「可重試剩餘秒數」，供前端倒數。有值時由
            app_error_handler 併入回應 body。
    """

    def __init__(
        self, status_code: int, detail: str, error_code: str = "UNKNOWN", *, retry_after: int | None = None
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code
        self.retry_after = retry_after
