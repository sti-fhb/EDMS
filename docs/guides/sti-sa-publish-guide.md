# `/sti-sa-publish` 使用指南

## 使用時機

當你**已經在本機改好文件**（`docs/` 下的需求文件、使用案例、規格文件等），要將變更送上 GitHub 時使用。

指令會自動幫你完成：
1. 同步最新 main
2. 偵測你改了哪些檔案
3. 開一個新分支
4. Commit 你的變更
5. Push 到 GitHub
6. 開 Pull Request
7. 合併 PR 到 main（可選擇立即合併或留待審閱）
8. 合併後清除遠端與本地分支

> 只需要按幾次數字確認，不需要懂 git 指令。

---

## 使用流程示範

以下是一個完整的操作範例（SA 修改了採血模組的需求文件與使用案例）。

---

**在 Claude Code 輸入：**

```
/sti-sa-publish
```

---

**步驟 1：同步最新 main**

```
$ git fetch origin main
$ git pull --rebase origin main
✅ 已同步最新 main。
```

---

**步驟 2：偵測異動檔案**

```
📄 偵測到以下異動：
  修改：
    docs/_refs/01-採血模組.md
    docs/requirements/RQBC.md
  新增：
    docs/use-cases/bc/usecases.md
```

---

**步驟 3：建立分支**

```
建議分支名稱：docs/bc-rq-usecase-update

  1. 使用此名稱
  2. 自訂名稱
```

> 輸入 `1`，按 Enter

```
$ git checkout -b docs/bc-rq-usecase-update
✅ 已建立並切換至分支 `docs/bc-rq-usecase-update`。
```

---

**步驟 4：選擇要 commit 的檔案**

```
請選擇要包含在此次 commit 的檔案：

  修改：
    docs/_refs/01-採血模組.md
    docs/requirements/RQBC.md
  新增：
    docs/use-cases/bc/usecases.md

  1. 全部檔案
  2. 選擇部分檔案
```

> 輸入 `1`，按 Enter

```
$ git add docs/

已 staged 的檔案：
  modified:  docs/_refs/01-採血模組.md
  modified:  docs/requirements/RQBC.md
  new file:  docs/use-cases/bc/usecases.md
```

---

**步驟 5：撰寫 commit message**

```
建議 commit message：docs: 更新採血模組需求文件與使用案例

  1. 使用此訊息
  2. 自訂訊息
```

> 輸入 `1`，按 Enter

```
$ git commit -m "docs: 更新採血模組需求文件與使用案例"
✅ Commit 完成。
```

---

**步驟 6：Push 分支**

```
$ git push -u origin docs/bc-rq-usecase-update
✅ 已 push 至遠端分支 `docs/bc-rq-usecase-update`。
```

---

**步驟 7：建立 Pull Request**

```
PR 預覽：
  標題：docs: 更新採血模組需求文件與使用案例
  目標分支：main

  1. 確認建立 PR
  2. 修改標題
  3. 取消
```

> 輸入 `1`，按 Enter

```
✅ PR 已建立：#181 docs: 更新採血模組需求文件與使用案例
🔗 https://github.com/sti-fhb/TBMS/pull/181
```

---

**步驟 8：合併 PR 到 main**

```
是否立即合併此 PR？

  1. 是，立即合併
  2. 否，留待人工審閱後合併
```

> 輸入 `1`，按 Enter

```
$ gh pr merge 181 --merge --delete-branch
✅ PR 已合併至 main，遠端分支已刪除。

$ git checkout main && git pull origin main && git branch -d docs/bc-rq-usecase-update
✅ 本地已切回 main 並同步最新版本。
```

---

**步驟 9：完成摘要**

```
## 發布完成！

✅ 分支：docs/bc-rq-usecase-update
✅ Commit：docs: 更新採血模組需求文件與使用案例
✅ PR：#181 docs: 更新採血模組需求文件與使用案例
🔗 https://github.com/sti-fhb/TBMS/pull/181
✅ 已合併至 main

異動檔案：
  - docs/_refs/01-採血模組.md
  - docs/requirements/RQBC.md
  - docs/use-cases/bc/usecases.md
```

---

## 常見情況

| 情況 | 指令的處理方式 |
|------|---------------|
| 不確定要 commit 哪些檔案 | 選 `2`（部分檔案），逐一確認 |
| 想自訂分支名稱 | 步驟 3 選 `2`，輸入自訂名稱 |
| 想自訂 commit 說明 | 步驟 5 選 `2`，輸入說明文字 |
| 想讓別人審閱再合併 | 步驟 8 選 `2`，PR 保持開啟 |
| 合併時發生衝突 | 指令會暫停並提示通知負責人，不會強制覆蓋 |

---

## 注意事項

- 執行指令前，請先**確認文件已儲存**
- 必須在 **`main` 分支**上才能執行此指令（尚未開分支的狀態）
- 若有疑問，可在步驟 8 選擇 `2`（不立即合併），讓負責人確認後再合併
