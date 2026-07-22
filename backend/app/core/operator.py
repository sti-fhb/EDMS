"""操作者資訊 Dependency（寫入型 API 填 CREATED_* / UPDATED_* 標準欄位用）。

寫入型端點（POST / PUT / PATCH / DELETE）一律注入 `get_operator` 取得操作者，
禁止直接讀 `payload.sub` 填欄位（見 sti-backend-modules）。EDMS 為單一組織、
無站點維度，故 OperatorInfo 僅含 user_id。

暫行授權規則（全域授權機制實作前）：寫入型端點只注入本 Dependency（內部已經
get_jwt_payload 完成認證），不加 require_admin / require_module_admin。
"""

from dataclasses import dataclass

from fastapi import Depends

from app.core.auth import JwtPayload, get_jwt_payload


@dataclass(frozen=True)
class OperatorInfo:
    """寫入操作者資訊：目前僅需 USER_ID（單一組織、無 site）。"""

    user_id: str


async def get_operator(payload: JwtPayload = Depends(get_jwt_payload)) -> OperatorInfo:
    """取得操作者資訊 Dependency（內部經 get_jwt_payload 完成認證與 DP_USER 狀態檢核）。"""
    return OperatorInfo(user_id=payload.sub)
