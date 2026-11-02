"""檔案儲存服務（T016）。

檔案存檔案系統 / 物件儲存，DB 僅存 metadata（FILE_*）。上傳前檢核大小（讀平台
`DP_PARAM.DM_FILE_MAX_MB`）與格式（`DM_FILE_TYPES`）。依 MIME 判定可預覽（PDF / 圖片）
或僅下載（Office）。研究 §3 / §10。

實際落盤 I/O（寫檔案系統 / 物件儲存）屬部署層，Foundation 提供可測核心：預覽判定 + 上傳檢核。

⚠️ 安全契約：
- 副檔名白名單檢核**非充分條件**——故 `resolve_upload_mime` 另以 magic bytes 驗證白名單內有固定檔頭之
  格式（PDF / 圖片 / Office）的真實型別、並以伺服端判定之權威 MIME 落地（防 evil.exe 改名 evil.pdf
  之內嵌 XSS，T066 M2；Office 類於 #211 L1 補上）。
- 上傳內容一律經 `read_upload` 讀入：讀取時即把關大小，不先整包載入記憶體再比對（#211 M1）。
- 檔名不得用於組路徑：一律以系統產生之 FILE_ID 命名，避免 `../` 路徑穿越。
- `DM_FILE_TYPES` 參數若被清空 / 停用，本函式**改用安全預設白名單 fail-closed**（不再跳過格式檢核），
  避免管理者誤清參數即開放任意副檔名（T066 L2）。
"""

import logging

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.services import ParamService

logger = logging.getLogger(__name__)

_MB = 1024 * 1024
_DEFAULT_MAX_MB = 50

# 可內嵌預覽之 MIME（其餘如 Office 僅提供下載）
_PREVIEWABLE_MIMES = frozenset({"application/pdf", "image/png", "image/jpeg", "image/jpg", "image/gif"})

# 安全預設副檔名白名單（fail-closed）：DM_FILE_TYPES 參數缺值時的後備，對齊種子預設值。
_DEFAULT_FILE_TYPES = frozenset({"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "jpg", "jpeg", "png"})


def is_previewable(mime: str) -> bool:
    """MIME 是否可內嵌預覽（PDF / 圖片）；Office 等回 False（僅下載）。"""
    return mime.lower() in _PREVIEWABLE_MIMES


# 副檔名 → 權威 MIME（**伺服端判定、完全不採用戶端 content_type**）。各項另需檔頭驗證，見 _EXT_MAGIC。
_EXT_TO_MIME = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

_ZIP_MAGIC = b"PK\x03\x04"
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # 舊版 Office 之 Compound File 容器

#: 副檔名 → 可接受的檔頭（任一相符即可）。涵蓋 `_EXT_TO_MIME` 全部項目（安全預設白名單）。
#:
#: - OOXML（docx / xlsx / pptx）另接受 OLE2：**加密**的 OOXML 是把 ZIP 包進 OLE2 容器
#:   （EncryptedPackage），設了開啟密碼的 Word / Excel 就是這種，只認 ZIP 會誤擋
#: - 舊版 Office（doc / xls / ppt）只認 OLE2。⚠️ 部分系統匯出的「xls」實為 HTML 表格、
#:   Word 另存的「doc」可能是 RTF——這類檔案會被擋，需請使用者另存為真正的 Office 格式
#:
#: ⚠️ 只驗**容器**檔頭：任何 ZIP（如 .docm / .jar）改名 .docx、任何 OLE2（如含巨集的 .doc）改名
#: 皆會通過——不檢查 `[Content_Types].xml`。可接受的理由：Office 類落地 MIME 非可預覽、一律以
#: attachment 下載，無內嵌渲染風險；本表要擋的是 `MZ` 執行檔等「換副檔名就能偽裝」的檔案（#211 L1）。
#:
#: ⚠️ **未列於此表的副檔名維持只驗副檔名**：管理者可經 `DM_FILE_TYPES` 加入 txt / csv 等
#: **無固定檔頭**的格式，無從比對。它們的落地 MIME 一律是 `application/octet-stream`
#: （非可預覽、僅下載），故不構成內嵌渲染風險。
_EXT_MAGIC: dict[str, tuple[bytes, ...]] = {
    "pdf": (b"%PDF-",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
    "doc": (_OLE2_MAGIC,),
    "xls": (_OLE2_MAGIC,),
    "ppt": (_OLE2_MAGIC,),
    "docx": (_ZIP_MAGIC, _OLE2_MAGIC),
    "xlsx": (_ZIP_MAGIC, _OLE2_MAGIC),
    "pptx": (_ZIP_MAGIC, _OLE2_MAGIC),
}


def resolve_upload_mime(file_bytes: bytes, filename: str) -> str:
    """**伺服端**由副檔名 + magic bytes 判定落地 MIME，**完全不採用戶端 content_type**（T066 M2）。

    不變量：**回傳之 MIME 為可預覽 ⟺ 已 magic-byte 驗證**（可預覽類副檔名皆列於 `_EXT_MAGIC`）。
    - 落地 MIME 一律取 `_EXT_TO_MIME[ext]`（白名單映射；未知副檔名 → `application/octet-stream`）——杜絕
      用戶端謊報 MIME（含謊報 `text/html` / `image/svg+xml` 等非可預覽但可渲染型別）寫入 DB。
    - 有固定檔頭的副檔名（`_EXT_MAGIC`）另要求檔頭相符，否則 `DM_FILE_005`（防 evil.exe 改名
      evil.pdf / evil.docx，#211 L1）。

    Raises:
        AppError: 檔案內容與副檔名不符（422 DM_FILE_005）。
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    magics = _EXT_MAGIC.get(ext)
    if magics is not None and not file_bytes.startswith(magics):
        # 只記副檔名：此時已通過白名單，值域受控；原始檔名為使用者輸入，不入 log
        logger.warning("DM 上傳檔頭與副檔名不符，已拒絕 ext=%s", ext)
        raise AppError(status_code=422, detail="檔案內容與副檔名不符", error_code="DM_FILE_005")
    return _EXT_TO_MIME.get(ext, "application/octet-stream")


async def resolve_upload_limits(db: AsyncSession, *, params: ParamService | None = None) -> tuple[int, frozenset[str]]:
    """目前生效的 `(單檔上限 MB, 允許副檔名集合)`。

    ## 🔴 這是**唯一**的解析處——驗證與「告訴使用者能傳什麼」都走它（#455）

    改版前上傳畫面的文案與 `accept` 是**寫死**的，於是 IT 依既定途徑改了 `DP_PARAM`
    之後，DP07 顯示新值、上傳畫面仍說舊話，而 `accept` 還會把新允許的格式擋在選檔器
    外——使用者看到的是「這個格式不能選」，**不會有任何錯誤訊息告訴他為什麼**。

    ⛔ **不要為前端另寫一支「取得限制」的函式。** 兩支各自解析參數、各自決定 fallback，
    遲早分岔——而分岔的表徵正是本 issue 要修的那個病：**選得到卻傳不上去**（或相反）。

    ⚠️ fail-closed 的語意必須保留：`DM_FILE_TYPES` 缺值 / 清空時退回**安全預設白名單**，
    而不是「全部放行」。管理者誤清參數不該等於開放任意副檔名（T066 L2）。
    """
    svc = params or ParamService()
    max_mb = await svc.get_int_param(db, "DM_FILE_MAX_MB", "VALUE", _DEFAULT_MAX_MB)
    allowed = await svc.get_param_value(db, "DM_FILE_TYPES", "VALUE")
    allowed_set = frozenset(t.strip().lower() for t in (allowed or "").split(",") if t.strip())
    return max_mb, (allowed_set or _DEFAULT_FILE_TYPES)


async def enforce_size_limit(db: AsyncSession, *, size_bytes: int, params: ParamService | None = None) -> None:
    """僅檢核大小不逾 `DM_FILE_MAX_MB`（讀入後之複檢；讀取時的把關見 `read_upload`）。

    Raises:
        AppError: 超過大小上限（422 DM_FILE_001）。
    """
    if size_bytes > await _max_upload_bytes(db, params or ParamService()):
        raise _too_large()


async def _max_upload_bytes(db: AsyncSession, svc: ParamService) -> int:
    return await svc.get_int_param(db, "DM_FILE_MAX_MB", "VALUE", _DEFAULT_MAX_MB) * _MB


def _too_large() -> AppError:
    # 每次現場建構，不共用模組級單例（理由見下方 `_NAME_TOO_LONG_MSG` 註解）
    return AppError(status_code=422, detail="檔案大小超過上限", error_code="DM_FILE_001")


async def read_upload(
    db: AsyncSession, file: UploadFile | None, *, params: ParamService | None = None
) -> tuple[str | None, bytes | None, str | None]:
    """讀取選填上傳檔 → `(檔名, bytes, 用戶端 content_type)`；未附檔（存草稿允許）回 `(None, None, None)`。

    US5 文件上傳與 US8 廢止附件共用（#211 M1）：大小在**讀進記憶體的過程中**就把關，而非讀完再比。
    - `UploadFile.size` 已知（Starlette 依實際寫入暫存檔的位元組數計得，客戶端無法謊報）→ 超限則一個位元組都不讀
    - 取不到時（縱深防禦；HTTP 路徑上 Starlette 一律提供）最多只讀 `上限 + 1` 位元組，多出那 1 個即判超限

    ⛔ 不要改回「分塊 append 再 `b"".join`」：chunks 與 join 結果會同時存在，峰值是上限的 **2 倍**
    （security review 以 tracemalloc 實測 50 MiB 檔 → 約 100 MiB），比改版前整包 `read()` 還糟。
    單次 `read(limit + 1)` 的峰值約為 1 倍上限。
    讀入後 service 仍以 `validate_upload` 複檢（大小 / 檔名 / 副檔名），本函式不取代它。

    ⚠️ 回傳之 content_type 是用戶端宣稱值，**不得**當落地 MIME——落地一律走 `resolve_upload_mime`。

    Raises:
        AppError: 超過大小上限（422 DM_FILE_001）。
    """
    if file is None:
        return None, None, None
    limit = await _max_upload_bytes(db, params or ParamService())
    if file.size is not None and file.size > limit:
        raise _too_large()
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise _too_large()
    return file.filename or "", data, file.content_type or "application/octet-stream"


#: 原始檔名之長度上限，對齊 `DM_DOC_VERSION.FILE_NAME` 與 `DM_REVIEW.OBSOLETE_FILE_NAME`
#: 的 `String(255)`（兩者同長，故一個常數涵蓋文件上傳與廢止附件兩條路徑；
#: `test_dm_input_limits_match_db.py` 守住「兩欄同長」這個前提）。
#:
#: 不設限時，超長檔名會在 INSERT 才撞 asyncpg 的 `StringDataRightTruncation`，而 `main.py`
#: 沒有 `DataError` 系列的處理器 ⇒ 落到最後的 catch-all、冒成 **500**（#697）。
MAX_FILE_NAME_LEN = 255

#: ## 為何是拒絕而非截斷
#:
#: 截斷會**默默改掉使用者的檔案名稱**，而下載時回給瀏覽器的正是這個名稱；兩支不同的長檔名
#: 截斷後還可能撞成同一個。明講「檔名過長，請縮短」是他當下就能處理的事。
#: 推導比照 `et/material/storage.ensure_file_name_acceptable`。
#:
#: ⛔ 只抄訊息、**不抄 ET 的模組級 `AppError` 單例寫法**：同一個 exception 物件被重複 `raise`
#: 時，Python 會把 `__traceback__` 掛在物件上並保留整條 frame 鏈（含各 frame 的 locals）。
#: DM 的上傳由 `read_upload` 整份讀進記憶體（只是讀取時即把關大小），被釘住的就是那份檔案位元組——一次被拒的
#: 超長檔名上傳會讓最多 `DM_FILE_MAX_MB` 常駐到下一次拒絕為止，且殘留的 traceback 一旦被
#: `logger.exception` 帶出來，印的是**別人那次請求**的堆疊。ET 那側是串流寫入、frame 裡只有
#: file handle，後果較輕，故該寫法在 DM 不成立。同檔 `DM_FILE_001` / `DM_FILE_002` 亦為現場建構。
_NAME_TOO_LONG_MSG = f"檔名過長（上限 {MAX_FILE_NAME_LEN} 字元），請縮短檔名後再上傳"


async def validate_upload(
    db: AsyncSession, *, size_bytes: int, filename: str, params: ParamService | None = None
) -> None:
    """上傳前檢核：大小不逾 `DM_FILE_MAX_MB`、檔名長度、副檔名屬 `DM_FILE_TYPES`。

    Raises:
        AppError: 超過大小上限（422 DM_FILE_001）、不支援格式（422 DM_FILE_002）、
            檔名過長（422 DM_FILE_003）。
    """
    svc = params or ParamService()
    await enforce_size_limit(db, size_bytes=size_bytes, params=svc)

    # 檔名長度先於副檔名檢核：兩者都不合時，「檔名過長」比「格式不支援」更接近使用者要做的事
    # （後者會讓他去找格式問題，而真正擋住的是長度）。
    if len(filename) > MAX_FILE_NAME_LEN:
        raise AppError(status_code=422, detail=_NAME_TOO_LONG_MSG, error_code="DM_FILE_003")

    # fail-closed：DM_FILE_TYPES 缺值 / 清空 → 退回安全預設白名單，格式檢核恆執行（T066 L2）
    #
    # ⚠️ 允許集合由 `resolve_upload_limits` 解析——**前端的 `accept` 走的是同一支**，
    # 兩邊因此不可能分岔（#455）。
    _, allowed_set = await resolve_upload_limits(db, params=svc)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in allowed_set:
        raise AppError(status_code=422, detail="不支援的檔案格式", error_code="DM_FILE_002")
