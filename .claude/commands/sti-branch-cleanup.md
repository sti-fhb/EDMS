執行以下步驟，清理本地已失效的分支與 worktree。

## 確認機制

所有需要使用者確認的環節，一律提供**數字選項**，使用者輸入數字即可：

| 使用者回覆 | 動作 |
|---------|------|
| 數字（如 `1`、`2`、`3`） | 執行對應選項 |
| `0` / `取消` | 停止並顯示「已取消。」 |

## 執行步驟

### Phase 1：清理遠端已刪除的本地分支

1. 同步遠端狀態：
   ```
   git fetch --prune
   ```

2. 列出所有本地分支的追蹤狀態：
   ```
   git branch -vv
   ```

3. 取得目前所有 worktree 與其對應分支：
   ```
   git worktree list --porcelain
   ```
   從輸出中擷取每個 worktree 的 `branch` 欄位，用於後續比對 `[gone]` 分支是否有關聯 worktree。

4. 從 step 2 結果中篩選出標記為 `[gone]` 的分支（即遠端已刪除），交叉比對 step 3 的 worktree 清單，整理成表格顯示給使用者。若該分支為目前 HEAD 所在分支，加上「⚠️ 目前分支」標記：

   | 分支名稱 | 最後 commit | 有無 worktree | 備註 |
   |----------|-------------|---------------|------|

   若無任何 `[gone]` 分支，顯示「沒有需要清理的分支」，跳至 Phase 2。

5. 詢問使用者：
   ```
   以上分支的遠端已刪除：
     1. 全部清除
     2. 選擇性刪除
     3. 跳過（進入 Phase 2）
   ```
   - 選擇 `1`：清除全部
   - 選擇 `2`：讓使用者指定要刪除的分支
   - 選擇 `3`：跳至 Phase 2

6. 若待刪除的分支中包含目前 HEAD 所在分支，提示使用者：「目前位於即將刪除的分支 `{分支名稱}`，需先切換至 `main`。」，執行 `git checkout main` 後再繼續。

7. 對每個要刪除的分支：
   - 若有關聯 worktree：
     1. 檢查該 worktree 是否有未提交變更（`git -C {worktree路徑} status --porcelain`）。若有，顯示警告：
        ```
        ⚠️ worktree `{路徑}` 含未提交變更。
          1. 放棄變更並刪除
          2. 跳過此項
        ```
     2. 優先使用 `git worktree remove --force {worktree路徑}` 移除。
     3. 若上述指令失敗，顯示：
        ```
        即將刪除目錄：`{完整路徑}`
          1. 確認刪除
          2. 跳過此項
        ```
        選擇 `1` 後執行 `rm -rf {worktree路徑}`，再執行 `git worktree prune`。
   - 刪除本地分支：`git branch -D {分支名稱}`

8. 顯示清理結果摘要。

### Phase 2：清理已合併 PR 的 Review Worktree

9. 以 `$(git rev-parse --show-toplevel)` 取得 `REPO_ROOT`，檢查 `$(dirname "$REPO_ROOT")/.review-worktree/` 目錄是否存在，若不存在則跳過此 Phase。

10. 列出 `$(dirname "$REPO_ROOT")/.review-worktree/` 下所有子目錄，取得對應的 PR 編號（目錄名格式為 `pr-{編號}`）。

11. 對每個 PR 編號，用 `gh pr view {編號} --json state,title` 查詢狀態。若 `gh pr view` 執行失敗（例如 PR 編號不存在或 GitHub API 錯誤），將該 worktree 標記為「狀態未知」，不自動納入清理範圍，由使用者手動決定是否刪除。

12. 整理成表格顯示：

    | Worktree | PR | 標題 | 狀態 |
    |----------|-----|------|------|

13. 篩選出已合併（MERGED）或已關閉（CLOSED）的 PR，詢問使用者：
    ```
    以下 Review Worktree 的 PR 已結束：
      1. 全部清除
      2. 選擇性刪除
      3. 跳過
    ```
    若有「狀態未知」的項目，另外列出並詢問使用者是否一併處理。

14. 對要清除的項目：
    - 優先使用 `git worktree remove --force {worktree路徑}` 移除。
    - 若上述指令失敗，顯示：
      ```
      即將刪除目錄：`{完整路徑}`
        1. 確認刪除
        2. 跳過此項
      ```
      選擇 `1` 後執行 `rm -rf {worktree路徑}`，再執行 `git worktree prune`。
    - 刪除對應的 `pr-review-{編號}` 本地分支

15. 顯示最終清理結果摘要。

### Phase 3：清理孤立 Worktree

16. 執行 `git worktree list --porcelain`，檢查輸出中是否有包含 `prunable` 屬性的 worktree：
    ```
    git worktree list --porcelain | grep -B2 "prunable"
    ```

17. 若有，列出 prunable worktree 的路徑並詢問使用者：
    ```
      1. 清理
      2. 跳過
    ```
    選擇 `1` 後執行：
    ```
    git worktree prune
    ```

18. 最後顯示完整清理報告：
    ```
    清理完成：
    - 已刪除 X 個本地分支
    - 已移除 Y 個 worktree
    - 已清理 Z 個 review worktree
    ```
