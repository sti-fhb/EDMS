---
description: 後端應用層 log 規範，寫 backend Python 時載入
paths:
  - "backend/app/**/*.py"
  - "backend/tests/**/*.py"
---

# 後端應用層 Log 規範

## 用法

```python
import logging
logger = logging.getLogger(__name__)

logger.warning("停用帳號嘗試登入 user=%s", user_id)
```

- 用 `%s` 參數化，禁 f-string / 字串拼接
- `except` 區塊用 `logger.exception()` 帶 stack trace

### ⚠️ `logger.exception()` 的 traceback 有兜底，訊息本體沒有

`app/core/log_redaction.install_exception_redaction`（`main.py` import 時安裝）以
`setLogRecordFactory` 把每筆紀錄的 **`exc_text` 預先填成去識別化的版本**。所以
`logger.exception()` 帶出的 traceback——含 SQLAlchemy 的 `[SQL: …] [parameters: …]`
與 asyncpg 的 `DETAIL:` 行——**會被遮罩**，不需要呼叫端自己處理。

🔴 **但訊息本體（`msg % args`）完全不經遮罩。** 兜底只管 `exc_info`：

```python
# ✅ traceback 走兜底
logger.exception("寄信失敗 user=%s", user_id)

# ⛔ 例外或個資當成參數傳進訊息本體 —— 沒有任何東西會遮它
logger.exception("寄信失敗 %s", exc)
logger.error("查無此人 email=%s", email)          # 要記就用 mask_email(email)
```

**判準**：值要出現在**訊息裡**時，呼叫端自己負責（`mask_email`、只記 `user_id`）；
值只出現在**例外的 traceback 裡**時，交給兜底，不要為此改寫 `except` 的寫法。

⛔ 兜底涵蓋不到的情況，見 `app/core/log_redaction.py` 檔頭的「未涵蓋的既有暴露面」
（訊息本體、`sqlalchemy.engine` 的 echo、非 DB 例外訊息裡的值等）。**不要假設「反正有遮罩」。**

把例外訊息**寫進 DB 或印到 CLI**（不經 log）時，用 `redact_exception_message(exc)`，不要用
`redact_sensitive(str(exc))`——後者只看文字，分不出例外鏈上有沒有 DB 錯誤，DB 主訊息裡的值會漏掉。

### 控制字元由全域轉義，換行也是

`app/core/log_sanitize.install_control_char_escape`（#913）在紀錄產生時把訊息、參數與 traceback
中的控制字元轉成字面（`ESC` → `\x1b`、換行 → `\n`），防止偽造 log 行與操控終端機。這只管
**完整性**，不管機密性——個資照樣要自己遮罩。

⚠️ 因此**訊息本體不能刻意多行**：`logger.error("失敗\n%s", 多行文字)` 會被壓成一行。要附堆疊就用
`exc_info=exc`，traceback 保留換行（續行自動縮排）。

## 禁用

- `print()` / `sys.stdout.write()` / `sys.stderr.write()`
- 自訂 Exception class（錯誤用 `AppError`，詳見 `sti-backend-modules.md`）

## 禁寫入 log 的敏感資料

- 密碼明文
- JWT / API Key 原始值（可記 KEY_PREFIX 或前 8 碼）
- `DP_PARAM_D.PARAM_VALUE`（可能含通關密碼雜湊）
- 個資完整值（必要時遮罩如 `A1****567`）
