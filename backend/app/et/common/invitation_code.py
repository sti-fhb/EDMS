"""ET 課程邀請碼產生器（T032）。

邀請碼為**純數字**、全域唯一，於課程**發布時**產生（草稿無碼），發布後永久不可變更。
長度由 `DP_PARAM.ET_INVITATION_CODE_LENGTH` 控制（預設 8），呼叫端經平台
`ParamService` 讀取後傳入——本模組不直接讀參數，保持純函式可單元測試。

⚠️ **欄位長度上限**：`ET_COURSE.INVITATION_CODE` 為 `VARCHAR(8)` **硬編**，而長度來自
可調參數。若該參數被調大於 8，產出的碼將塞不進欄位。本模組於此 **fail-fast** 而非
靜默截斷——截斷會破壞唯一性假設並產生難以追查的碰撞。
（#171 已將該參數分級為 `READONLY`（僅 IT 可改），風險低但非零。）
"""

import secrets
from collections.abc import Callable

# 對應 ET_COURSE.INVITATION_CODE 之 VARCHAR(8)
INVITATION_CODE_MAX_LEN = 8

# 碰撞重產上限：8 碼數字有 1e8 種組合，連續 100 次撞上表示碼空間已近耗盡或
# exists 判定有誤，此時放棄並報錯，避免無限迴圈。
_MAX_ATTEMPTS = 100


def generate_invitation_code(*, length: int, exists: Callable[[str], bool]) -> str:
    """產生全域唯一之純數字邀請碼。

    Args:
        length: 碼長，來自 `DP_PARAM.ET_INVITATION_CODE_LENGTH`。
        exists: 唯一性判定 callable，回傳 True 表示該碼已被使用（呼叫端注入
            repository 查詢，使本函式保持純粹、可單元測試）。

    Raises:
        ValueError: `length` 不合法（< 1 或超過欄位上限）。
        RuntimeError: 連續碰撞達上限仍取不到未使用之碼。
    """
    if length < 1:
        raise ValueError("邀請碼長度須至少 1")
    if length > INVITATION_CODE_MAX_LEN:
        raise ValueError(
            f"邀請碼長度 {length} 超過 ET_COURSE.INVITATION_CODE 欄位上限 {INVITATION_CODE_MAX_LEN}；"
            "請調整 DP_PARAM.ET_INVITATION_CODE_LENGTH 或先擴充欄位長度"
        )

    for _ in range(_MAX_ATTEMPTS):
        # 逐位取亂數而非 randrange，確保前導零之碼（如 00123456）同樣可產生，
        # 使碼空間完整為 10^length。
        code = "".join(str(secrets.randbelow(10)) for _ in range(length))
        if not exists(code):
            return code

    raise RuntimeError(f"連續 {_MAX_ATTEMPTS} 次產生之邀請碼皆已被使用，請確認碼空間是否耗盡")
