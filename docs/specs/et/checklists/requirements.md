# Specification Quality Checklist: 教育訓練文件管理模組（Education & Training）

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-07-03
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)（僅用業務代碼名稱如 ET_COURSE / ET-MSG，per sti-spec-style §4；無框架 / 語言細節）
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed（模組定位 / 主要角色 / User Stories 索引 / Requirements / Key Entities / Success Criteria / Assumptions / 跨模組介接 / 排程作業總覽 / RQ 追蹤矩陣）

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain（2026-07-03 grep 確認無 TBD / 待補 / 待確認 / ???）
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable（SC-001 ~ SC-012 皆量化）
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined（spec_us1 ~ 15.md 各含 Acceptance Scenarios）
- [x] Edge cases are identified（可逆狀態機、影片累計覆蓋率邊界、Attempt Snapshot 並發、軟刪除分流、標籤對應變更影響、Email 變更逾時、問卷凍結、0 管理者情境、DM 文件廢止等）
- [x] Scope is clearly bounded（Assumptions + Out of Scope + 跨模組介接總覽；ET/DM 獨立部署、不依賴主系統業務模組）
- [x] Dependencies and assumptions identified（Assumptions + 跨模組介接總覽 + 各 spec_us 前置依賴）

## Feature Readiness

- [ ] All functional requirements have clear acceptance criteria — ⚠ **部分**：各 spec_us{N}.md 具 Acceptance Scenarios 與系統訊息表（ET-MSG-…，2026-07-03 補齊 15 US），行為可驗證；但**尚未建立 `FR-ET-XXX` 功能需求編號**（sti-spec-structure 要求），RQ→FR→AC 追溯鏈以 RQ→US→AC 替代。**待補**（SA precheck S1）。
- [x] User scenarios cover primary flows（15 US 涵蓋 UCET001 ~ UCET015）
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- spec.md（索引）已完成：模組定位、主要角色（管理者 / 教師 / 學員 / 系統自動）、User Stories 索引（15 US / P1~P3）、優先級總覽、Key Entities、全模組業務規則（受訓單位標籤 / 起訖時間與可逆狀態機 / 強制完成解鎖 80% 累計覆蓋率 / 課後回饋問卷 / 排程統計與提醒 / 通知信統一範本 / 多選題部分計分 / 洗牌與 Attempt Snapshot / 閱卷明細 / 軟刪除分流 / 並發處理 / 樂觀鎖 / 管理者保護 / DM 文件廢止 / 邀請與加入 / 完課率 / 章節異動 / 系統初始化 / Email 變更）、Success Criteria、Assumptions、跨模組介接、排程作業總覽、RQ 追蹤矩陣。
- **已完成**：spec_us1 ~ 15.md 全數產出（各含 User Story 描述、Acceptance Scenarios、系統訊息表 ET-MSG-…、前置依賴）；data-model.md（27 表 + Lookup + ERD）、plan.md、research.md、tasks.md、issues.md、contracts/（SRVDM001 / SRVDM002 / EXT-ET-EMAIL）、wireframes/et/index.html。
- **2026-07-02 客戶 6 項需求變更**已傳播至 spec / data-model / plan / tasks / wireframe / research（受訓單位標籤取代業務模組、發布標籤自動邀請＋寄信、起訖時間與可逆關閉、課後問卷、排程統計與提醒、每次作答明細、通知範本、影片倍速）。
- **2026-07-03 交付前自檢後續**：（1）通知 Email 契約 `ext-et-email-server.md` 已整份改寫對齊 2026-07-02（統一範本 / ET_NOTIFY_TEMPLATE / 排程信 / IS_ACTIVE）；（2）US13 課後問卷填寫頁已補入 wireframe（`et-survey` / ET05-Q）；（3）本檢核清單補建。
- **待補（不擋 SD 開發、建議補強）**：
  - **S1**：各 spec_us 之 `FR-ET-XXX` 功能需求編號（目前以 Acceptance Scenarios + 系統訊息表承載行為）。
  - **S4**：data-model `ET_MATERIAL` 之多支影片 / 多份 DM 文件 1:N 拆表於 plan / data-model phase 2 定案（目前以暫時欄位呈現概念）。
- 來源可追溯：spec 內容對應 requirements/RQET.md、use-cases/et/usecases.md、_refs/10-教育訓練文件管理模組.md（source of truth），無新增未授權範圍。
