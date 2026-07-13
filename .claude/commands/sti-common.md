本指令為 STI 指令系列的共用規則說明，供使用者查閱。直接輸出以下內容，不需執行任何工具。

---

# STI 指令共用規則

## 確認機制

所有 STI 指令統一使用以下確認機制。所有需要使用者確認的環節，一律提供**數字選項**，使用者輸入數字即可：

| 使用者回覆 | 動作 |
|---------|------|
| 數字（如 `1`、`2`、`3`） | 執行對應選項 |
| 直接輸入文字 | 視為自訂內容（如自訂分支名、修改 commit message） |
| `0` / `取消` | 停止並顯示「已取消。」 |

選填欄位若不填寫，請輸入「無」或 `skip`。

---

## Issue 狀態顏色規則

| 條件 | 顯示 |
|------|------|
| OPEN，無負責人 | 🔴 OPEN |
| OPEN，有負責人 | 🟡 OPEN |
| CLOSED | 🟢 CLOSED |

## PR 狀態顏色規則

| 條件 | 顯示 |
|------|------|
| OPEN，非草稿 | 🟢 OPEN |
| OPEN，草稿 | ⚪ DRAFT |
| MERGED | 🟣 MERGED |
| CLOSED（未合併）| 🔴 CLOSED |

## Label 意義對照

| Label | 意義 |
|-------|------|
| `blocked` | 等待其他 Issue 完成才能開始 |

---

## 自動偵測關聯 Issue

以下指令支援自動偵測：`/sti-commit`、`/sti-pr-create`

偵測優先順序：
1. `$ARGUMENTS` 傳入的 Issue 編號（優先）
2. 掃描 git log 找出 `close #xx`：
   ```
   git log main..HEAD --oneline | grep -oE "#[0-9]+" | head -1
   ```
3. 找不到 → 詢問使用者手動輸入或輸入「無」

---

## Issue 標題轉分支名稱規則

以下指令使用此規則：`/sti-implement`

轉換步驟：
1. 移除方括號標記（如 `[Foundation]`、`[Phase 1]`）
2. 轉為全小寫
3. 空白與特殊字元替換為連字號 `-`
4. 移除連續連字號與首尾連字號
5. 加上前綴：`feature/{結果}`

範例：`[Foundation] 新增 Issue 管理指令` → `feature/issue-management-commands`

---

## 環境說明

- **Claude 工具呼叫（Bash tool）**：一律使用 bash 語法
- **使用者手動執行**：一律使用 bash 語法（pnpm、uv run 等）
- 嚴禁直接修改 `main` 分支，所有開發在 feature 分支進行

---

## 複雜度分級（預判 issue 規模）

以下指令使用此規則：`/sti-sa-precheck`、`/sti-plan`、`/sti-implement`

對照下表打分，任一指標達「複雜」門檻即視為複雜：

| 指標 | 簡單 | 複雜 |
|------|------|------|
| FR 數 | ≤ 5 | > 5 |
| AC 數 | ≤ 5 | > 5 |
| 訊息類型 | ≤ 5 | > 10 |
| 跨模組依賴 | 無 | 有 |
| 獨有業務邏輯主題 | 0 | ≥ 2 |

各指令據此的動作：

- `/sti-plan`：多數指標為簡單 → 10 節模板；任一達複雜門檻 → 18 節模板。
- `/sti-sa-precheck`：越複雜，越要確保 A-3（contracts）/ A-5（一致性交叉）到位。
- `/sti-implement`：無 `/sti-plan` 規劃留言時，若達複雜門檻 → 提示先跑 `/sti-plan`（見該指令步驟 7）。
