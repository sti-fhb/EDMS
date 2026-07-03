檢查 Alembic revision 鏈的 head 狀態，並在發現多個 head 時提供 content 衝突分析與 merge 指引。

**使用時機**：
- `git pull origin main` 後
- 建立新 migration 前
- 開 PR 前
- PR review 時

---

## 執行步驟

### 步驟 1：解析 revision 圖

使用 **Bash 工具**執行以下固定 script：

```bash
cd backend && python3 - <<'PYEOF'
import os, re

d = 'alembic/versions'
migrations = {}

for f in sorted(os.listdir(d)):
    if not f.endswith('.py'):
        continue
    txt = open(f'{d}/{f}').read()
    m_rev = re.search(r'^revision(?::\s*str)?\s*=\s*["\']([^"\']+)["\']', txt, re.M)
    m_down = re.search(r'^down_revision(?::\s*[^=]+)?\s*=\s*(.+)', txt, re.M)
    if not m_rev:
        continue
    revision = m_rev.group(1)
    down_val = m_down.group(1).strip() if m_down else 'None'
    down_revisions = []
    if not down_val.startswith('None'):
        if down_val.startswith('('):
            down_revisions = re.findall(r'["\']([^"\']+)["\']', down_val)
        else:
            m = re.search(r'["\']([^"\']+)["\']', down_val)
            if m:
                down_revisions = [m.group(1)]
    m_doc = re.search(r'^"""(.+?)"""', txt, re.DOTALL | re.M)
    description, create_date = "", ""
    if m_doc:
        found_cd, blank_after = False, False
        for line in m_doc.group(1).strip().split("\n"):
            stripped = line.strip()
            if stripped.startswith("Create Date:"):
                m_date = re.search(r'(\d{4}-\d{2}-\d{2})', stripped)
                if m_date: create_date = m_date.group(1)
                found_cd, blank_after = True, False
                continue
            if found_cd:
                if not stripped: blank_after = True; continue
                if blank_after and not description: description = stripped; break
    migrations[revision] = dict(
        revision=revision, down_revisions=down_revisions,
        filename=f, description=description, create_date=create_date
    )

referenced = set()
for r in migrations.values():
    for dr in r["down_revisions"]:
        referenced.add(dr)
heads = [r for r in migrations if r not in referenced]

print(f'HEAD 數量：{len(heads)}')
for h in heads:
    m = migrations[h]
    desc = m["description"][:30] if m["description"] else "—"
    print(f'  {h[:8]}  {m["filename"]}  {desc}  {m["create_date"] or "—"}')

if len(heads) == 1:
    # 輸出最近 3 版供確認
    cur, count = heads[0], 0
    rows = []
    while cur and count < 3:
        m = migrations.get(cur)
        if not m: break
        pos = "HEAD" if count == 0 else "  ↑"
        rows.append(f'  {pos:<6} {cur[:8]}  {m["filename"][:45]}  {m["create_date"] or "—"}')
        if not m["down_revisions"]: break
        cur = m["down_revisions"][0]; count += 1
    print("\n最近 3 版：")
    for r in rows: print(r)
PYEOF
```

根據 script 輸出的 HEAD 數量，進入對應分支。

---

### 步驟 2：依 head 數量分支

---

#### 情況 A：單一 head ✅

顯示：
```
✅ Alembic 版本鏈健康（單一 head）

最近 3 版：
  HEAD   cfdaf208   dp03_rename_user_column.py    使用者欄位改名      2026-04-15
    ↑    b3018e58   dp03_add_user_phone.py         新增電話欄位        2026-04-14
    ↑    8f814945   dp_init_schedule.py            初始化排程          2026-04-12
```

結束。

---

#### 情況 B：多個 head ⚠️

##### 2a. 列出所有 head

```
⚠️  發現 {N} 個 head，需合併後才能繼續建立新 migration。

Head 清單：
  1.  {rev_id 前 8 碼}   {檔名}   {說明}   {日期}
  2.  {rev_id 前 8 碼}   {檔名}   {說明}   {日期}
  ...
```

##### 2b. Content 衝突分析

使用 **Read 工具**讀取每個 head 對應的 migration 檔案，擷取 `upgrade()` 函式內容。

掃描各 head 的 upgrade() 中出現的 table 名稱，識別方式：
- `op.add_column("TABLE_NAME", ...)`
- `op.drop_column("TABLE_NAME", ...)`
- `op.alter_column("TABLE_NAME", ...)`
- `op.create_table("TABLE_NAME", ...)`
- `op.drop_table("TABLE_NAME")`
- `op.create_index(..., "TABLE_NAME", ...)`
- `op.execute("... TABLE_NAME ...")` 中出現的大寫表名

找出被**兩個以上 head** 操作的 table，標示為 content 衝突。

顯示分析結果：

```
Content 衝突分析：
  ET_COURSE  ← head 1 和 head 2 都有操作  ⚠️  需人工確認執行順序
  ET_QUIZ    ← 僅 head 1 操作              ✅
  ET_ENROLL  ← 僅 head 2 操作              ✅
```

若無 content 衝突：

```
Content 衝突分析：無 table 被多個 head 同時操作 ✅
```

##### 2c. 提供 merge 指引

```
建議執行以下指令合併 heads：

  cd backend && alembic merge heads -m "merge_multiple_heads"

⚠️  注意：merge 只合併版本鏈結構，不解決 migration 內容衝突。
   若上方分析顯示有 content 衝突，merge 後需人工確認兩段 migration
   的執行順序不會互相破壞（例如：一個 add column、另一個 drop 同一欄位）。

  1. 執行 merge
  2. 稍後手動處理
```

##### 2d. 執行 merge（選擇 1）

```bash
cd backend && alembic merge heads -m "merge_multiple_heads"
```

執行後，顯示新建立的 merge migration 檔名，並提醒：

```
✅ Merge migration 已建立：{新檔名}

後續步驟：
  1. 確認新 migration 的 down_revision 包含所有原本的 head revision ID
  2. 若上方 content 分析有衝突，人工確認兩段 migration 的操作不互相破壞
  3. 執行 alembic upgrade head 驗證可正常 apply
```

##### 選擇 2：稍後手動處理

顯示指令供使用者自行執行後結束：

```
手動 merge 指令：
  cd backend && alembic merge heads -m "merge_multiple_heads"

merge 後記得確認新 migration 的 down_revision 正確包含所有 head。
```
