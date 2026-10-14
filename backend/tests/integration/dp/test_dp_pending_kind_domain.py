"""`DP_PENDING_REGISTRATION.KIND` 值域於 DB 層封閉（#215）。

#137 的護欄（`tests/unit/dp/test_dp_user_pending_kinds.py`）證明的是「**同一個值只定義一次**」，
不是「只有這兩個值進得了 DB」。兩者互補、非替代：

- #137：改值只能改 `kinds.py`，改動者看得到代價說明
- 本檔：**打錯字的值根本寫不進去**，不論經哪一條路徑

為什麼值得在 DB 層擋（#215 的立論）：一筆 `KIND='ADMIN-INVITE'`（連字號 typo）的列
在**所有 UI 上都看不見**——邀請清單濾 `KIND='ADMIN_INVITE'` 撈不到、`DP_USER` 也查不到，
但它佔住 `EMAIL` 的唯一鍵，使管理者代建該 Email 恆回誤導的 409「此 Email 已被註冊」。
管理者連取消它都做不到（取消邀請需 `invite_id`，而該列不在清單上、UI 拿不到 id）。
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.utils import utcnow
from app.dp.user.kinds import KIND_ADMIN_INVITE, KIND_SELF_REGISTER

pytestmark = pytest.mark.integration

_CONSTRAINT = "CK_DP_PENDING_REGISTRATION_KIND"

# 走 raw SQL 而非 ORM：本檔驗的是 **DB 約束**本身。經 ORM 寫入時，若日後有人在
# Python 層補了一道檢查，這條測試會因為那道檢查而紅——看起來一樣綠燈，但驗到的
# 是另一件事（而 #215 的立論正是「繞過 repository 的路徑」）。
_INSERT = text(
    'INSERT INTO "DP_PENDING_REGISTRATION" '
    '("TOKEN_HASH", "EMAIL", "USER_NAME", "PWD_HASH", "KIND", "EXPIRES_DATE", '
    ' "INVITE_ID", "CREATED_USER", "CREATED_DATE") '
    "VALUES (:token_hash, :email, :user_name, NULL, :kind, :expires_date, "
    " NULL, :created_user, :created_date)"
)


async def _insert(db, *, kind: str, email: str, token: str):
    now = utcnow()
    return await db.execute(
        _INSERT.bindparams(
            token_hash=token,
            email=email,
            user_name="值域測試",
            kind=kind,
            expires_date=now,
            created_user="zt-kind",
            created_date=now,
        )
    )


@pytest.mark.parametrize(
    "bad_kind",
    [
        "ADMIN-INVITE",  # 連字號 typo —— #215 body 舉的例子
        "admin_invite",  # 大小寫錯
        "SELF_REGISTE",  # 少一字
        "",  # 空字串（NOT NULL 擋不住）
    ],
)
async def test_未知_kind_寫入被_DB_拒絕(db, bad_kind: str) -> None:
    """值域外的 `KIND` 一律被 DB 擋下，不論打錯的形式。

    空字串特別列入：`KIND` 是 `NOT NULL`，但 `NOT NULL` 對空字串無效——
    少了 CHECK 就會寫進去，且它在任何 `KIND = '...'` 的過濾下都撈不到。
    """
    with pytest.raises(DBAPIError) as exc:
        await _insert(db, kind=bad_kind, email=f"zt-kind-{len(bad_kind)}@edms.local", token=f"zt{len(bad_kind):062d}")
    assert _CONSTRAINT in str(exc.value), f"應由 {_CONSTRAINT} 擋下，實得：{exc.value}"
    await db.rollback()


@pytest.mark.parametrize("good_kind", [KIND_SELF_REGISTER, KIND_ADMIN_INVITE])
async def test_兩個合法_kind_仍可寫入(db, good_kind: str) -> None:
    """正向錨點：證明上面那條「被拒絕」不是因為 INSERT 本身就寫不進去。

    少了這條，把 `_INSERT` 寫壞（欄位名打錯之類）也會讓上面四條**全部通過**——
    那是「對錯誤回應做否定斷言」的同一種假證據。
    """
    result = await _insert(db, kind=good_kind, email=f"zt-ok-{good_kind.lower()}@edms.local", token=f"zt1{good_kind:0>61}")
    assert result.rowcount == 1
    await db.rollback()
