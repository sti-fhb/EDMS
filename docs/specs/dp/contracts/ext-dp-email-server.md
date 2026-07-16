# 外部介接：eMail Server（SMTP）

**日期**: 2026-07-09 | **規格**: [../spec.md](../spec.md)

> 平台發信引擎（US6 worker）對外部郵件系統之介接。2026-07-08 發信集中化後，**全 EDMS 僅此一處連 SMTP**（原 ET 契約 `ext-et-email-server.md` 之寄送責任移轉至此；ET / DM 一律經 SRVDP002）。

## 介接方式

| 項目 | 內容 |
|------|------|
| 協定 | SMTP（TLS；主機 / 埠 / 帳密 / 寄件者於 `backend/.env` 設定：`MAIL_SERVER` / `MAIL_PORT` / `MAIL_USERNAME` / `MAIL_PASSWORD` / `MAIL_FROM`；對齊 fastapi-mail 慣例）|
| 方向 | DP worker → eMail Server（單向送信；不收信、無退信解析）|
| 內容 | `DP_EMAIL_LOG` 之渲染快照（SUBJECT / BODY，HTML）；收件人一列一信 |
| 速率 / 重試 | 依平台級 `MAIL` 參數（`RATE_PER_MIN` / `RETRY_MAX` / `RETRY_INTERVAL_MIN`）|
| 失敗處理 | SMTP 例外→ 該列重試；逾上限標 FAILED 留 `ERROR_MSG`；SMTP 長時間不可用時信件停留 outbox，恢復後續寄（不遺失）|
| 監控 | FAILED 率 / outbox 積壓由 IT 以 log / 監控工具追蹤（系統不內建告警通報，spec 釐清第 2 輪）|

## 寄送信件類別總覽

| 來源 | 信件 |
|------|------|
| DP（系統信）| 密碼重設、帳號變更驗證、密碼到期提醒 |
| ET | 課程邀請 / 提醒 / 週報等（`MODULE=ET` 範本，事件見 ET 規格）|
| DM | 送審 / 退回 / 廢止通知、文件發布通知、KPI 週報、未讀提醒（`MODULE=DM` 範本，事件見 DM 規格）|
