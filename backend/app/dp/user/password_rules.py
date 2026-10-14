"""密碼長度與字元種類門檻之共用判定（#623）。

特權帳號（ET 或 DM 任一模組管理者）套 `PWD_POLICY.ADMIN_MIN_LEN`（預設 12），其餘套
`PWD_POLICY.MIN_LEN`（預設 8）；字元種類一律 `PWD_POLICY.CHAR_TYPES`（預設 3）。

## 為什麼集中在這裡

原本只有變更密碼（`profile_service`）判斷管理者身分，忘記密碼重設只讀 `MIN_LEN`，管理者因此
可經忘記密碼繞過 12 字元；前端提示又只讀公開政策的 `min_len`，管理者照提示設 8～11 字元，
送出才被擋。**門檻在哪裡算，就要在每個設定密碼的入口與提示端點都用同一支**，否則提示、
前端檢核與後端檢核三者會再度各說各話。

## 判定失敗的方向

`module_admin_gate.is_module_admin` 為 fail-closed：判定未註冊或拋例外一律回 False，於是該帳號
套**一般**門檻。這個方向不會被使用者察覺（要求變寬鬆沒人抱怨），ET / DM 的判定現已於各自
`bootstrap.py` 註冊；若日後有人拔掉註冊，管理者會靜默退回 8 字元。
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.module_admin import module_admin_gate
from app.services import ParamService

_DEFAULT_MIN_LEN = 8
_DEFAULT_ADMIN_MIN_LEN = 12
_DEFAULT_CHAR_TYPES = 3
_PRIVILEGED_MODULES = ("ET", "DM")


@dataclass(frozen=True)
class PasswordRules:
    """某帳號設定新密碼時適用之門檻。"""

    min_len: int
    char_types: int


async def general_rules(db: AsyncSession, *, params: ParamService | None = None) -> PasswordRules:
    """一般使用者門檻：給不知道是誰、或帳號尚無任何角色的情境（註冊 / 啟用帳號）。

    Args:
        db: 資料庫 session。
        params: 參數服務（測試注入用）。

    Returns:
        以 `MIN_LEN` 與 `CHAR_TYPES` 組成之門檻。
    """
    params = params or ParamService()
    return PasswordRules(
        min_len=await params.get_int_param(db, "PWD_POLICY", "MIN_LEN", _DEFAULT_MIN_LEN),
        char_types=await params.get_int_param(db, "PWD_POLICY", "CHAR_TYPES", _DEFAULT_CHAR_TYPES),
    )


async def rules_for_user(db: AsyncSession, user_id: str, *, params: ParamService | None = None) -> PasswordRules:
    """指定帳號適用之門檻：ET 或 DM 任一模組管理者套 `ADMIN_MIN_LEN`，其餘同 `general_rules`。

    Args:
        db: 資料庫 session。
        user_id: 要設定新密碼的帳號。
        params: 參數服務（測試注入用）。

    Returns:
        該帳號適用之門檻。
    """
    params = params or ParamService()
    for module in _PRIVILEGED_MODULES:
        if await module_admin_gate.is_module_admin(module, user_id, db):
            return PasswordRules(
                min_len=await params.get_int_param(db, "PWD_POLICY", "ADMIN_MIN_LEN", _DEFAULT_ADMIN_MIN_LEN),
                char_types=await params.get_int_param(db, "PWD_POLICY", "CHAR_TYPES", _DEFAULT_CHAR_TYPES),
            )
    return await general_rules(db, params=params)
