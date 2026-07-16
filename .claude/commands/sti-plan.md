執行以下步驟，為指定 Issue 做「實作前盤點」：讀規格 → 判複雜度選模板 → 寫規劃留言 → 幻覺檢查列出真 SA Q → 給使用者 review 後 post 到 issue，最後建議銜接 `/sti-implement`。

## 適用對象

此指令給 SD（開發者）在**開工前**使用，產出 issue 上的「規劃留言 + SA Q 留言」。

> 與 `/sti-sa-precheck`（SA 規格交付自檢）、`/sti-implement`（開工實作）區隔：
> `/sti-plan`（規劃）→ ⏳ 等 SA 回 Q → `/sti-implement`（開工）。
> 本指令**不開分支、不碰程式碼**，只產出 issue 留言。

## 確認機制

需要使用者確認的環節一律提供**數字選項**：

| 使用者回覆 | 動作 |
|---------|------|
| 數字（如 `1`、`2`） | 執行對應選項 |
| 直接輸入文字 | 視為自訂內容 |
| `0` / `取消` | 停止並顯示「已取消。」 |

## 參數說明（$ARGUMENTS）

| 參數 | 說明 | 範例 |
|------|------|------|
| `#編號` 或 `編號` | 要盤點的 Issue 編號（必填）| `/sti-plan #432` |

---

## 執行步驟

### 步驟 0：強制前置（不可跳）

1. **讀 issue 本身，並記下開立者**（決定 SA Q 要 @ 誰）：
   ```bash
   gh issue view {N} -R sti-fhb/EDMS --json number,title,body,author,assignees
   ```
   - 記住 `author.login`，作為步驟 4 SA Q 留言要 @ 的 SA 帳號（`{SA 帳號}`）。
   - 若 issue 開立者明顯不是 SA（例如由 SD 自己補開），改以 `assignees` 中的 SA 或詢問使用者該 @ 誰，**不要寫死特定帳號**。

2. **找同模組已 close 前例 issue 當模板**：
   ```bash
   gh issue list -R sti-fhb/EDMS --search "[{模組}]" --state closed --limit 20
   ```
   挑複雜度相近的，讀其留言：
   ```bash
   gh issue view {前例編號} -R sti-fhb/EDMS --comments
   ```

3. **讀 spec / wireframe / data-model**：
   - `docs/specs/{模組}/spec.md`（總覽 + 訊息類型）
   - `docs/specs/{模組}/spec_us{N}.md`（本 US 規格）
   - `docs/specs/{模組}/data-model.md`（本 issue 相關 Table）
   - `docs/specs/{模組}/contracts/*.md`（本 issue 涉及的跨模組 SRV/API 契約）
   - `docs/wireframes/{模組}/index.html`（grep 出本 issue 對應 screen-id 區段，逐行讀）

4. **跨模組依賴調查**：
   - grep 既有 backend 程式碼確認跨模組工具是否已實作
   - `gh issue list` 查跨模組工具的 issue 是否 merge
   - 依賴未交付 → 列為依賴警示（放入規劃節「依賴與環境」）

---

### 步驟 1：判複雜度，選模板

複雜度分級表見 `/sti-common`「複雜度分級（預判 issue 規模）」（三支指令共用，避免 drift）：

→ 多數指標為簡單用 10 節；任一達複雜門檻用 18 節。顯示判定結果與選用模板。

---

### 步驟 2：寫規劃留言

存於 `/tmp/issue{N}/planning.md`。

**檔案第一行必須是標記**（供 `/sti-implement` 精準辨識規劃留言，不可省略）：

```markdown
<!-- sti-plan:planning -->
```

接著才寫規劃內容。

**18 節（複雜）** — 主體 16 節 + 附錄 2 節：

1. 整體操作流程（A→B→C 字母分段）
2. 畫面草圖（至少 5 狀態，含 hover / 異常）
3. **Wireframe HTML → MUI props 對照表**（逐 class 對 MUI 元件 + props）
4. 訊息類型視覺規則（訊息表 × inline Alert / Dialog / Snackbar / Toast）
5. 後端 API 設計（每 endpoint 路徑 / 權限 / req-resp / error code）
6. 檔案清單（後端 + 前端 + 測試 三類分列）
7. AC → 測試對應
8. Error Codes（對齊 `.claude/rules/sti-error-codes.md`）
9~12. 獨有業務主題 A/B/C/D（依 issue 客製：狀態機 / 識別碼類型 / 加密策略 / cascade 等）
13. 兩段式 TDD 切點（純 layout 階段 A / 邏輯階段 B）
14. 實作順序（後端 → 階段 A 截圖 review → 階段 B；每條 AC 一個 checkpoint commit）
15. 釐清預設與 follow-up（指向 SA Q）
16. 依賴與環境（前置 issue / 跨模組工具 / 表是否建好）
17. 附錄 A：互動行為總覽（場景 / 觸發 / 結果表）
18. 附錄 B：開發前盤點清單（spec / wireframe / data-model 逐項打勾）

**10 節（簡單）** — 由 18 節裁剪：

1. 整體流程　2. 畫面草圖　3. Wireframe → MUI 對照　4. 訊息類型視覺規則
5. 後端 API 設計（含 Error Codes）　6. 檔案清單　7. AC → 測試對應
8. 實作順序（含 TDD 切點）　9. 釐清預設　10. 依賴與環境

> 裁剪規則：砍「獨有業務主題 ABCD」與附錄 A/B；Error Codes 併入 API 設計；兩段式 TDD 併入實作順序。

---

### 步驟 3：列候選 SA Q

存於 `/tmp/issue{N}/sa_questions.md`。開發時遇到的疑問先全列為候選 Q，**不要直接 post**。

---

### 步驟 4：幻覺檢查（最重要）

逐題對照 4 個來源驗證，過濾掉不該問 SA 的：

| 判定 | 動作 |
|------|------|
| spec 已答（spec_us / spec / data-model / contracts / wireframe 寫了）| **撤回**，補 spec 引用 |
| SD 自決（UX / 實作選擇 / 欄位形式 / 檔案位置 / 快取策略）| **撤回**，註明自決理由 |
| 可沿用既有 pattern（前例 issue 已有做法）| **撤回**，引用前例 |
| 真正 spec 未明寫**且**影響業務行為 | **保留** |

經驗值：初版 6~8 條候選，幻覺檢查後通常撤回 4~6 條、留 2~3 條真 Q。

把保留的真 Q 覆寫回 `/tmp/issue{N}/sa_questions.md`，格式：

```markdown
<!-- sti-plan:sa-questions -->
# Issue #{N} — SA Open Questions（開發前釐清）

@{SA 帳號}

於 #{N} 規劃留言中盤點到以下 N 點 spec 未明寫且影響業務行為，請 SA 確認。

> 每題標「阻塞類型」（固定列舉，供 `/sti-implement` 解析「未回覆的 Q 卡到哪」，勿用自由文字）：
> `backend-schema`（卡後端 schema / API 介面）｜`frontend-ux`（純前端狀態 / UX，不卡後端）｜`cross-module`（卡跨模組依賴）｜`none`（不卡骨架，可先開工）

> **自我驗證紀錄**：初版列 X 條候選，對照 spec / data-model / contracts / wireframe 後撤回 Y 條：
> - 撤回項 1（理由）

---

## Q1：{標題}
**阻塞類型**：`backend-schema`
**現況**：...
**選項**：A / B / C
**請 SA 裁示**：...

## Q2：...

---

## 收斂
- 待 SA 回覆後即可開工；Q1 結論前可先以 ... 推進 Phase 1
```

> SA 回覆後若需改 spec，由 SA 同步 `docs/specs`（SD 沿用程式既有命名造成的差異請 SA 後續同步）。

---

### 步驟 5：給使用者 review（禁止直接 post）

**先給使用者看，確認後才 post**。回報：

- 規劃留言節數（18/10）+ 路徑
- SA Q 真題數量 + 撤回幾題（含撤回理由摘要）
- 跨模組依賴狀態（哪個工具 / 表是否已交付）

詢問使用者：

```
盤點完成，是否 post 到 issue #{N}？
  1. 確認 post（先規劃留言、後 SA Q 留言）
  2. 先修改規劃 / SA Q
  3. 取消
```

選 `1` 後依序執行（**順序很重要**：規劃先、SA Q 後，這樣 SA 回覆會接在 SA Q 下方）：

```bash
gh issue comment {N} -R sti-fhb/EDMS --body-file /tmp/issue{N}/planning.md
gh issue comment {N} -R sti-fhb/EDMS --body-file /tmp/issue{N}/sa_questions.md
```

---

### 步驟 6：建議下一步（銜接 /sti-implement）

依步驟 4 各 Q 的「阻塞類型」與後端 / 前端依賴判斷，輸出建議（下表情境與阻塞類型列舉一一對應）：

| 阻塞類型（情境）| 輸出 |
|------|------|
| `none`（或無真 SA Q，不卡任何骨架）| `✅ 盤點完成。可直接開工：/sti-implement #{N}` |
| `backend-schema`（卡後端 schema / API 介面）| `⏳ Q{n} 卡後端介面，建議等 SA 回覆後再執行 /sti-implement #{N}` |
| `frontend-ux`（純前端狀態 / UX，不卡後端）| `✅ 可先做 Phase 1 後端：/sti-implement #{N}；前端 Phase 2 等 SA` |
| `cross-module`（卡跨模組依賴）| `⚠ 依賴 {工具/表} 未交付，先確認是否影響 critical path` |

---

## 不適用盤點的情境（直接跳過，改用 /sti-implement）

清單見 `/sti-common`「不適用『開工前盤點 / 交付前自檢』的情境」（與 `/sti-sa-precheck` 共用）。
