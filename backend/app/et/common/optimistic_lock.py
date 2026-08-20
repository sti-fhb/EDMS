"""樂觀鎖檢核工具（T028）。

ET 之課程 / 章節 / 項目 / 測驗 / 題目 / 問卷各表持有 `VERSION` 欄位，寫入時以
`WHERE VERSION = :expected` 更新；若影響列數為 0，表示該列已被他人先行修改
（或已被刪除），即為版本衝突。

多裝置同時編輯課程之並發策略見 docs/specs/et/plan.md §並發控制策略。
"""

from app.core.exceptions import AppError


def ensure_version_matched(*, rowcount: int, entity: str) -> None:
    """樂觀鎖更新後檢核；影響列數為 0 即視為版本衝突。

    Args:
        rowcount: `UPDATE ... WHERE VERSION = :expected` 之影響列數。
        entity: 實體名稱，僅供呼叫端日誌／除錯辨識，**不進錯誤訊息**
            （per sti-error-codes：error_message 不得嵌入動態值或欄位名稱，
            防 Log Injection、不洩露 schema）。

    Raises:
        AppError: 版本不符（409 `ET_LOCK_001`）。
    """
    if rowcount == 0:
        raise AppError(
            status_code=409,
            detail="資料已被其他使用者修改，請重新載入後再試",
            error_code="ET_LOCK_001",
        )
