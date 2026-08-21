"""ET → DM 文件取用（T029 / AC 10）——**已於 #183 交付後接上真實 Service**。

ET 教材引用 DM「訓練教材」分類之文件，經平台唯一跨模組出口 `app/services` 取得
`DmDocumentService`（DM #183 / PR #189 交付）：

| 方法 | 對應 | 用於 |
|------|------|------|
| `list_training_documents(db, category=..., keyword=..., func_code=...)` | SRVDM002 | ET02 教材下拉 |
| `get_current_by_doc_id(db, doc_id)` | SRVDM001 | ET02 發布檢核（`obsolete`）/ ET05 學員閱讀 |
| `read_file_for_reference(db, doc_id=..., version_id=...)` | 取檔 | ET05 學員取教材檔案 |

## 為何不自行定義型別與 Protocol

`DmDocumentService` 已是**具型別的門面**（`DmCurrentVersion` / `DmDocItem` /
`DmFileContent`），ET 若再包一層自己的 dataclass 只是重複維護、且兩邊欄位漂移時
無人察覺。本模組因此只保留 ET 端的**使用約束**與取得入口。

## 使用時的三項約束（DM 端已對應設計，勿繞過）

1. **授權由 ET 自判**——`read_file_for_reference` **刻意不掛 DM 角色閘**（ET 學員多半
   無 DM 角色，掛了會被 403 `DM_AUTH_001`）。因此 ET 呼叫前**必須自行確認**：該學員
   為此課程已加入且未移除之學員、且該章節已解鎖。
2. **`DmCurrentVersion` 不含 `file_path`**——這是 DM 刻意的設計，檔案一律經
   `read_file_for_reference` 取得。ET 不得繞過該方法自行組路徑（違反模組邊界，
   且 #160 之 storage-root 圍籬會失效）。
3. **取檔不計入 DM 閱讀統計**（DM 端 D-2）——ET 代學員取檔不寫 `DM_DOC_READ`，
   學習進度由 ET 自行統計（`ET_PROGRESS` / `ET_PROGRESS_VIDEO`）。

## 例外語意（與 stub 時期不同）

DM 端以 `AppError` 表達失敗，**非回 None**：

- 查無文件 / 非可引用分類 → **404**（刻意不洩漏該文件是否存在）
- 文件存在但尚無發布版 → **409 `DM_DOC_013`**
- 取非當前版之檔案 → **403 `DM_DOC_002`**
- 分類不在白名單 → **422 `DM_DOC_010`**

呼叫端須據此處理，不可再假設「回 None 代表查無」。
"""

from app.services import DmDocumentService

# ET 教材固定引用之 DM 分類碼（非 `TRAINING_MATERIAL`——2026-08-19 依 DM 定稿契約更正）。
# DM 端 `list_training_documents` 預設值亦為此，且僅白名單分類可跨模組引用。
TRAINING_CATEGORY = "TRAINING"


def get_dm_document_client() -> DmDocumentService:
    """取得 DM 文件取用 Service（經 `app/services` 唯一跨模組出口）。

    保留本工廠而非讓呼叫端直接 `DmDocumentService()`：使「ET 如何取得 DM 文件」有單一
    切入點，日後若需加入快取、重試或替換實作時不必改動各呼叫處。
    """
    return DmDocumentService()
