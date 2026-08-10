"""權限管理（dp-roles）轉接層 schema（US7）。

DP 為轉接層、不自持角色/指派資料；本檔僅定義 DP 端點之請求 / 回應形狀，
實際 roles / groups 語意與寫入由各模組 provider 落地（module-callbacks §3）。
"""

from datetime import datetime

from pydantic import BaseModel


class AssignmentItem(BaseModel):
    """單一使用者於某模組之角色 / 群組現況（權限管理列）。"""

    user_id: str
    user_name: str
    email: str
    roles: list[str]
    groups: list[str]  # DM＝可見對象 TAG_ID；ET＝受訓單位標籤代碼
    last_modified_by: str | None = None  # 最後異動者 USER_ID（原始碼）
    last_modified_by_name: str | None = None  # 最後異動者顯示名（姓名，無則 email；查無則 None）
    last_modified_date: datetime | None = None


class AssignPayload(BaseModel):
    """儲存單一使用者之目標角色 + 群組集合（兩維度獨立、各自為完整目標集）。"""

    roles: list[str]
    groups: list[str]


class GroupOption(BaseModel):
    """群組可選項（DM 可見對象 / ET 受訓單位標籤）。"""

    code: str
    name: str
