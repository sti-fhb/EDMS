# User Story 6 — 通知發送服務（UCDP009，發信引擎・無畫面）

> 返回總檔：[spec.md](spec.md) | 模組：平台（DP）| Priority：P1 | Wireframe：—（服務，無畫面）

## User Story

作為 ET / DM 模組（呼叫方），我要傳入收件人與 `template_code` 呼叫平台唯一發信服務，由平台渲染範本、經 outbox 非同步寄送並記錄結果，以便所有信件集中管理且業務交易不被寄信阻塞。

**Priority**: P1 — 密碼重設信（US3）、帳號變更驗證信（US8）與各模組業務通知皆依賴本服務。

**Independent Test**: 模組呼叫 `send_email` 後立即返回，信件進入 `DP_EMAIL_LOG`（PENDING）並由背景 worker 寄出（SENT）；SMTP 失敗時依重試上限重試、逾上限標記 FAILED 留錯誤訊息；停用範本之呼叫不寄信且不影響呼叫方流程。

### Acceptance Scenarios

1. **Given** 模組於業務事件呼叫 `send_email(recipients, template_code, params)`，**When** 對應範本存在且啟用，**Then** 以 params 代入變數渲染主旨 / 內文、逐收件人寫入 `DP_EMAIL_LOG`（狀態 PENDING、記 `CALLER_MODULE`）、**立即返回**（不同步寄送、不阻塞呼叫方交易）
2. **Given** outbox 存在 PENDING 信件，**When** 背景 worker 依速率 / 重試參數（平台級 `MAIL`）輪詢，**Then** 透過外部 SMTP 批次寄送並將狀態更新為 SENT（記寄出時間）
3. **Given** SMTP 寄送失敗，**When** 未達重試上限，**Then** 依參數延遲重試（累計重試次數）；**When** 逾重試上限，**Then** 標記 FAILED 並保留錯誤訊息（失敗率監控由 IT 監控機制負責，不做系統內通報）
4. **Given** 對應範本為停用狀態，**When** 模組呼叫，**Then** 不產生寄送（該類信件不寄），呼叫正常返回、觸發事件照常運作
5. **Given** 傳入之 `template_code` 不存在，**When** 呼叫，**Then** 服務回傳明確錯誤並記 log（由呼叫方決定後續處理）
6. **Given** 範本變數缺漏（params 未含範本所需變數），**When** 渲染，**Then** 記錄渲染錯誤、該筆標記 FAILED（不中斷其他收件人）
7. **Given** 大量收件人（如 DM 發布通知「全體」），**When** 呼叫，**Then** 全數進 outbox 由 worker 依速率分批寄送，呼叫方交易不受影響

## Functional Requirements

- **FR-DP-US6-01**: 平台 MUST 提供唯一發信服務 `send_email(recipients, template_code, params)`（簡寫；完整簽章含 `module` / `caller_module`，見 [contracts/platform-services.md](contracts/platform-services.md)）；各模組 MUST NOT 自持範本表、MUST NOT 自建 outbox、MUST NOT 直連 SMTP
- **FR-DP-US6-02**: 發信 MUST 非同步——服務僅渲染 + 寫入 outbox `DP_EMAIL_LOG`（PENDING）即返回；實際寄送由常駐背景 worker 執行（worker 不登錄於排程表）
- **FR-DP-US6-03**: 渲染 MUST 以 `MODULE` + `TEMPLATE_CODE` 取 `DP_NOTIFY_TEMPLATE` 啟用中範本，代入變數產生主旨 / 內文；範本停用時 MUST 不寄且不影響呼叫方
- **FR-DP-US6-04**: `DP_EMAIL_LOG` MUST 記錄收件人、狀態（PENDING / SENT / FAILED）、重試次數、錯誤訊息、`CALLER_MODULE`、時間（append-only）
- **FR-DP-US6-05**: worker MUST 依平台級參數（每分鐘速率、重試上限、重試間隔）寄送與重試；逾上限 MUST 標記 FAILED 並保留錯誤訊息；MUST NOT 內建告警通報（由 IT 監控負責）
- **FR-DP-US6-06**: 單筆收件人寄送失敗 MUST NOT 影響同批其他收件人

## 系統訊息

本 US 為背景服務、無使用者介面，不定義 UI 訊息；執行結果以 `DP_EMAIL_LOG` 狀態與應用層 log 表達，服務對呼叫方回傳明確錯誤碼（`template_code` 不存在、參數不合法等，詳見 contracts/）。

## 前置依賴

- `DP_NOTIFY_TEMPLATE` 範本存在且啟用（US9 維護；`MODULE=DP` 系統信不可停用）
- 發信調校參數（速率 / 重試 / 間隔）為平台級參數（US5）
- 外部 eMail Server（SMTP）可用；不可用時信件停留 outbox 依重試機制處理（跨模組介接）

## 相關文件

- 需求章節：[RQDP.md](../../requirements/RQDP.md) §通知範本與發信引擎
- 使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP009
- 服務契約：[contracts/platform-services.md](contracts/platform-services.md)（SRVDP002）、[contracts/ext-dp-email-server.md](contracts/ext-dp-email-server.md)
- 共用規則：[spec.md](spec.md) §通知範本與發信引擎
