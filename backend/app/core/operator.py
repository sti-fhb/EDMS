"""操作者資訊 Dependency（寫入型 API 填 CREATED_* / UPDATED_* 標準欄位用）。

寫入型端點（POST / PUT / PATCH / DELETE）一律注入 `get_operator` 取得操作者，
禁止直接讀 `payload.sub` 填欄位（見 sti-backend-modules）。EDMS 為單一組織、
無站點維度，故 OperatorInfo 僅含 user_id。

**本 Dependency 只負責「取操作者」，不是授權閘**（內部僅經 `get_jwt_payload` 完成認證）。
授權另掛：DP 後台端點於 router-level 掛 `require_any_module_admin()`、業務模組端點掛各自
的存取閘（如 DM 的 `get_dm_context`）。#250 之前的「暫行授權規則」（寫入型只注入本
Dependency、不加 admin 閘）已廢止，詳見 `.claude/rules/sti-backend-modules.md` §授權規則。
"""

from dataclasses import dataclass

from fastapi import Depends

from app.core.auth import JwtPayload, get_jwt_payload, get_jwt_payload_pwd_exempt


@dataclass(frozen=True)
class OperatorInfo:
    """寫入操作者資訊：目前僅需 USER_ID（單一組織、無 site）。"""

    user_id: str


async def get_operator(payload: JwtPayload = Depends(get_jwt_payload)) -> OperatorInfo:
    """取得操作者資訊 Dependency（內部經 get_jwt_payload 完成認證與 DP_USER 狀態檢核）。"""
    return OperatorInfo(user_id=payload.sub)


async def get_operator_pwd_exempt(payload: JwtPayload = Depends(get_jwt_payload_pwd_exempt)) -> OperatorInfo:
    """**逃生門**版的 `get_operator`：不檢查密碼是否須變更（#929）。

    ⛔ **目前唯一合法的使用者是 `PUT /dp/user/me/password`**——它是寫入型端點（需
    `OperatorInfo` 填稽核欄位），又必須在「須變更密碼」狀態下可用，否則使用者永遠改不了
    密碼。其餘白名單端點都是讀取型，用 `get_jwt_payload_pwd_exempt` 即可。

    新增使用者前先問：這支端點**不改密碼也非登出**，為什麼須變更密碼的人非用不可？
    答不出來就不該用這一支。白名單的完整理由見 `get_jwt_payload_pwd_exempt`。
    """
    return OperatorInfo(user_id=payload.sub)
