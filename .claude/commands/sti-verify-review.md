執行以下步驟，驗證指定 GitHub Pull Request 的 Review 報告正確性，自動偵測 **STALE**（基於舊版程式碼）與 **HALLUCINATION**（AI 幻覺）問題。

## 參數說明（$ARGUMENTS）

| 參數 | 說明 | 範例 |
|------|------|------|
| `#編號` 或 `編號` | 要驗證的 PR 編號（必填）| `/sti-verify-review #43` 或 `/sti-verify-review 43` |
| `--all` | 驗證該 PR 所有 review（含歷史），而非僅最新一輪 | `/sti-verify-review #43 --all` |
| `--id ID` | 驗證指定 review ID | `/sti-verify-review #43 --id 123` |

## 核心概念

| 判定 | 定義 |
|------|------|
| ✅ **CONFIRMED** | Review 指出的問題在 PR 最新版程式碼中確實存在 |
| ⏳ **STALE** | 問題曾經存在，但已在後續 commit 中修正（Review 基於舊版） |
| ❌ **HALLUCINATION** | 問題在所有版本的程式碼中都不存在（AI 幻覺） |
| ⚪ **UNVERIFIABLE** | 主觀建議（DESIGN / STYLE 類），無法以程式碼比對判定對錯 |
| 🔵 **INTEGRATION** | reviewer 標為「🔵 整合/Sync 後待辦」的項目，非 PR 缺陷、不驗證、不計入可信度 |

## 執行步驟

### 1. 解析參數

從 `$ARGUMENTS` 解析：
- **PR 編號**（去除 `#` 符號）。**必須為純數字（正整數）**，若包含非數字字元或未傳入，提示：「請提供 PR 編號，例如：`/sti-verify-review #43`」，並停止執行。
- **`--all` 旗標**：是否驗證所有 review（預設為 `false`，僅驗證最新一筆）。
- **`--id ID`**：指定的 review ID（**必須為純數字**）。若提供，僅驗證該筆 review（即使是 DISMISSED 狀態也會驗證）。

> **預設模式（不帶 `--all`）**：僅驗證 `submitted_at` 最大的那一筆 review。若有多筆 review 的 `submitted_at` 相同（秒級），全部驗證。

### 2. 取得 PR 資訊

依序取得（可平行執行）：

```bash
# 2a. PR 基本資訊
gh pr view {編號} --json number,title,state,author,headRefName,baseRefName

# 2b. PR 所有 commits（SHA + 時間戳）
gh pr view {編號} --json commits --jq '.commits[] | {sha: .oid, message: .messageHeadline, date: .committedDate}'

# 2c. 取得 repo owner/name
gh repo view --json owner,name --jq '"\(.owner.login)/\(.name)"'

# 2d. PR 所有 reviews（body + submitted_at）
# 注意：不使用 != — Claude Code Bash tool 會將 ! 轉義導致 jq 解析失敗
# 排除 DISMISSED review（預設不驗證）；--id 模式下需額外撈取 DISMISSED
gh api repos/{owner}/{repo}/pulls/{編號}/reviews --paginate --jq '.[] | select(.state == "APPROVED" or .state == "CHANGES_REQUESTED" or .state == "COMMENTED") | {id: .id, user: .user.login, state: .state, body: .body, submitted_at: .submitted_at}'
# 若使用 --id 模式，額外撈取所有狀態（含 DISMISSED）以便比對：
# gh api repos/{owner}/{repo}/pulls/{編號}/reviews --paginate --jq '.[] | {id: .id, user: .user.login, state: .state, body: .body, submitted_at: .submitted_at}'

# 2e. PR 最新 HEAD SHA
gh pr view {編號} --json headRefOid --jq '.headRefOid'
```

若 PR 狀態為 MERGED 或 CLOSED，提示使用者：
```
此 PR 已 {MERGED/CLOSED}。
  1. 仍要驗證
  2. 取消
```

> **過濾規則**：
> - 排除 review body 為空字串或 null 的 review（純 approve 無留言），輸出：「Review {id} by {user} 無 body 內容，跳過。」
> - 預設模式與 `--all` 模式：排除 `state == "DISMISSED"` 的 review。
> - `--id` 模式：不排除 DISMISSED，即使已被 dismiss 也會驗證。

### 3. 建立時間軸

將步驟 2 取得的 commits 和 reviews 按時間排序，產出對照表：

```markdown
### 時間軸
| 時間 | 事件 |
|------|------|
| 2026-03-11T10:00:00Z | 📝 Commit `f8544a4` - initial implementation |
| 2026-03-11T14:30:00Z | 📝 Commit `c867281` - fix type annotations |
| 2026-03-12T06:05:35Z | 🔍 Review 5 by Sandra-168 (CHANGES_REQUESTED) |
```

初步判斷 stale 風險（基於 review `submitted_at` 與 PR 最新 commit 時間差）：
- Review 在最新 commit **之後** 提交 → **低風險**（reviewer 可能已看到最新版）
- Review 在最新 commit **之前** 提交：
  - 間隔 < 5 分鐘 → **高風險**（可能在 commit 推送前就開始 review）
  - 間隔 5–30 分鐘 → **中風險**
  - 間隔 > 30 分鐘 → **需看中間有多少 commit**（commit 越多，stale 可能性越高）

> **注意**：以上為啟發式判斷，時間差僅能反映 review 提交與 commit 合入的順序，無法確認 reviewer 開始閱讀時是否已看到最新 commit。實際 stale 狀況仍以步驟 5b 的程式碼比對結果為準。

### 4. 解析 Review 報告

從 review body 解析結構化發現。**優先依 `/sti-pr-review` 的固定格式解析**：

#### 4a. 結構化格式（`/sti-pr-review` 產出）

識別特徵（使用**前綴比對**，忽略標題後的中文括號說明）：
- 標題以 `### 🔴 CRITICAL` 開頭（完整格式：`### 🔴 CRITICAL（必須修正）`）
- 標題以 `### 🟠 HIGH` 開頭（完整格式：`### 🟠 HIGH（強烈建議修正）`）
- 標題以 `### 🟡 MEDIUM` 開頭（完整格式：`### 🟡 MEDIUM（建議改善）`）
- 標題以 `### 🟢 LOW` 開頭（完整格式：`### 🟢 LOW（可選改善）`）
- 標題以 `### 🔵 整合/Sync 後待辦` 開頭（完整格式：`### 🔵 整合/Sync 後待辦（非 PR 現有缺陷）`）
- 每項發現含 `- **檔案**：`、`- **問題**：`、`- **建議修正**：`（🔵 區塊另含 `- **來源**：`）

解析規則：
1. 依嚴重等級標題切分區塊
2. 在每個區塊內，依 `**檔案**：` 欄位分割每項發現
3. 提取：
   - **severity**：從區塊標題取得（CRITICAL / HIGH / MEDIUM / LOW / INTEGRATION）
   - **編號**：如 `C-1`、`HIGH-1`、`M-2`、`LOW-3`（若報告中有編號則沿用，否則自動產生）
   - **file_path**：從 `**檔案**：` 提取（格式 `file_path:line_number`）
   - **claim**：從 `**問題**：` 提取（review 對程式碼的斷言/描述）

> **🔵 整合/Sync 後待辦（severity=INTEGRATION）特別處理**：此類項目是 reviewer 明確標示「非 PR 現有缺陷、根植於 main-merge」的整合提醒，**不代表 PR 缺陷**。
> - **不**以 PR 真實 HEAD 當「PR 缺陷」驗證（跳過步驟 5 的 CONFIRMED / HALLUCINATION 判定）。
> - **不計入**可信度計算的分母（比照 UNVERIFIABLE 排除）。
> - 於報告「驗證結果」表另列一列，判定欄標 `🔵 整合待辦（未驗）`，證據欄註明來源檔案。
> - 若 reviewer 把整合待辦誤放進 🔴/🟠/🟡/🟢 缺陷區塊（未歸類到 🔵），仍照該等級正常驗證——本規則只認 reviewer 主動標示的 🔵 分類。

#### 4b. 非結構化格式（降級解析）

若 review body 不符合 `/sti-pr-review` 格式，進入「盡力解析」模式：
- 搜尋包含檔案路徑（含 `/` 或 `.py`、`.ts` 等副檔名）的段落
- 提取該段落的描述作為 claim
- severity 統一標記為 `UNKNOWN`

#### 4c. Claim 類型分類

對每項 claim 進行分類，決定可驗證性：

| 類型 | 特徵關鍵字 | 可驗證性 | 驗證方式 |
|------|-----------|---------|---------|
| `MISSING` | 「缺少」「沒有」「未包含」「缺」「missing」「no」「lack」 | 高 | 確認宣稱缺少的東西是否真的不存在 |
| `WRONG_USAGE` | 「應使用 X 而非 Y」「改用」「應該」「instead of」 | 高 | 讀取程式碼比對實際寫法 |
| `SECURITY` | 「硬編碼」「injection」「XSS」「token」「密碼」「secret」 | 高 | 搜尋特徵 pattern |
| `STYLE` | 「命名」「過長」「巢狀」「格式」「naming」 | 中 | 可驗證但有主觀成分 |
| `DESIGN` | 「建議」「可考慮」「架構」「suggest」「consider」 | 低 | 標記為 UNVERIFIABLE |

### 5. 逐項驗證

**此步驟為核心**。對每項可驗證的發現（排除 `DESIGN` 類與 🔵 INTEGRATION 類），從 PR 分支最新 HEAD 讀取實際程式碼進行比對。

> **重要**：此步驟使用 `git show` 唯讀讀取程式碼，不需建 worktree。需要先 fetch PR 分支。
>
> 若本地已有 `pr-review-{編號}` 分支（由 `/sti-pr-review` 建立），可直接重用，不需再 fetch：
> ```bash
> git show pr-review-{編號}:{file_path}
> ```
>
> 否則建立 `pr-verify-{編號}` 暫存分支：
> ```bash
> # 安全性檢查：若同名分支已存在，提示使用者
> if git branch --list pr-verify-{編號} | grep -q .; then
>   echo "WARNING: 本地已有 pr-verify-{編號} 分支，將被覆蓋。"
> fi
> git fetch origin pull/{編號}/head:pr-verify-{編號} --force
> ```

#### 5a. 驗證最新版（Latest HEAD）

> **`git show` 失敗處理**：若 `git show` 回傳非零退出碼（檔案不存在或路徑有誤），該項標記為 **UNVERIFIABLE** 並附註「無法讀取 `{file_path}`」，**不得**視為 CONFIRMED 或 HALLUCINATION。

依 claim 類型選擇驗證方式：

**MISSING 類**（「缺少 X」）：
```bash
# 用 git show 讀取最新版檔案
git show pr-verify-{編號}:{file_path}
# 或用 Grep 搜尋特定 pattern（如型別標註、import 語句）
```
- 若宣稱缺少的東西**確實不存在** → 暫定 CONFIRMED
- 若宣稱缺少的東西**實際存在** → 進入 5b 追溯

**WRONG_USAGE 類**（「使用了 X，應改用 Y」）：
```bash
git show pr-verify-{編號}:{file_path}
```
- 讀取對應程式碼，確認實際使用的寫法
- 若**確實使用了 X** → 暫定 CONFIRMED
- 若**已使用 Y** → 進入 5b 追溯

**SECURITY 類**（「硬編碼密碼」「SQL injection」）：
```bash
git show pr-verify-{編號}:{file_path}
```
- 搜尋特徵 pattern（硬編碼字串、raw SQL 拼接等）
- 若**確實存在** → 暫定 CONFIRMED
- 若**不存在** → 進入 5b 追溯

**STYLE 類**（「命名不佳」「函式過長」）：
- 讀取程式碼做基本驗證（如計算函式行數、檢查命名）
- 若客觀指標可驗證（如行數）→ CONFIRMED 或進入 5b
- 若純主觀 → UNVERIFIABLE

#### 5b. STALE 追溯（回溯歷史 commit）

當步驟 5a 判定「最新版不成立」時，回溯歷史 commit 確認 claim 曾經成立的版本：

```bash
# 取得 PR 的 commit 列表（最新在前，上限 10 個）
git log pr-verify-{編號} --oneline -10

# 逐一檢查歷史版本
git show {older_sha}:{file_path}
```

遍歷順序：從最新 commit 往回追溯（跳過 HEAD，因 5a 已確認不成立）。

判定規則：
- **找到成立的版本** → **STALE**（標注：成立版本 SHA、修正版本 SHA）
- **所有歷史版本都不成立** → **HALLUCINATION**
- **檔案在歷史版本中不存在**（新增檔案）→ 若 claim 是 MISSING 類且檔案從第一個 commit 起就有該內容 → **HALLUCINATION**

#### 5c. 驗證進度報告

每驗證完一項，簡短輸出進度（避免長時間無回饋）：
```
[3/8] HIGH-1: repository 缺型別註解 → ❌ HALLUCINATION（型別完整存在於所有版本）
[4/8] HIGH-2: update/delete 未注入 payload → ✅ CONFIRMED
```

### 6. 產出驗證報告

將所有驗證結果整理為結構化報告：

```markdown
## 🔎 Review 驗證報告

**PR**: #{編號} — {PR 標題}
**驗證對象**: Review {review_id} by {reviewer} ({submitted_at})
**PR 最新 commit**: {head_sha_short} ({commit_date})
**時間差**: {時間差描述}（{高/中/低} stale 風險）

### 時間軸
| 時間 | 事件 |
|------|------|
| {時間} | {事件描述} |
| ... | ... |

### 驗證結果

| # | 等級 | 項目摘要 | Claim 類型 | 判定 | 證據 |
|---|------|---------|-----------|------|------|
| HIGH-1 | 🟠 | repository 缺型別註解 | MISSING | ❌ HALLUCINATION | `get_list(db: AsyncSession, page: int...)` 型別完整 |
| HIGH-2 | 🟠 | update/delete 未注入 payload | MISSING | ✅ CONFIRMED | `update_ref_code` 確實無 payload 參數 |
| M-1 | 🟡 | 建議抽取常數 | DESIGN | ⚪ UNVERIFIABLE | 主觀設計建議 |
| ... | | | | | |

### 統計

| 判定 | 數量 | 佔比 |
|------|------|------|
| ✅ CONFIRMED | {N} | {X}% |
| ⏳ STALE | {N} | {X}% |
| ❌ HALLUCINATION | {N} | {X}% |
| ⚪ UNVERIFIABLE | {N} | {X}% |
| 🔵 INTEGRATION（整合待辦，未驗） | {N} | {X}% |

### STALE 詳情（若有）

| # | 項目 | 成立版本 | 修正版本 |
|---|------|---------|---------|
| {編號} | {摘要} | `{sha_short}` ({date}) | `{sha_short}` ({date}) |

### HALLUCINATION 詳情（若有）

| # | 項目 | Review 聲稱 | 實際程式碼 |
|---|------|-----------|-----------|
| {編號} | {摘要} | {review 的描述} | {實際程式碼片段或 grep 結果} |

### 結論

**Review 可信度**：{高/中/低}
- 高：90%+ 可驗證項目正確（CONFIRMED），無 HALLUCINATION
- 中：70–89% 可驗證項目正確，或有 1 項 HALLUCINATION
- 低：< 70% 可驗證項目正確，或有 2+ 項 HALLUCINATION

**需注意**：{列出所有 STALE 和 HALLUCINATION 項目的簡要摘要}
```

> **可信度計算**：僅計算可驗證項目（排除 UNVERIFIABLE）。
>
> 兩個指標：
> - **正確率**（reviewer 判斷能力）：`(CONFIRMED + STALE) / (CONFIRMED + STALE + HALLUCINATION) * 100%`
>   - STALE 算「正確」是因為 reviewer 的觀察在當時版本是正確的，只是時間差問題
> - **時效性**（review 是否基於最新版）：`CONFIRMED / (CONFIRMED + STALE) * 100%`
>
> 可信度等級以**正確率**為主要依據：
> - 高：正確率 90%+，且無 HALLUCINATION
> - 中：正確率 70–89%，或有 1 項 HALLUCINATION
> - 低：正確率 < 70%，或有 2+ 項 HALLUCINATION

### 7. 詢問後續動作

報告產出後，詢問使用者：

```
是否要將驗證報告貼到 PR comment？
  1️⃣ 貼到 PR（發布到 PR 頁面）
  2️⃣ 僅本地查看（不提交）
```

若使用者選擇「貼到 PR」，使用 `--body-file` 避免 shell 跳脫問題（與 `/sti-pr-review` 保持一致）：

```
Step A：使用 Write tool 將驗證報告寫入 /tmp/sti-verify-review-{編號}-body.md
Step B：執行以下指令發布並清理暫存檔：
```

```bash
gh pr comment {編號} --body-file "/tmp/sti-verify-review-{編號}-body.md" && rm -f "/tmp/sti-verify-review-{編號}-body.md"
```

貼上成功後顯示：「✅ 驗證報告已貼到 PR #{編號}。」

### 8. 清理

驗證完成後，若步驟 5 建立了 `pr-verify-{編號}` 分支，刪除該暫存分支：

```bash
# 僅刪除本指令建立的 pr-verify- 前綴分支
if git branch --list "pr-verify-{編號}" | grep -q .; then
  git branch -D "pr-verify-{編號}"
  echo "已刪除暫存分支 pr-verify-{編號}"
fi
```

> 若步驟 5 重用了 `/sti-pr-review` 的 `pr-review-{編號}` 分支，此步驟不執行任何清理（保留給 `/sti-pr-review` 管理）。重用時不 fetch，直接使用現有本地分支狀態，避免 `pr-review-{編號}` 被意外更新到不同 SHA。

## 多 Review 驗證模式

### `--all` 模式

依 `submitted_at` 從舊到新逐一驗證每筆 review，每筆產出獨立的驗證報告區塊。

> **安全上限**：若 review 數量超過 5 筆，先顯示列表讓使用者選擇：
> ```
> 此 PR 共有 {N} 筆 review，預估驗證時間較長。
>   1. 驗證全部
>   2. 選擇特定 review（請輸入 --id）
>   3. 取消
> ```

最後附上彙總統計：

```markdown
### 彙總（所有 Review）

| Review | Reviewer | 可信度 | CONFIRMED | STALE | HALLUCINATION | UNVERIFIABLE |
|--------|----------|--------|-----------|-------|---------------|--------------|
| Review 4 | user-A | 中 | 5 | 1 | 1 | 2 |
| Review 5 | user-B | 低 | 3 | 0 | 2 | 1 |
```

### `--id ID` 模式

僅驗證 `id` 匹配的 review。若 ID 不存在，提示：「找不到 Review ID {ID}，可用的 Review ID 有：{列表}」。

## 限制與注意事項

1. **此 agent 本身也可能幻覺**：但工作是「讀程式碼 → 比對文字描述」而非「生成新分析」，幻覺風險遠低於 review agent。驗證結論應附上程式碼證據（git show 輸出片段），讓使用者可自行確認。
2. **主觀項目無法驗證**：DESIGN / STYLE 類建議只能標 UNVERIFIABLE，不要強行判定。
3. **Review 格式依賴**：非 `/sti-pr-review` 產出的 review 解析精度較低，會進入降級解析模式。
4. **Commit 歷史上限**：STALE 追溯最多回溯 10 個 commit，超過此範圍的歷史版本不會檢查。
5. **DISMISSED review**：預設模式與 `--all` 模式排除 DISMISSED review（步驟 2d 的 jq filter 不撈取）。`--id` 模式下會撈取所有狀態，即使已被 dismiss 也會驗證。
6. **語言**：驗證報告使用繁體中文。
