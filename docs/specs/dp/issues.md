# 開發 Issues 清單：平台模組（Platform）

**模組代碼**: DP | **日期**: 2026-07-09
**來源**: [plan.md](plan.md) §功能分群與開發順序 | [tasks.md](tasks.md) | [spec.md](spec.md)

> 每張 Issue 為一個**功能之垂直切割**（DB + API + UI + 驗收條件），可獨立開發、測試與交付。Issue #0 為基礎建設，其餘依 plan.md 之 P1 / P2 階段排序。
>
> **增量模式（2026-07-09）**：採「產一張 → 實作 → 驗證 OK → 再補下一張」流程；目前僅 Issue #0 完整撰寫，#1 起之完整 body 待 #0 實作驗證後逐張補入（總覽表先列全貌）。
>
> **Issue 開立規則（2026-07-09）**：
> 1. 標題格式：`[{階段}] {模組代碼} — {功能名稱}`（如 `[Foundation] DP — 專案建置與平台基礎建設`、`[P1-核心] DP — 通知發送服務`）
> 2. Labels：`{階段標籤}`（Foundation 用 `priority:P0`；其餘 `P1-核心` / `P2-延伸` / `收尾`）+ `DP-平台` + `{US 標籤}`（如 `US6`；無對應 US 者免）
> 3. **依序開立**，於 body「依賴」段標註相依之 **GitHub Issue 編號**（模組內序號 #0–#12 僅為規劃用，實際編號以 GitHub 為準、回填總覽表）

---

## Issue 總覽

| # | 標題 | 對應 | 階段 | 涵蓋 Tasks | 主要前置 | GitHub # | 狀態 |
|---|------|------|------|-----------|---------|----------|------|
| 0 | 專案建置與平台基礎建設 | — | Setup + Foundational | T001 ~ T017（17 任務）| 無 | [#16](https://github.com/sti-fhb/EDMS/issues/16) | ✅ 已開立 |
| 1 | 通知發送服務（發信引擎 + outbox）| US6 / UCDP009 | P1-核心 | T018 ~ T020（3 任務）| #0 | — | 待補 |
| 2 | 登入 / 登出與模組入口頁 | US1 / UCDP001 | P1-核心 | T021 ~ T025（5 任務）| #0 | — | 待補 |
| 3 | 使用者自助註冊 | US2 / UCDP002 | P1-核心 | T026 ~ T027（2 任務）| #2 | — | 待補 |
| 4 | 忘記密碼 | US3 / UCDP003 | P1-核心 | T028 ~ T029（2 任務）| #1, #2 | — | 待補 |
| 5 | 使用者管理（dp-users）| US4 / UCDP005 | P1-核心 | T030 ~ T032（3 任務）| #2, #3 | — | 待補 |
| 6 | 系統參數與清單維護（dp-params）| US5 / UCDP006 | P1-核心 | T033 ~ T034（2 任務）| #2 | — | 待補 |
| 7 | 權限管理（dp-roles）| US7 / UCDP010 | P1-核心 | T035 ~ T036（2 任務）| #2（模組 service 以 stub）| — | 待補 |
| 8 | 個人資料維護 + 強制變更密碼（dp-profile）| US8 / UCDP004 | P2-延伸 | T037 ~ T039（3 任務）| #1, #2 | — | 待補 |
| 9 | 通知範本維護（dp-templates）| US9 / UCDP011 | P2-延伸 | T040 ~ T041（2 任務）| #1, #2 | — | 待補 |
| 10 | 操作記錄查詢（dp-audit）| US10 / UCDP007 | P2-延伸 | T042 ~ T043（2 任務）| #2 | — | 待補 |
| 11 | 排程引擎與總覽 + SCHDP001（dp-schedule）| US11 / UCDP008 | P2-延伸 | T044 ~ T046（3 任務）| #0, #1 | — | 待補 |
| 12 | 整合測試 + 安全 + 收尾 | — | 收尾 | T047 ~ T054（8 任務）| 全部 | — | 待補 |
| F1 | 開發流程 CI 基礎建設（local-ci / ci.yml 預備 / PR 模板 / error-codes 骨架）| — | Foundation-infra | —（不對應 tasks.md 業務 task）| 無 | [#18](https://github.com/sti-fhb/EDMS/issues/18) | 🔨 開發中 |

> **F 系列＝Foundation-infra**（開發流程 / CI/CD，非業務 task）。F1 只做 repo 側、不依賴 runner；runner 註冊 + CD + branch protection 於未來 GCP 環境就緒後處理（EDMS 自有 ci/cd，不共用 TBMS）。

---

## Issue #0：[Foundation] DP — 專案建置與平台基礎建設（GitHub [#16](https://github.com/sti-fhb/EDMS/issues/16)）

**對應規格**：[plan.md](plan.md) §技術背景、§第零階段；[data-model.md](data-model.md)；[research.md](research.md) §1–§11；[contracts/platform-services.md](contracts/platform-services.md)
**階段**：Setup + Foundational（為所有 Issue 之前置；亦為 ET / DM 兩模組開發之前置）
**前置條件**：
- PostgreSQL 17 已建置；TBMS 原始碼（`../TBMS`）可供遷移參照
- `backend/.env`、`frontend/.env` 依 `.env.example` 建立

### 任務說明

建立 EDMS 後端 / 前端骨架（自 TBMS 遷移起手包，依 [EDMS-MIGRATION.md](../../../EDMS-MIGRATION.md) §3 / §4），完成 DP 10 張平台表 migration 與種子資料，並實作平台共用元件：稽核服務（SRVDP003）、參數唯讀服務（SRVDP001）、JWT 基礎（短 TTL + 活動換發）、認證 middleware、速率限制、密碼策略工具、模組管理者判定閘。本 Issue 完成後，SRVDP001–003 即可供 ET / DM 模組開發引用。

> ⚠️ **遷移裁剪（research §1，最容易踩雷處）**：起手包複製後 MUST 裁剪——不建 `DP_SESSION`（無 Refresh Token，改 `auth_time` 換發）、不帶 `app/dp/roles` / `menus`（無全域 RBAC）、無 `ACCOUNT_CONFIRM` 開通信、`EMAIL` 不加密、刪 MFA。勿照 EDMS-MIGRATION 舊清單全帶。

### 範圍

**後端**：
- T001 調整既有骨架（`fa9b398` 已建最小骨架，改為補缺口）：**首步修 `core/base_model.py` 移除 `CREATED_SITE` / `UPDATED_SITE`（四基底類別，TBMS 殘留）**、pyproject 補 PyJWT / passlib[bcrypt] / fastapi-mail / APScheduler、config 與 `.env.example` 補 JWT / SMTP 設定；db / pagination / exceptions / conftest 沿用
- T002~T008 Migration：`DP_USER`（無 DP_SESSION）、`DP_PWD_RESET` + `DP_PWD_HIST`、`DP_AUDIT_LOG`（TEXT 存 JSON + ROW_HASH + DB 帳號僅 INSERT/SELECT）、`DP_PARAM_M/D`、`DP_NOTIFY_TEMPLATE`、`DP_EMAIL_LOG`、`DP_SCHEDULE` + `DP_SCHEDULE_LOG`
- T009 種子：平台級參數（`JWT` / `PWD_POLICY` / `LOGIN` / `MAIL` / `ACTION_TYPE` 全預設值，見 data-model §種子）、DP 系統信 3 支（`PWD_RESET` / `EMAIL_CHANGE_VERIFY` / `PWD_EXPIRY_REMIND`，IS_SYSTEM=true）、排程 job 4 筆
- T011 SRVDP003 稽核服務（鏈式 ROW_HASH）
- T012 SRVDP001 參數唯讀服務（不快取）
- T013 JWT 基礎（`auth_time` claim、15 分 TTL、換發驗證 8 小時上限）
- T014 認證 middleware（每請求查 `DP_USER` 狀態）+ request_context / operator
- T015 速率限制 middleware（IP + 帳號滑動視窗）
- T016 密碼策略工具（複雜度 / 重複性 / bcrypt / 歷程追加）
- T017 模組管理者判定閘（`is_module_admin` 聚合，**stub 可注入**）

**前端**：
- T010 骨架：Vite + React 19 + MUI 7 + React Router v7 + TanStack Query v5（一律 TypeScript）、DP 後台 layout（sidebar 對齊 [wireframe](../../wireframes/dp/index.html)）、登入 overlay 骨架

**測試**：
- 測試 DB 骨架（`test_edms`、xdist）；各共用元件單元測試；migration 可升可測

### 驗收條件

- [ ] `uv run alembic upgrade head` 成功建立 10 張 DP 表；標準欄位齊備（CREATED/UPDATED_USER/DATE、RES_ID、DELETED，**無 SITE 欄位**）；**不存在** `DP_SESSION` / `DP_ROLE` / `DP_MENU` 表
- [ ] 種子載入成功：平台級參數（含 `ACCESS_TTL_MIN`=15、`RENEW_MAX_HOURS`=8、`FAIL_LOCK_COUNT`=5、`LOCK_MINUTES`=30、`MIN_LEN`=8 / `ADMIN_MIN_LEN`=12、`HISTORY_COUNT`=3、`EXPIRY_DAYS`=90、`RETRY_MAX`=5 / `RATE_PER_MIN`=60 / `RETRY_INTERVAL_MIN`=2）、DP 系統信 3 支（IS_SYSTEM=true）、排程 job 4 筆（SCHDP001 / SCHET001 / SCHET002 / SCHDM001）
- [ ] SRVDP003 `log_action` 寫入 `DP_AUDIT_LOG` 含鏈式 ROW_HASH（驗證工具可證前列被改即斷鏈）；應用 DB 帳號對本表僅可 INSERT / SELECT
- [ ] SRVDP001 `get_param_value` / `get_param_list` 讀取種子正確；停用清單項於 enabled_only 過濾；PARAM_ID 不存在回空非例外
- [ ] JWT 簽發含 `auth_time`；換發於「token 有效 + 未逾 8 小時」通過、逾 15 分未換發自然失效、逾 8 小時上限拒絕（單元測試覆蓋）
- [ ] 認證 middleware：未帶 token 401；停用 / 鎖定帳號之有效 token 下次請求被拒（每請求查 DP_USER）
- [ ] 速率限制以「IP + 帳號」維度超限回 429
- [ ] 密碼策略：8 / 12 字元與 3 種字元組合檢核、與最近 3 次重複拒絕（查 `DP_PWD_HIST`）、bcrypt 雜湊（單元測試覆蓋）
- [ ] `is_module_admin` 判定閘可以 stub 注入替換（依 [contracts/module-callbacks.md](contracts/module-callbacks.md) 簽章）
- [ ] 前端骨架可啟動；DP 後台 layout sidebar 六畫面連結對齊 wireframe；無任何 `.js` / `.jsx` 檔
- [ ] `uv run pytest -q` 全綠；ruff / ESLint 通過（CI 合規門檻）

### 依賴

無，可獨立開發（本 Issue 為全部 Issue 與 ET / DM 模組開發之前置）。

### 注意事項

- **遷移裁剪清單**（research §1）為本 Issue 最高風險點——照舊清單誤帶 `DP_SESSION` / RBAC / MFA / 開通信會與 spec 直接矛盾
- **既有骨架的 `base_model.py` 含 SITE 欄位**（TBMS 原封帶殘留，`CREATED_SITE` 還是必填）——T001 首步移除，否則 10 張 DP 表全會多兩個無資料來源的欄位（2026-07-09 現況盤點）
- 稽核前後值以 **TEXT 存 JSON**（型別規範不用 JSONB，research §6）
- 表 / 欄位命名 UPPER_SNAKE_CASE、型別限用集合，依 `sti-naming-conventions` 與 data-model DD
- Alembic 依 `sti-alembic-rules`；後端分層依 `sti-backend-modules` / `sti-backend-boundaries`（ET / DM 僅可經 SRVDP 介面使用平台能力）
- 啟動方式一律照 `README.md`「啟動開發環境」章節

### 相關文件

- [spec.md](spec.md)（模組總覽）、[plan.md](plan.md)、[research.md](research.md)、[data-model.md](data-model.md)、[tasks.md](tasks.md) Phase 1–2
- [contracts/platform-services.md](contracts/platform-services.md)、[contracts/module-callbacks.md](contracts/module-callbacks.md)
- [EDMS-MIGRATION.md](../../../EDMS-MIGRATION.md) §3 / §4（遷移來源）

**Labels**：`priority:P0`, `DP-平台`（Foundation 無對應 US，免 US 標籤）

---

## Issue #1 ~ #12：待補（增量模式）

依總覽表順序，於前一張 Issue 實作驗證 OK 後逐張補入完整 body（格式同 Issue #0，對齊 `sti-issue-create` canonical 模板）。

---

## 異動紀錄

| 日期 | 異動 |
|------|------|
| 2026-07-09 | 首版：總覽表（#0–#12）+ Issue #0（Foundation）完整撰寫；採增量模式，#1 起待 #0 驗證後補入 |
| 2026-07-09 | 補 Issue 開立規則（標題 `[{階段}] {模組代碼} — {功能名稱}`、Labels 階段+`DP-平台`+US、依序開立標依賴編號）；總覽表加 GitHub # 欄；Issue #0 已開立為 GitHub #16 並依規則更名、換 labels（`priority:P0` + `DP-平台`）|
