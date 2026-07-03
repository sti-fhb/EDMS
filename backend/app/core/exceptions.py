from fastapi import HTTPException


class AppError(HTTPException):
    """統一錯誤處理，禁止自訂其他例外 class。

    Args:
        status_code: HTTP 狀態碼。
        detail: 錯誤訊息（內部 debug 用，同時作為 error_message 回傳）。
        error_code: 標準化錯誤代碼（依 docs/ref/error-codes.md），預設 "UNKNOWN"。
    """

    def __init__(self, status_code: int, detail: str, error_code: str = "UNKNOWN") -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code
