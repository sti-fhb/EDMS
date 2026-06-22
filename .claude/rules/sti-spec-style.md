---
description: 正式 spec / use-case / requirement 文件撰寫規範；寫或改 docs/specs、docs/use-cases、docs/requirements 下的 .md 時載入
paths:
  - "docs/specs/**/*.md"
  - "docs/use-cases/**/*.md"
  - "docs/requirements/**/*.md"
---

# Spec 文件撰寫規範

## 1. 不得出現建模工具相關字眼或內部識別碼

**為什麼**：spec / use-case / requirement 是給 PG、外部開發者、QA、PM 等多角色看的權威設計文件，讀者**不一定知道 EA（Enterprise Architect）是什麼工具**。文件應自包含、業務語言優先；建模工具僅是 SA 的內部產出來源，工具相關識別碼（Object_ID / GUID）對讀者無意義且難以維護同步。

### 禁止出現的內容

- 工具名稱字眼：`EA`、`Sparx`、`Enterprise Architect`、`EA Model`
- 工具角色字眼：`EA Rule`、`EA UseCase`、`EA Diagram`、`EA Tagged Values`、`EA code`、`EA 對應`
- 內部識別碼：
  - GUID（`{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}` 格式）
  - Object_ID / Package_ID / Element_ID 整數
- 工具檔案路徑：`TSBMS三總捐供血R.eap` 等
- 工具操作描述：「從 EA 刪除」「對齊 EA」「EA 為 source of truth」

### 改寫範例

| ❌ 違規寫法 | ✅ 正確寫法 |
|------------|-----------|
| `對應 EA Model Activity<<功能選項>>` | （刪除整段，spec 不需引用工具結構） |
| `EA Rule「離線原則」（GUID `{2B94...}`）` | `[§離線原則](spec.md#離線原則r03)`（章節錨點） |
| `SRVDP020 從 EA 刪除` | `SRVDP020 已廢除` / `SRVDP020 已停用` |
| `對齊 EA UCLB101` | `對齊 UCLB101` |
| `EA UC 圖見 [...]` | `UC 圖見 [...]` |
| `EA code: DP_OPERATION_MODE` | `PARAM_ID: DP_OPERATION_MODE` |
| `EA 對應` 欄位 | （整欄刪除） |

## 2. 不建立 ea-notes.md 或同類輔助筆記

**為什麼**：建模工具本身即權威來源，spec 端再放一份徒增雙向同步成本，且該檔案會違反規則 1（必含工具識別碼）。

- 不在 `docs/specs/{模組}/` 下建立 `ea-notes.md`
- 既有的 `ea-notes.md` 應刪除（截至 2026-04-29，所有模組已清空）
- EA 操作後記錄的 Object_ID / GUID 僅用於當下對話脈絡，不落地到任何 md 檔

## 3. 例外（允許保留 ID 欄位的檔案）

下列檔案**本質為工具 dump 或對外資料**，允許含原始 ID 欄位：
- `docs/dd/{模組}/DD-*.md`（DD export，本質為工具匯出）
- `_refs/` 下的原始分析資料（非 spec 產出）

但 `docs/dd/{模組}/` 下若僅是過時的非 export 文字檔（非 dump 格式），仍應對齊規則 1。

## 4. 業務語言參照原則

正式描述中可用：
- **業務代碼名稱**：如「代碼表 LB_TYPE」「參數 DP_OPERATION_MODE」「FR-001」「UCDP008」
- **章節錨點**：如 `[§離線原則](spec.md#離線原則r03)`、`[US3](spec_us3.md)`
- **編碼規則描述**：如「同功能選項編碼規則（模組碼 + 流水號）」

不可用：
- 工具內部識別（GUID / Object_ID）
- 「EA」相關字眼

## 5. 檢核（撰寫或修改後）

寫或更新文件後執行以下 grep（無結果即合規）：

```bash
grep -rE "\bEA\b|Sparx|Enterprise Architect|\{[A-F0-9]{8}-[A-F0-9]{4}-" docs/specs docs/use-cases docs/requirements
```

> 此檢核也適用於本檔本身——本檔的「EA」「Enterprise Architect」字眼是規則描述用，不算違規；檢核時僅針對 spec / UC / RQ 文件。

## 變更歷史

- **2026-04-20** 使用者首次明示「正式 md 不要有 EA」
- **2026-04-29** 使用者再度強調，理由「其他人不知 EA 是什麼」；本規則由記憶升級為永久 rule
