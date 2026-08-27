"""待驗證列（`DP_PENDING_REGISTRATION.KIND`）之值域——DP 模組內單一定義（#137）。

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
歷史快照，不應依賴 app 常數，否則改常數會回頭改變既有 migration 的語意）。另外，值域
**未在 DB 層封閉**（`KIND` 為 VARCHAR、無 CHECK），故本護欄證明的是「只定義一次」，
不是「只有這兩個值進得了 DB」。
"""

# US2 自助註冊：**不帶 PWD_HASH**（#212），密碼由本人於驗證步當場設定
KIND_SELF_REGISTER = "SELF_REGISTER"

# US4 管理者邀請：建立時 PWD_HASH 為 NULL，受邀者於啟用連結自設密碼才回填
KIND_ADMIN_INVITE = "ADMIN_INVITE"
