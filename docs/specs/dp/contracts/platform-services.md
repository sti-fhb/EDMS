# 平台內部服務契約（DP 提供、ET / DM 呼叫）

**日期**: 2026-07-09 | **規格**: [../spec.md](../spec.md) | **資料模型**: [../data-model.md](../data-model.md)

> 三支服務皆為**同一 FastAPI 應用內之 Python service 呼叫**（模組邊界依 `sti-backend-boundaries`：ET / DM 僅得 import DP 之公開 service 介面，不得直接操作 DP 資料表）。介面以函式簽章 + 語意規則描述；實際型別以實作之 Pydantic schema 為準。

---

## SRVDP001 — 參數唯讀查詢服務

供各模組讀取 `DP_PARAM` 之參數值與清單定義（唯讀；維護僅經 DP 後台 US5）。

```python
def get_param_value(param_id: str, key: str = "VALUE") -> str | None
    """取單值參數；不存在或停用回 None。"""

def get_param_list(param_id: str, enabled_only: bool = True) -> list[ParamItem]
    """取清單定義（依 SORT_ORDER 排序）。ParamItem: key / value / is_enabled / sort_order。"""
```

規則：
- **不快取**（儲存即生效，見 research §7）；每次讀 DB
- 呼叫方 MUST 只讀自己前綴（`ET_` / `DM_`）與平台級（無前綴）之 PARAM_ID；服務不強制檢核呼叫來源（同進程信任），越域讀取屬實作違規、由 code review 把關
- 業務規則（分類碼嵌入 DOC_ID、`ALL` 展開、唯一手冊檢核）歸呼叫方；本服務僅回定義
- 錯誤語意：PARAM_ID 不存在 → 空結果（非例外），利呼叫方以預設值 fallback

---

## SRVDP002 — 發信服務（送信 + outbox）

各模組寄送 Email 之唯一入口；模組不自持範本、不自建佇列、不直連 SMTP。

```python
async def send_email(
    recipients: list[str],        # 收件人 Email（逐收件人一列 outbox）
    template_code: str,           # DP_NOTIFY_TEMPLATE.TEMPLATE_CODE
    module: str,                  # 範本歸屬 MODULE（DP / ET / DM）
    params: dict[str, str],       # 範本變數
    caller_module: str,           # 呼叫方模組（記入 CALLER_MODULE）
) -> SendResult                   # queued_count / skipped_reason
```

規則：
- **非同步**：渲染 + 寫入 `DP_EMAIL_LOG`（PENDING）即返回；實際寄送由常駐 worker 依平台級 `MAIL` 參數執行（見 research §8）
- 範本停用（IS_ENABLED=false）→ 回 `skipped_reason="TEMPLATE_DISABLED"`、不寄、不視為錯誤（呼叫方業務照常）
- 範本 `CHANNEL` 不含 Email（`MSG`，僅站內訊息）→ 回 `skipped_reason="CHANNEL_NOT_EMAIL"`、不寄、不視為錯誤（`EMAIL` / `BOTH` 才寄）
- `template_code` 不存在 → raise `AppError`（錯誤碼依 `sti-error-codes` 於實作定義）；變數缺漏 → 該收件人列標 FAILED、不中斷其他收件人
- 渲染內容以快照存 outbox；事後改範本不影響已排隊信件
- 呼叫方 MUST 於自身交易 commit 後呼叫（避免業務回滾但信已排隊）

---

## SRVDP003 — 稽核寫入服務

各模組資安稽核事件之統一寫入口（`DP_AUDIT_LOG`，append-only）。

```python
def log_action(
    module: str,                  # 事件歸屬 DP / ET / DM
    func_name: str,               # 功能 / 資源名稱（如 ET-COURSE、DP-USERS）
    action_type: str,             # LOGIN / LOGOUT / CREATE / UPDATE / DELETE
    result: str,                  # SUCCESS / FAIL
    operator_id: str,             # 操作者 USER_ID（系統作業用 SYSTEM）
    target_id: str | None = None,
    description: str | None = None,
    before_value: dict | None = None,   # 服務內序列化為 JSON 字串
    after_value: dict | None = None,
    source_ip: str | None = None,
) -> None
```

規則：
- 服務內計算 `ROW_HASH`（鏈式雜湊，research §6）；呼叫方不涉入
- **寫入範圍**：資安類事件（帳號 / 角色權限 / 系統操作 / 登入登出 / 參數範本異動）；**業務歷程**（DM_CHANGE_LOG、閱讀、學習紀錄）MUST NOT 寫入本表、留各模組
- 呼叫時機：於呼叫方 Service 層 CUD 完成時（同交易內），對齊 TBMS `AuditLogService` 慣例；`res_id` 隨標準欄位寫入
- 無查詢介面於本契約——查詢僅經 DP 後台 US10

---

## 版本

| 日期 | 異動 |
|------|------|
| 2026-07-09 | 首版（SRVDP001–003）|
