# SA 工作規則

## 文件編碼規則

編碼格式統一為：`前綴` + `模組代碼` + `三位流水號`（如 RQET001、UCET001）。編號中間不加 `-`。

### 前綴定義

#### 文件編碼
- **RQ** = 需求（Requirement）：存放於 `docs/requirements/` 目錄
- **UC** = 使用案例（Use Case）：依據各模組正式需求文件（`RQ{模組代碼}.md`）整理，存放於 `docs/use-cases/` 目錄

#### 系統編碼
- **SRV** = 內部服務（Service）：模組間溝通的服務，格式 `SRV` + `模組代碼` + `三位流水號`（如 SRVDM001、SRVDM002 — ET 介接 DM 取得教材文件）
- **API** = 外部介接（API）：與外部系統介接的 API，格式 `API` + `模組代碼` + `三位流水號`（如 APIET001）
- **SCH** = 排程作業（Schedule）：定時或事件觸發的批次作業，格式 SCH + 模組代碼 + `三位流水號`（如 SCHET001）

#### 功能作業編碼
- 格式：`模組代碼` + `兩位流水號`（如 ET01、DM02）
- 用於標識各模組的功能作業項目

### 需求代碼
- **ET** = 教育訓練（Education & Training）— 本 repo 主模組
- **DM** = 文件管理（Document Management）— 介接模組，需求文件位於 TSBMS_SA repo，ET 透過 SRVDM001 / SRVDM002 取得教材文件

### 檔案讀取規則
- Claude 只需讀取 `docs/_refs/` 下的 `.md` 檔案，PDF 檔案僅供人工參考，不需讀取。

### 目錄結構
- `docs/_refs/` — 系統初步分析資料與需求說明書（source of truth）
- `docs/requirements/RQ{模組代碼}.md` — 各模組正式需求文件（整合分析資料與 RQ）
  - `docs/requirements/RQET.md` — 教育訓練（本 repo）
  - （DM 文件管理的 `RQDM.md` 位於 TSBMS_SA repo，本 repo 僅透過契約介接）
- `docs/use-cases/{模組代碼}/usecases.md` — 各模組使用案例
  - `docs/use-cases/et/usecases.md`
- `docs/specs/{模組代碼}/` — 各模組 Speckit 設計文件（功能規格、資料模型、實作計畫等）
  - `docs/specs/{模組代碼}/contracts/` — API 契約（含內部服務 SRV 與外部 API，如 ET↔DM 介接）
  - `docs/specs/et/`

## 需求整理流程

1. 從需求說明書逐條整理初始需求至 `docs/requirements/RQ0.md`，編碼以 **RQ** 開頭（如 RQET001）
2. 讀取 `docs/_refs/` 下各模組分析資料，以分析資料為主體，對應回 RQ 編號，補齊缺漏，產出 `docs/requirements/RQ{模組代碼}.md`
3. 依各模組正式需求文件，整理使用案例至 `docs/use-cases/{模組代碼}/usecases.md`，編碼以 **UC** 開頭（如 UCET001）

## 需求變更流程

`docs/_refs/` 為需求變更的唯一來源（source of truth），`RQ0.md` 保留不動作為原始對照。
1. 使用者先修改 `docs/_refs/` 下對應的分析資料
2. 告知 Claude 哪個模組有異動
3. Claude 依據更新後的 `docs/_refs/` 重新產出對應的 `docs/requirements/RQ{模組代碼}.md`

## RQ{模組代碼}.md 產出規則

以 `RQET.md` 為例，其他模組比照辦理：

1. **主體來源**：以 `docs/_refs/` 下對應的分析資料（如 `10-教育訓練文件管理模組.md`）為主體結構
2. **章節分組**：依分析資料的功能章節分組
3. **對應 RQ**：將 `RQ0.md` 中已有的 RQ 編號對應至相符的章節
4. **無對應 RQ 的項目**：分析資料中有、但 `RQ0.md` 無對應的項目，不發 RQ 編號，僅列出需求說明並在來源欄標註 `分析資料`
5. **來源標註**：每條需求標註來源欄位（`需求說明書` 或 `分析資料`）
6. **表格格式**：

| 編號 | 需求說明 | 操作角色 | 來源 |
|------|----------|----------|------|
| RQET001 | ... | 學員 | 需求說明書 |
| — | ... | 系統自動 | 分析資料 |

7. **編號不重整**：已發出的 RQ 編號不可變更或重新排序，只能新增
8. **模組概述**：含角色表、作業流程、跨模組介接、可配置參數
9. **涵蓋比對摘要**：末段附三張表（RQ → 分析資料、分析資料 → RQ、RQ 有但分析資料未涵蓋）

## 需求追蹤

- 每條 UC 必須標註其對應的 RQ 編號，建立 RQ → UC 的追蹤關係
- UC 表格需包含「關聯需求」欄位：

| 編號 | 使用案例名稱 | 關聯需求 | 說明 |
|------|-------------|---------|------|
| UCET001 | 建立教育訓練課程 | RQET001 | ... |
| UCET002 | 學員報名課程 | RQET003, RQET004 | ... |

- 一條 UC 可對應多條 RQ，一條 RQ 也可被多條 UC 引用
- 末段附 **RQ 追蹤矩陣**：列出每條 RQ 編號對應的 UC 編號

## Speckit 作業流程

### 產出目錄

每個模組的設計文件存放於 `docs/specs/{模組代碼}/`：

```
docs/specs/{模組代碼}/
├── spec.md              # 功能規格
├── plan.md              # 實作計畫
├── research.md          # 研究決策紀錄
├── data-model.md        # 資料模型（ERD + DD）
├── contracts/           # 介面契約（API 等）
├── checklists/
│   └── requirements.md  # 規格品質檢核
└── tasks.md             # 開發任務清單
```

### 標準作業順序

1. `/speckit.specify` — 依據 RQ + UC 產出功能規格（spec.md）
2. `/speckit.clarify` — 釐清規格中的待確認項目
3. `/speckit.plan` — 產出實作計畫（plan.md + research.md + data-model.md + contracts/）
4. `/speckit.tasks` — 產出開發任務清單（tasks.md）
5. `/speckit.analyze` — 跨文件一致性檢查（可在任意階段執行）

### 產出規範

- 所有產出一律使用**繁體中文**
- **資料來源**：以 `docs/_refs/` 為 source of truth，所有內容須可追溯至來源文件
- **模組代碼**：使用本文件定義的需求代碼（ET, DM）

### 資料庫命名規範

本專案資料庫使用 **PostgreSQL**，以下為 SA 設計文件（data-model.md 等）的命名規則：

#### Table 命名
- 格式：`{模組代碼}_{英文名}`，全部 **UPPER_SNAKE_CASE**
- 後綴規則：僅在主表+明細成對時才加 `_M`（主表）/ `_D`（明細）；歷史表加 `_H`。單獨的 Table 不加後綴
- 對應檔（junction table）視為明細，加 `_D`
- 範例：`ET_COURSE`（單獨主表）、`ET_QUIZ_M` + `ET_QUIZ_D`（主+明細成對）、`ET_ENROLL_H`（歷史）

#### 欄位命名
- 全部 **UPPER_SNAKE_CASE**
- 主鍵格式：`{縮寫}_ID`（如 `SHELF_ID`、`INV_ID`）

#### 資料型別
- 限用：VARCHAR(n), TEXT, INT, BIGINT, DECIMAL(p,s), DATE, TIMESTAMP, BOOLEAN
- 不使用 CHAR、FLOAT、DOUBLE 等非標準型別

#### Table 標準欄位

每張 Table 必須包含以下標準欄位（放在業務欄位之後）：

| 欄位代碼 | 欄位名稱 | 資料型別 | 必填 | 說明 |
|----------|----------|----------|------|------|
| CREATED_USER | 建立者 | VARCHAR(20) | Y | 建立資料的使用者 |
| CREATED_DATE | 建立時間 | TIMESTAMP | Y | 資料建立時間 |
| CREATED_SITE | 建立站點 | VARCHAR(10) | Y | 建立資料的站點代碼 |
| UPDATED_USER | 異動者 | VARCHAR(20) | N | 最後異動的使用者 |
| UPDATED_DATE | 異動時間 | TIMESTAMP | N | 最後異動時間 |
| UPDATED_SITE | 異動站點 | VARCHAR(10) | N | 最後異動的站點代碼 |
| RES_ID | 來源功能 ID | VARCHAR(30) | N | 資料來源的作業功能 ID |
| DELETED | 刪除標記 | INT | N | 軟刪除（0=正常, 1=已刪除） |

- 統一使用上述標準欄位命名，不可自行變體（如不可用 CREATE_DATE、UPDATE_USER 等）
- ER 圖（Mermaid）中可省略標準欄位，僅列業務欄位，避免圖表過長

### 開發交付文件

進入開發階段時，需提供以下 speckit 產出文件：

| 文件 | 路徑 | 用途 |
|------|------|------|
| 功能規格 | `docs/specs/{模組代碼}/spec.md` | User Story、FR、驗收標準 |
| 資料模型 | `docs/specs/{模組代碼}/data-model.md` | ERD、DD、代碼表 |
| API 契約 | `docs/specs/{模組代碼}/contracts/` | 外部介面規格 |
| 開發任務 | `docs/specs/{模組代碼}/tasks.md` | 任務清單與執行順序 |
| 研究紀錄 | `docs/specs/{模組代碼}/research.md` | 設計決策與排除方案 |

## Git 操作提醒

- **修改共用檔案前**（`docs/_refs/00-主文件.md`、`docs/_refs/06-報表需求.md`、`README.md` 等跨模組檔案），Claude 必須提醒使用者先執行 `git pull --rebase`，改完立即 commit & push
- push 前一律 `git pull --rebase`，避免多餘 merge commit
