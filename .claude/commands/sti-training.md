執行以下步驟，為指定模組撰寫**教育訓練簡報**：先產 md 供確認，再產出 pptx。

## 參數說明（$ARGUMENTS）

| 參數 | 必選 | 說明 | 範例 |
|------|------|------|------|
| `<模組碼>` | 必填 | 模組代碼（`dm`、`et`、`dp`），不分大小寫 | `/sti-training dm` |
| `deck` | 選填 | md 已確認，只重產簡報 | `/sti-training dm deck` |
| `notes=none` | 選填 | 產出不帶備忘稿（另有 `brief`） | `/sti-training dm deck notes=none` |

---

## 執行步驟

### 步驟 0：載入規範（不可略過）

讀取 `docs/manuals/教育訓練教材規範.md`，後續一切依其規定辦理；**本指令不重述其內容，以免兩份漂移**。

帶 `deck` 參數時跳至步驟 7。

### 步驟 0.5：既有教材之處置

`docs/manuals/_training/{模組碼}-*.md` **已存在**時，⛔ MUST NOT 逕行覆寫——以 AskUserQuestion 問使用者要做什麼：

| 選項 | 動作 |
|---|---|
| 調整指定段落 | 請使用者指出要改哪裡，只動那幾段，⛔ 不重寫全檔 |
| 只重產簡報 | 跳至步驟 7 |
| 全部重寫 | 先告知現有檔案將被取代，確認後才回到步驟 1 |

檔案不存在時直接進步驟 1。

### 步驟 1：盤點該模組的作業

⛔ **一律查原始碼與檔案，不憑記憶、不抄他模組**：

| 要查的 | 查法 |
|---|---|
| 作業編號與**側欄顯示名稱** | `frontend/src/layouts/navItems.ts` 之 `NAV_GROUPS`（各項的 `code`／`label`）；無側欄入口的子頁見同檔 `SUBPAGE_SCREENS` |
| 側欄群組名稱 | 同上，該模組群組的 `title` |
| **手冊名稱** | `ls docs/manuals/{模組碼}/*.md` |
| 各作業的角色限制 | 前端：`navItems.ts` 各項的 `requires*` 旗標；後端：各模組的存取閘（DM 為 `backend/app/dm/roles/authz.py`、`gate.py`，ET 為 `backend/app/et/roles/`，DP 後台為 `require_any_module_admin`）與各 service 的角色判斷 |
| 業務規則、狀態、檢核 | `docs/specs/{模組碼}/spec.md`、`data-model.md`、`spec_us*.md` |
| **封面講師**（該模組負責人）| `git log --format='%an' -- docs/manuals/{模組碼}/ \| sort \| uniq -c \| sort -rn` 取主要提交者，對照 `manual_config.AUTHORS` |

**側欄名稱與手冊名稱不一致者 MUST 記下**，兩者都要寫進教材（規範第八節）。

⚠️ 畫面碼於 2026-09-30 重編過，舊 issue／PR 用的是舊號；一律以 `navItems.ts` 與各模組 `spec.md`〈畫面代號對照表〉的現行號為準。

### 步驟 2：判定模組型態

依規範第二節判定 A 流程型／B 功能型。**拿不準時用 AskUserQuestion 問使用者**，選項描述須含判準（「有一個主角從頭走到尾」vs「各作業彼此獨立」），⛔ 不自行認定。

### 步驟 3：擬大綱，與使用者確認後才動筆

產出大綱（章名＋各章張數＋時間分配），**貼在對話中**請使用者確認，⛔ 不寫成檔案中轉。

**課程總長度一併請使用者定奪**（規範開頭：長度依模組作業數而定），⛔ 不沿用他模組的時數。

- A 型：概述 → 主流程 → 各條岔路 → 設定與查詢 → 總結
- B 型：概述 → 各功能群（依使用頻率或畫面分組）→ 總結

章名用具體的名詞短語，⛔ 不用「分布」「意義」這類抽象詞。


### 步驟 4：寫 md

依規範第三～九節撰寫。每一段照「流程圖 → 實際操作 → 重點」三階段（規範第四節）。

⚠️ **先寫結構與投影片內容**——結構會反覆調整，先寫講稿會重做。

⚠️ **`> 講稿：` 為選配，預設不寫**——使用者要求時才補。
`> 提示：`（示範步驟、時間、待補事項、預期提問）**一律要寫**，那是講師自己看的。

### 步驟 5：內容自檢

逐項核對規範第十節的檢查清單（作業是否齊全、編號與名稱、段落指涉、數字一致、時間加總）。

⚠️ **版面溢出此時驗不到**——要等簡報產出後才有檔案可量，見步驟 7。

### 步驟 6：交付 md 供確認

告知使用者 md 位置與大綱摘要，**等待確認後才產簡報**。

### 步驟 7：產出簡報

⚠️ 產出前先確認 `docs/manuals/tools/manual_config.py` 的 `PROJECT_CASE_NO`、`VENDOR` 已填正式值——仍為「（待確認）」時，封面與每頁頁尾會印出佔位字樣。**停下來請使用者提供**，⛔ 不自行填入（本 repo 為 public，上傳前須經使用者同意）。

```bash
python docs/manuals/tools/gen_training_deck.py docs/manuals/_training/{檔名}.md [--notes brief|none]
```

缺 `python-pptx`／`lxml` 時先裝（`pip install python-pptx`），⛔ 不要求使用者自行處理。

⚠️ 本機 Git Bash 的 `python` 可能指向 `backend/.venv`（uv 建立、無 pip），`pip install` 則裝進系統 Python——裝完仍報 `No module named 'pptx'` 時，改用裝了套件的那支 Python 執行產生器。

產出後**必跑版面檢查**，有溢出先修 md 再重產，確認無溢出才回報張數與位置：

```python
from pptx import Presentation
from pptx.util import Emu
p = Presentation(r"docs/manuals/教育訓練/{檔名}.pptx")
for i, s in enumerate(p.slides, 1):
    mx = max((Emu(sh.top).cm + Emu(sh.height).cm
              for sh in s.shapes if Emu(sh.top).cm < 17.0), default=0)
    if mx > 17.4:
        print(f"第 {i} 頁內容到 {mx:.1f}cm，超出版面")
```

⚠️ 檔案被 PowerPoint 開啟時會寫入失敗（`PermissionError`），請使用者關閉後重試。

---

## 注意事項

- ⚠️ **本指令產出的是初稿，不是定稿**：內容自規格推導而來，**MUST 由該模組負責人對照實機校對**。
  下列三類只有該模組的人寫得出來，⛔ 不要自規格臆造：常見問題（要帶過課才知道學員卡在哪）、
  示範腳本的測試資料（哪個帳號、哪筆資料可現場演）、各作業的操作陷阱（規格不寫「這欄大家都填錯」）。
- **md 是唯一來源**：使用者要求調整時一律改 md 再重產，⛔ 不手改 pptx
- **調整先確認再動**：牽涉內容刪減時先說明取捨理由，取得同意再改
- **產生器可改**：版型不敷使用時可擴充 `gen_training_deck.py`，但新語法 MUST 同步寫入規範第九節
- 本流程同步自 TBMS（2026-10-01 新增）；查法與範例已改為 EDMS 適用，判準、版型與語法與 TBMS 一致
