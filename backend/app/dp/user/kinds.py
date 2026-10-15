r"""待驗證列（`DP_PENDING_REGISTRATION.KIND`）之值域——DP 模組內單一定義（#137）。

⚠️ **`KIND_ADMIN_INVITE` 是安全不變量，不是普通字串常數。**

`register_service` 的守衛（「Email 有未逾期的管理者邀請 → 擋下自助註冊」）與
`repository.delete_pending_unless_active_invite` 的條件式刪除（「未逾期邀請不刪」）
**必須命中同一個值**，#125 的修補才成立：

- 只改到守衛 → 守衛永不觸發，退化為靠 UNIQUE 撞出 409，訊息難看但資料不會掉
- 只改到條件式刪除 → TOCTOU 窗口回歸 #125 原本的 bug，管理者發出的邀請會被匿名的
  自助註冊**靜默吃掉**（邀請從清單消失、原邀請信連結失效，且管理者毫無感知）

原本這兩個值分散在四個檔案各自定義，沒有任何機制保證一致。集中於此後，
`tests/unit/dp/test_dp_user_pending_kinds.py` 會掃 `backend/app` 確保字面量不再出現於他處——
要改值只能改這裡，改動者也就看得到上面的代價說明。

護欄的射程僅及於 `backend/app`：`alembic/versions/` 內的字面量刻意不納入（migration 是
歷史快照，不應依賴 app 常數，否則改常數會回頭改變既有 migration 的語意）。

## 值域如何被封閉（#215）

本護欄證明的是「**只定義一次**」；「**只有這兩個值進得了 DB**」由另一道負責——
`CK_DP_PENDING_REGISTRATION_KIND`（`alembic` 之 `b4e7c91d2a36`，ORM 側同步宣告於
`models.py`）。兩者互補、非替代：

- 少了本護欄：值被複製到各處後各自漂移，#125 的兩個守衛可能命中不同字串
- 少了 CHECK：打錯字的值**寫得進去**，而那一列在所有 UI 上都看不見卻佔住 `EMAIL` 唯一鍵，
  使管理者代建該 Email 恆回誤導的 409，且連取消都做不到（取消邀請需 `invite_id`，
  而該列不在清單上）

⚠️ 應用層**沒有**等價的執行期斷言，是刻意的：#215 的危害正來自「日後新增、繞過
`AuthRepository` 的寫入路徑」，而應用層守不住那一類。`create_pending_registration` 的
`kind` 參數雖有 `Literal` 標註，那只提供閱讀時的提示——CI 無 mypy，不具強制力，
**勿視之為守門**。

## 新增一個 KIND 值時，要一併檢查的地方

值域已於 DB 封閉 ⇒ 新增值**必然需要一支 migration** 改 `CK_DP_PENDING_REGISTRATION_KIND`
（改這裡的常數不夠）。那一步是 fail-loud 的，會立刻發現。

**真正會漏的是其餘讀取端。** 清單寫死檔名行號必然過期，故改以可重跑的指令取得：

```bash
grep -rn "KIND_ADMIN_INVITE\|KIND_SELF_REGISTER" backend/app --include=*.py
```

每一處命中都屬於下列四類之一，**新增值時逐類問一次「新 kind 該落在哪一邊」**：

| 類別 | 漏改的後果 |
|------|-----------|
| **清單過濾**（`user/repository.build_invite_list_stmt` 等）| 新 kind 的列在 UI 上**完全看不見** |
| **條件式刪除**（`user/repository.delete_pending_unless_active_invite`）| 新 kind 的列會被自助註冊**靜默覆蓋** |
| **啟用端點的 `expected_kind`**（兩支共用 `activation.py`）| 新 kind 的連結一律被判無效 |
| **Email 佔用判定**（`users/service.create_user`）| 管理者代建對該 Email 回誤導的 409 |

另需同步 `docs/specs/dp/data-model.md` 的 `KIND` 欄位說明與 CHECK 約束名。

⚠️ 四類的共同形狀是「**拿 `== KIND_ADMIN_INVITE` 當作二分法**」——程式裡沒有「其他 kind」
這個分支。新增第三個值時，每一處都得決定它屬於哪一側，而**預設落到 else 那側**
（＝被當成自助註冊處理），那通常不是你要的。
"""

from typing import Literal

# US2 自助註冊：**不帶 PWD_HASH**（#212），密碼由本人於驗證步當場設定
KIND_SELF_REGISTER = "SELF_REGISTER"

# US4 管理者邀請：建立時 PWD_HASH 為 NULL，受邀者於啟用連結自設密碼才回填
KIND_ADMIN_INVITE = "ADMIN_INVITE"

# 寫入端的型別標註用。字面量在本檔重複一次是刻意的：`Literal` 需要語法上的字面量，
# 不能帶入常數；而 #137 的護欄只禁止 `kinds.py` **以外**出現，故別名必須定義在這裡，
# 否則 `repository.py` 自己寫 `Literal["SELF_REGISTER", ...]` 會讓護欄測試變紅。
#
# ⛔ **這不是守門**：CI 無 mypy，型別標註不具強制力。值域的強制來自
# `CK_DP_PENDING_REGISTRATION_KIND`（見上）。本別名只讓錯誤在**讀程式碼**時看得出來。
PendingKind = Literal["SELF_REGISTER", "ADMIN_INVITE"]
