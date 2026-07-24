/**
 * 平台級參數的使用者可讀中文標籤（對齊 wireframe dp-params）。
 *
 * key 為 `${PARAM_ID}.${PARAM_KEY}`；VALUE 參數以此顯示中文名稱，代碼另以小字備查。
 * 未列於此表者（模組級 ET_/DM_ 或未來新增）回退顯示原始代碼。
 */
const PARAM_LABELS: Record<string, string> = {
  "JWT.ACCESS_TTL_MIN": "閒置自動登出（分鐘）",
  "JWT.RENEW_MAX_HOURS": "單次登入時效上限（小時）",
  "PWD_POLICY.MIN_LEN": "密碼最小長度（一般使用者）",
  "PWD_POLICY.ADMIN_MIN_LEN": "密碼最小長度（特權帳號）",
  "PWD_POLICY.CHAR_TYPES": "字元組合要求（種類數）",
  "PWD_POLICY.HISTORY_COUNT": "密碼歷史記憶次數",
  "PWD_POLICY.EXPIRY_DAYS": "密碼最長效期（天）",
  "PWD_POLICY.EXPIRY_REMIND_DAYS": "密碼到期提醒天數（天）",
  "LOGIN.FAIL_LOCK_COUNT": "登入失敗鎖定次數",
  "LOGIN.LOCK_MINUTES": "帳號鎖定時間（分鐘）",
  "LOGIN.RESET_TOKEN_TTL_MIN": "密碼重設連結有效時間（分鐘）",
  "LOGIN.EMAIL_CHANGE_TTL_MIN": "Email 變更驗證連結有效時間（分鐘）",
  "LOGIN.IDLE_DISABLE_DAYS": "閒置停用天數（天）",
  "MAIL.RATE_PER_MIN": "每分鐘寄信上限（封）",
  "MAIL.RETRY_MAX": "寄信重試上限次數",
  "MAIL.RETRY_INTERVAL_MIN": "寄信重試間隔（分鐘）",
}

/** 取參數的中文標籤；未定義者回退原始代碼。 */
export function paramLabel(paramId: string, paramKey: string): string {
  return PARAM_LABELS[`${paramId}.${paramKey}`] ?? paramKey
}