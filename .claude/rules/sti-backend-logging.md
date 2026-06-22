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

## 禁用

- `print()` / `sys.stdout.write()` / `sys.stderr.write()`
- 自訂 Exception class（錯誤用 `AppError`，詳見 `sti-backend-modules.md`）

## 禁寫入 log 的敏感資料

- 密碼明文
- JWT / API Key 原始值（可記 KEY_PREFIX 或前 8 碼）
- `DP_PARAM_D.PARAM_VALUE`（可能含通關密碼雜湊）
- 個資完整值（必要時遮罩如 `A1****567`）
