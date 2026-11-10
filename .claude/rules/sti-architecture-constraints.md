---
description: 系統架構硬性約束，開發後端時載入
paths:
  - "backend/**/*.py"
---

# 系統架構硬性約束

## 部署設定與可維護設定之界線

### 定義
- 部署設定：`app/core/config.py` `Settings` 欄位，值來自 `.env`
- 可維護設定：`DP_PARAM_M`／`DP_PARAM_D`、`DP_NOTIFY_TEMPLATE`，及其他經畫面或 API 維護、程式讀回作為設定使用之表

### 一律放部署設定，禁止放可維護設定
- 後端開檔、寫檔、掃目錄所依據之根目錄
- 後端主動連線之目標：主機、連接埠、URL（SMTP、DB、外部服務）
- 本系統對外網址（組信件連結、下載連結用）
- 後端對外連線所用之機密：密碼、金鑰、token

### 可放可維護設定
- 業務數值與規則（效期、上限、允許副檔名、開關、文字模板、通知收件人）
- 相對於部署設定根目錄之單層子目錄名：讀取時以 `\A[A-Za-z0-9_-]+\Z` 驗證
- 外部系統呼叫本系統之憑證：只存雜湊

### 實作
- spec 要求以可維護設定承載「一律放部署設定」之值時，不得照做；列為 SA 問題
- 可維護設定或 DB 欄位之值用於組路徑時，須經根目錄圍籬：DM 用 `app/dm/document/file_paths.py` `resolve_within_root`、ET 用 `app/et/material/storage.py` `resolve_within_root`；新增根目錄時比照（`realpath` 後 `commonpath` 須等於 root），不通過即 `AppError`
- DB 存檔案位置只存相對於部署設定根目錄之相對路徑
- API 回應、錯誤訊息、可下載內容不得含部署設定之絕對路徑與主機位址
- 新增可維護設定 seed 時，值不得為絕對路徑、URL、`host:port`、明文機密
- 不得新增經畫面維護之外部連線設定（主機、帳密）；業務上需要時列為 SA 問題
