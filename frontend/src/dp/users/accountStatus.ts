/**
 * 帳號狀態判定（#250）。
 *
 * 對稱後端 `app/dp/users/account_status.py`。「已鎖定」一律由前端以 `locked_until > now`
 * 衍生——後端只回原始 `LOCKED_UNTIL`、不算「是否鎖定中」（見後端 `UserResponse` docstring：
 * 避免序列化時取系統時間）。使用者管理頁與權限管理頁共用本判定，避免兩份漂移。
 */

/** 帳號狀態兩維度（DP_USER.STATUS / LOCKED_UNTIL 的前端形狀）。 */
export interface AccountStatusFields {
  status: string
  locked_until: string | null
}

/**
 * 帳號是否已停用（需管理者手動啟用，不會自動恢復）。
 *
 * ⚠️ **判定是 `!== "ACTIVE"` 而非 `=== "DISABLED"`，方向不可反**（#603）。理由可重新推導：
 * `DP_USER.STATUS` 是 `String(10)`、**無 CHECK 約束**，日後新增第三種狀態時——
 *
 * - 後端 `account_status.py` 的 `is_account_disabled` 是 `status != "ACTIVE"`，會判定該帳號不可用
 * - 前端若寫 `=== "DISABLED"`，會判定它正常，畫面把一個**登不進系統的帳號標成綠色「啟用中」**
 *
 * 兩邊對同一筆資料得出相反結論，而且沒有任何東西會紅。fail-closed（寧可誤標成停用）才與後端同邊。
 */
export function isDisabled(row: AccountStatusFields): boolean {
  return row.status !== "ACTIVE"
}

/**
 * 這個 `status` 是不是前端認得的值（目前只有 `ACTIVE` / `DISABLED`）。
 *
 * 供**狀態操作**（停用 / 啟用 / 解鎖）判斷要不要提供入口，與 `isDisabled` 的用途不同：
 *
 * - `isDisabled` 回答「**顯示**上要不要當成停用」→ 未知值一律當停用（fail-closed）
 * - 本函式回答「**操作**上我有沒有把握」→ 未知值一律回 false，不給任何狀態按鈕
 *
 * 兩者缺一不可。少了本函式，未知狀態的列會落進 `isDisabled` 那一支而顯示「啟用」，
 * 而後端 `set_status` 不檢查舊狀態、照寫 `ACTIVE`——於是畫面標示 fail-closed、操作卻 fail-open：
 * 一個語意未知（可能是凍結 / 待調查）的帳號被一鍵解回正常，且「啟用」沒有二次確認（#603 裁示）。
 */
export function isRecognisedStatus(row: AccountStatusFields): boolean {
  return row.status === "ACTIVE" || row.status === "DISABLED"
}

/** 帳號是否鎖定中（ACTIVE 且 locked_until 尚未逾時；逾時者已自動解鎖）。 */
export function isLocked(row: AccountStatusFields): boolean {
  return row.status === "ACTIVE" && row.locked_until !== null && new Date(row.locked_until) > new Date()
}

/** 帳號目前是否可用（未停用且未鎖定中）——登不進系統者不應被指派權限。 */
export function isAccountUsable(row: AccountStatusFields): boolean {
  return !isDisabled(row) && !isLocked(row)
}
