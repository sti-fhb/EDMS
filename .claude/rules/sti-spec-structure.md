---
description: 模組 spec 與 wireframe 之目錄與檔案結構慣例；寫或改 docs/specs/{模組} 與 docs/wireframes/{模組} 時載入
paths:
  - "docs/specs/**/*.md"
  - "docs/wireframes/**/*.html"
  - "docs/wireframes/**/*.md"
---

# 模組 Spec 與 Wireframe 結構規範

> **Source of truth**：BS（供應）模組為**典範參考**。新模組或既有模組調整 spec / wireframe 時，必須對齊 BS 結構。
>
> **Why**：避免每模組各自發明結構，造成 PG / QA / 跨模組 SA review 時需重新理解；統一結構也讓 codemaps / 文件產生 / IDE 索引運作正常。

---

## 1. Spec 目錄結構（`docs/specs/{模組代碼}/`）

### 必含項目

```
docs/specs/{模組代碼}/
├── spec.md                     # 模組總覽（含 US 索引、Clarifications、Edge Cases、Key Entities、Success Criteria、Assumptions、Dependencies、Out of Scope、外部參考、異動紀錄）
├── spec_us1.md                 # 各 User Story 獨立規格
├── spec_us2.md
├── ...                         # spec_us{N}.md
├── data-model.md               # ERD（Mermaid）+ 實體屬性 + 業務規則
├── plan.md                     # 實作計畫
├── research.md                 # 設計決策紀錄
├── tasks.md                    # 開發任務清單
├── issues.md                   # GitHub Issues 清單（每個 US 一張 issue + Foundation + Polish；對齊 sti-issue-create canonical 模板）
├── contracts/                  # 跨模組 SRV / API 契約
│   └── SRVxxx-xxx.md
└── checklists/
    └── requirements.md         # 規格品質檢核
```

### 可選項目（依模組需要）

- `codelists.md` — 代碼表權威定義（如 CP 模組）
- `endpoints/` — 內部前端→後端 endpoint 規格（如 CP 模組之 cp01-receive.md）
- `*.png` / 流程圖 — UC 流程圖匯出

### 禁止項目

- ❌ `ea-notes.md` 或同類輔助筆記（per [`sti-spec-style.md`](sti-spec-style.md)）
- ❌ IDE 設定檔（`.code-workspace` / `.vscode/`）
- ❌ 工具 dump 之檔案（屬 `docs/dd/{模組}/` 範圍）

### `spec.md` 必含區塊

- **User Stories 索引**（含 US / 對應 UC / 名稱 / Priority / 規格檔超連結）
- **Clarifications**（依日期分 Session）
- **系統訊息類型定義**（5 類：錯誤 / 警告 / 確認 / 成功 / 提示）
- **Edge Cases（跨 US 共用）**
- **Key Entities**（業務語意，schema 詳見 data-model.md）
- **Success Criteria**（可量化指標 SC-XXX）
- **Assumptions / Dependencies / Out of Scope**
- **外部參考**（相對連結至 plan.md / contracts / data-model.md / codelists.md / research.md / tasks.md / issues.md）
- **異動紀錄**

### `spec_us{N}.md` 必含區塊

- **對應 UC / 功能選項 / Priority / Wireframe / 回到 spec.md**
- **User Story**（描述 + Why this priority + Independent Test）
- **Acceptance Scenarios**（Given / When / Then 格式）
- **Functional Requirements**（FR-{模組}-XXX 編號）
- **依賴**（跨 US / 跨模組 / 主檔）
- **系統訊息**（Code 對應前述 5 類）
- **相關文件**

### `issues.md` 必含區塊

- **Issue 總覽 table**（# / 標題 / 階段 / 畫面 / US / FR / 規格檔 / 依賴）
- **每個 Issue** 之完整 body（對齊 `.claude/commands/sti-issue-create.md` canonical 模板）：
  - 任務說明 / 範圍（後端 / 前端 / 測試 拆分）/ 驗收條件 / 依賴 / 注意事項 / 相關文件

---

## 2. Wireframe 目錄結構（`docs/wireframes/{模組代碼}/`）

### 必含項目

```
docs/wireframes/{模組代碼}/
└── index.html                  # 單一 HTML 檔，內嵌所有畫面 + sidebar + 切換邏輯
```

### 結構慣例（**強制對齊 BS 模式**）

`index.html` **必須**符合：

1. **單一檔案**：所有畫面整合於同一 `index.html`
2. **Sidebar + data-screen 屬性**：sidebar 用 `<a data-screen="screen-id">` 標記，點擊切換顯示對應 `<div id="screen-id">`
3. **不使用 iframe**：避免跨檔案載入造成 review / debug 困難
4. **不分檔**：不可拆成 `cp01.html` / `cp02.html` / `bs01.html` 等獨立檔
5. **可選 CDN**：可引用 Bootstrap / Bootstrap Icons / Chart.js 等 CDN 統一風格

### 範本參考

```html
<!-- index.html 骨架（依 BS 模式） -->
<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <title>國軍捐血管理系統 — {模組名稱} Wireframe</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <!-- ... CDN ... -->
</head>
<body>
  <nav class="navbar navbar-tsbms"><!-- 上方導覽 --></nav>
  <div class="d-flex">
    <aside class="sidebar">
      <a class="nav-link" href="#" data-screen="screen-1">畫面1</a>
      <a class="nav-link" href="#" data-screen="screen-2">畫面2</a>
      <!-- ... -->
    </aside>
    <main class="content">
      <div id="screen-1" class="screen">畫面1 內容</div>
      <div id="screen-2" class="screen d-none">畫面2 內容</div>
      <!-- ... -->
    </main>
  </div>
  <script>
    // sidebar 點擊切 screen
    document.querySelectorAll('[data-screen]').forEach(a => {
      a.addEventListener('click', e => {
        e.preventDefault();
        const id = a.getAttribute('data-screen');
        document.querySelectorAll('.screen').forEach(s => s.classList.add('d-none'));
        document.getElementById(id).classList.remove('d-none');
      });
    });
  </script>
</body>
</html>
```

### 禁止項目

- ❌ 將每個畫面拆為獨立 `.html` 檔（如 `cp01.html` / `bs03.html`）
- ❌ `index.html` 用 `<iframe>` 載入子畫面
- ❌ 缺 `index.html`（如先前 DP 模組僅有 `dp10.html`）

### 樣式內部說明（per `feedback_wireframe_internal_note_style`）

- **操作者可見**之文字 / hint：用一般灰字 italic（`form-hint` class）
- **內部設計註記**（給 SA / 開發者參考）：用**深綠 italic + 💡**（`internal-note` class）

### 業務術語（per `feedback_wireframe_term_grid_to_list`）

- 操作者可見處用「列表」/「清單」字眼，**不**用「grid」（CSS class 名可保留 grid）

### Sample 資料（per `feedback_sample_blood_bag_prefix`）

- mock 血袋條碼一律 **`T8869`** 開頭

---

## 3. 違規檢核（撰寫或修改後）

### Spec 結構檢核

```bash
# 確認必含檔案存在
test -f docs/specs/{模組}/spec.md && \
test -f docs/specs/{模組}/data-model.md && \
test -f docs/specs/{模組}/plan.md && \
test -f docs/specs/{模組}/research.md && \
test -f docs/specs/{模組}/tasks.md && \
test -f docs/specs/{模組}/issues.md && \
test -d docs/specs/{模組}/contracts && \
test -d docs/specs/{模組}/checklists && \
echo "Spec structure OK"

# 確認無 IDE 設定誤放
find docs/specs/{模組}/ -name "*.code-workspace" -o -name ".vscode" | head -5
# (無輸出 = 合規)
```

### Wireframe 結構檢核

```bash
# 確認單一 index.html
ls docs/wireframes/{模組}/*.html
# 應只看到 index.html；多檔（cp01.html 等）= 違規

# 確認不用 iframe
grep -c iframe docs/wireframes/{模組}/index.html
# 應為 0（CDN 用的 script 不算）
```

---

## 4. 既有模組合規狀態（2026-05-07 對照）

| 模組 | spec 結構 | wireframe 結構 | 狀態 |
|------|----------|---------------|------|
| **BC** | — | 單一 index.html | ✅ 合規 |
| **BS** | ✅ 完整 | 單一 index.html | ✅ **典範** |
| **CP** | ✅ 完整（issues.md 2026-05-07 補入）| ⚠️ **需整合**（cp01/02/11/12 → index.html）| ⚠️ wireframe 待修 |
| **DP** | ⚠️ 待清 IDE 檔（已修）| ⚠️ **需建 index.html 框架**（dp10.html 整合進去）| ⚠️ wireframe 待修 |

---

## 變更歷史

- **2026-05-07** 首版建立。對齊 BS 模組結構，列出 spec / wireframe 之必含 / 禁止項目，提供檢核命令；既有模組（CP / DP）合規狀態列出待修項目。
