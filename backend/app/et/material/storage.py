"""教材影片之落盤與 storage-root 圍籬（#203 / #188 前瞻風險 B2）。

leaf 模組——只依賴 `os` / `logging` / `settings` / `AppError`，不引入 `app.services`，
比照 DM 之 `app/dm/document/file_paths.py`（#160）避免循環 import。

## 串流寫檔，不可照抄 DM

DM 之上傳把整份檔案讀進記憶體（`data: bytes`）。ET 影片單檔上限 **500 MB**，照做
會爆記憶體——數個教師同時上傳就足以把行程打掛。本模組以分塊讀寫，記憶體佔用固定
在一個 chunk。

## 大小檢核必須在串流過程中做

不能只信 `UploadFile.size` 或 `Content-Length`：兩者都由用戶端提供，可以說謊。
唯一可靠的是**邊寫邊數**，超過上限就中止並刪除半成品。

## storage-root 圍籬

`FILE_PATH` 落地與讀取共用同一根目錄與同一套圍籬邏輯，避免寫入端與讀取端 drift。
讀取端的 `os.path.realpath` 須落在 `ET_VIDEO_STORAGE_ROOT` 內——即使 DB 中的路徑
因任何瑕疵含 `../` 或絕對路徑逃逸，串流端也不會外洩根目錄外的檔案。讀取者可能是
**無任何 DM / 管理權限的學員**。
"""

import errno
import logging
import os
import shutil
import stat
import uuid

from app.core.config import settings
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

#: 串流讀寫之分塊大小（1 MB）。太小會增加 syscall 次數，太大則失去串流的意義。
CHUNK_SIZE = 1024 * 1024

#: 原始檔名之長度上限，對齊 `ET_MATERIAL_VIDEO.FILE_NAME` 的 `VARCHAR(200)`。
#: 不設限時超長檔名會在 INSERT 時撞 asyncpg 的 StringDataRightTruncation，
#: 冒成未處理的 500——與 #202 修過的三個「越界回 500」屬同一類。
MAX_FILE_NAME_LEN = 200

#: 暫存子目錄。放在 storage root **之內**——跨檔案系統的 rename 不是原子操作，
#: 放在系統暫存區再搬進來會退化成複製，500 MB 的檔案等於多讀寫一次。
TMP_DIRNAME = ".tmp"

#: 目錄名之位數上限：`MATERIAL_ID` / `STAGE_ID` 皆為 BigInteger，最大 19 位。
MAX_ID_DIGITS = 19

#: 暫存模式新增之教材的目錄前綴（#871）：`s{stage_id}/`。
#:
#: `STAGE_ID` 與 `MATERIAL_ID` 是兩個獨立序列、共用同一個數字命名空間——原本暫存 7 與正式教材 7
#: 落在同一個 `7/`，歸屬圍籬因此無從判定。加前綴後數字目錄只屬於正式教材，暫存目錄的影片於
#: 按「更新」時由 `link_into_material` 掛回 `{MATERIAL_ID}/`。
STAGED_DIR_PREFIX = "s"

#: 歸屬圍籬強制生效之標記檔（#871），由遷移腳本（`relocate_videos`）確認全部影片皆已落在
#: `{MATERIAL_ID}/` 之後寫入。
#:
#: 放在影片目錄而非設定檔：「資料已遷移」是**資料**的狀態——DB 與影片目錄一起還原到遷移前的
#: 備份時，標記檔跟著消失、圍籬自動退回放行模式，不會把舊資料整批擋成 404。
OWNERSHIP_FENCE_MARKER = ".ownership-fence-enforced"

#: Windows 沒有 `O_NOFOLLOW`；該平台的檔名層級連結需管理者權限才建得出來，退化為 0。
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)

#: `_link_entry` 只在 Windows 允許改走較弱路徑（#937）。其他平台判定為不支援時一律拒絕：
#: 能力偵測比的是函式物件本身，`os.link` 被任何工具包一層就會「看起來不支援」，不能因此靜默降級。
_WEAK_LINK_ALLOWED = os.name == "nt"

_TOO_LARGE_OR_BAD_FORMAT = AppError(
    status_code=422,
    detail="影片格式或大小不符",
    error_code="ET_MATERIAL_003",
)

_NAME_TOO_LONG = AppError(
    status_code=422,
    detail=f"影片檔名過長（上限 {MAX_FILE_NAME_LEN} 字元），請縮短檔名後再上傳",
    error_code="ET_MATERIAL_006",
)


_BAD_STORAGE_PATH = AppError(
    status_code=422,
    detail="影片儲存位置不合法",
    error_code="ET_MATERIAL_007",
)


def ensure_file_name_acceptable(file_name: str) -> None:
    """檔名長度須在 `ET_MATERIAL_VIDEO.FILE_NAME` 容得下的範圍內。

    ## 為何是拒絕而非截斷

    截斷會**默默改掉使用者的檔案名稱**，而該名稱正是「同名影片」判定的依據——
    兩支不同的長檔名截斷後可能撞在一起，變成一個使用者無法理解的「重複」錯誤。
    明講「檔名過長，請縮短」則是他當下就能處理的事。

    ## 為何不靠 DB 的長度限制擋

    靠 DB 擋的結果是 `StringDataRightTruncation` 冒成 500——使用者只會看到「伺服器
    處理失敗」。這與 #202 修過的三個「越界回 500 而非 4xx」是同一類問題。

    Raises:
        AppError: 422 `ET_MATERIAL_006`。
    """
    if len(file_name) > MAX_FILE_NAME_LEN:
        raise _NAME_TOO_LONG


def storage_root() -> str:
    """影片儲存根目錄之正規化絕對路徑（單一事實來源：`settings.ET_VIDEO_STORAGE_ROOT`）。

    空設定值 fail-closed（#240 A4）：`os.path.realpath("")` 回 CWD，圍籬範圍會變成整個後端
    原始碼目錄，孤兒清理（#775）更會把原始碼當成孤兒檔刪掉。production 由 config 護欄於啟動
    即擋，dev（DEBUG=true）則靠此處。
    """
    value = settings.ET_VIDEO_STORAGE_ROOT
    if not value or not value.strip():
        raise RuntimeError("ET_VIDEO_STORAGE_ROOT 未設定，拒絕以工作目錄作為影片儲存根目錄")
    return os.path.realpath(value)


def video_dir_name(material_id: int) -> str:
    """影片落盤目錄名：正式教材為 `{material_id}`，暫存新增的教材（負數 id ＝ `-STAGE_ID`）為 `s{stage_id}`。"""
    return str(material_id) if material_id >= 0 else f"{STAGED_DIR_PREFIX}{-material_id}"


def _resolved_within_root(path: str, root: str | None = None) -> str | None:
    """path 以 root 為基準正規化（解析 `..` / symlink）後若落在 root 內回其絕對路徑，否則 `None`。

    `path` 為**相對於 `ET_VIDEO_STORAGE_ROOT` 的片段**（`ET_MATERIAL_VIDEO.FILE_PATH` 之
    儲存格式，#233）；傳入絕對路徑亦受支援——`os.path.join` 遇絕對第二引數會丟棄 root 直接
    回該路徑，故既有絕對路徑資料只要仍落在當前 root 內即照常解析（免 big-bang 轉換）。

    ⚠️ 上述 join 行為使絕對路徑得以繞過 root 前綴，**其後的 commonpath 檢查是唯一防線**——
    移除它等同解除圍籬。讀取者可能是無任何 DM / 管理權限的學員，重構時不得省略。

    fail-closed：`None` / 空字串 / 非字串、跨磁碟（Windows 上 `commonpath` 會拋
    `ValueError`）、逃出根目錄一律回 `None`。

    **單次 realpath**——回傳值即「被驗證且將被讀取」的同一路徑。若驗證與實際讀取各自
    解析一次，兩次之間 symlink 被換掉就形成 TOCTOU 缺口。
    """
    if not isinstance(path, str) or not path:
        return None
    root = storage_root() if root is None else root
    try:
        resolved = os.path.realpath(os.path.join(root, path))
        return resolved if os.path.commonpath([root, resolved]) == root else None
    except (ValueError, TypeError):
        return None


def _belongs_to(resolved: str, prefix: str, root: str) -> bool:
    """已通過 root 圍籬之 `resolved` 是否位於 `{root}/{prefix}/` 之下（不含該目錄本身）。

    以**解析後**路徑相對於 root 的第一段比對，而非比對原始字串——`..` 繞道、symlink 指向他份
    教材、既有絕對路徑資料因此一併被涵蓋。比照 DM 之 `file_paths._belongs_to`（#240 A1）。
    """
    parts = os.path.relpath(resolved, root).split(os.sep)
    return len(parts) >= 2 and parts[0] == prefix


def locate_in_root(file_path: str, root: str) -> str | None:
    """以讀取端同一套 root 圍籬解析 `file_path`；逃出 root 回 `None`（供遷移腳本判定，免與播放端 drift）。"""
    return _resolved_within_root(file_path, root)


def belongs_to_material(resolved: str, material_id: int, root: str) -> bool:
    """已解析之路徑是否落在 `{root}/{material_id}/` 之下（與播放端 `expect_prefix` 同一套判定）。"""
    return _belongs_to(resolved, str(material_id), root)


def ownership_fence_enforced(root: str) -> bool:
    """歸屬圍籬是否已強制生效（`OWNERSHIP_FENCE_MARKER` 為一般檔；目錄或連結不算）。"""
    try:
        return stat.S_ISREG(os.lstat(os.path.join(root, OWNERSHIP_FENCE_MARKER)).st_mode)
    except OSError:
        return False


def mark_ownership_fence_enforced(root: str) -> None:
    """寫入標記檔，使歸屬圍籬強制生效（僅供遷移腳本於確認無待遷移影片後呼叫）。

    `O_NOFOLLOW`：該位置若事先被放了連結，寫入不落到它指向的檔（呼叫端寫完應以
    `ownership_fence_enforced` 回讀確認）。
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _O_NOFOLLOW
    fd = os.open(os.path.join(root, OWNERSHIP_FENCE_MARKER), flags, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("#871：本目錄的影片皆已落在 {MATERIAL_ID}/ 之下，播放端強制驗證檔案歸屬。\n")


def clear_ownership_fence_marker(root: str) -> None:
    """移除標記檔，使歸屬圍籬退回放行模式（遷移腳本 `--revert` 用）。不存在時不報錯。"""
    try:
        os.remove(os.path.join(root, OWNERSHIP_FENCE_MARKER))
    except FileNotFoundError:
        pass


def resolve_within_root(file_path: str, *, not_found: AppError, expect_prefix: str | None = None) -> str:
    """讀取端圍籬：回正規化後之安全路徑；逃逸出根目錄則 raise 呼叫端提供之 `not_found`。

    錯誤文案由呼叫端自帶，避免與該端點其他 404 措辭不一致。逃逸時記安全事件但
    **不記落盤路徑**（遵 `sti-backend-logging`）。

    ⚠️ **播放端點落地時必須比照 DM，先做 `Path(resolved).is_file()` 再開檔**（見
    `app/dm/detail/router.py`）。Windows 的 `os.path.realpath` 不拒絕內嵌 NUL 字元
    （CPython gh-106242），帶 NUL 的路徑會通過本圍籬；`pathlib` 的 `is_file()` 內部
    `except ValueError: return False`，能把它收斂成統一 404，但若直接 `open(resolved)`
    則會拋 `ValueError` 冒成 500。POSIX 端 `realpath` 本身就會拋、由此處 fail-closed
    接住，兩平台行為因而一致。此為 #233 security review INFO-6。

    ## `expect_prefix`：檔案歸屬（#871，比照 DM #240 A1）

    傳入時另驗檔案落在 `{root}/{expect_prefix}/` 之下。播放票以 `video_id` 授權，檔案邊界須對齊
    同一支影片所屬的 `MATERIAL_ID`——否則一筆寫錯的 `FILE_PATH` 就能讓學員讀到他份教材的影片。
    此為 root 圍籬之**額外**一層，root 圍籬一律先跑、不可被取代；兩層共用同一次取得的 root。

    ⚠️ **遷移完成前只記 log、照常放行**：#871 之前暫存上傳的影片落在 `abs(暫存 id)/`，與所屬
    `MATERIAL_ID` 不同。維運跑完遷移腳本（`python -m app.et.material.relocate_videos --apply`）、
    寫入 `OWNERSHIP_FENCE_MARKER` 之後才強制——合併當下若直接擋，既有影片會整批播不出來。
    """
    root = storage_root()
    resolved = _resolved_within_root(file_path, root)
    if resolved is None:
        logger.warning("ET 影片 storage-root 圍籬攔截一筆逃逸 / 無效之 FILE_PATH（不記路徑）")
        raise not_found
    if expect_prefix is not None and not _belongs_to(resolved, expect_prefix, root):
        if ownership_fence_enforced(root):
            logger.warning("ET 影片檔案歸屬圍籬攔截一筆不屬於本教材之 FILE_PATH（不記路徑）")
            raise not_found
        _warn_unmigrated_once(resolved)
    return resolved


#: 放行模式下已記過 warning 的路徑（L6：播放器的 Range 請求會讓同一支影片打很多次，每次都記會洗版）。
#: 只在本行程內去重、有上限——它只是降噪，不是狀態。
_WARNED_UNMIGRATED: set[str] = set()
_WARNED_UNMIGRATED_MAX = 10_000


def _warn_unmigrated_once(resolved: str) -> None:
    if resolved in _WARNED_UNMIGRATED:
        return
    if len(_WARNED_UNMIGRATED) >= _WARNED_UNMIGRATED_MAX:
        _WARNED_UNMIGRATED.clear()
    _WARNED_UNMIGRATED.add(resolved)
    logger.warning("ET 影片檔不在所屬教材目錄、影片目錄遷移尚未執行，暫予放行（不記路徑）")


def ensure_format_allowed(file_name: str, allowed_formats: list[str]) -> str:
    """檢核副檔名在允許清單內，回**正規化後的小寫副檔名**（不含點）。

    以副檔名而非 MIME 判定：`Content-Type` 由用戶端提供、可任意偽造，而副檔名至少
    決定了檔案落地後的樣子。真正的內容驗證由 `ffprobe` 承擔——它讀不出長度的檔案
    一律拒收，等於間接要求「這真的是一支影片」。

    Args:
        file_name: 上傳之原始檔名。
        allowed_formats: 來自 `DP_PARAM.ET_VIDEO_ALLOWED_FORMATS`（如 `["mp4", "webm"]`）。

    Raises:
        AppError: 422 `ET_MATERIAL_003`。
    """
    ext = os.path.splitext(file_name)[1].lstrip(".").lower()
    if not ext or ext not in {fmt.strip().lower() for fmt in allowed_formats}:
        raise _TOO_LARGE_OR_BAD_FORMAT
    return ext


async def save_video_stream(upload, *, ext: str, max_size_bytes: int) -> tuple[str, int]:
    """分塊串流寫入**暫存檔**，回 `(暫存檔絕對路徑, 位元組數)`。

    寫的是暫存檔而非正式路徑：長度還沒驗（`ffprobe` 需要檔案存在才能探測），此時
    若直接落在正式路徑，一支長度解析失敗的影片就會留在正式區。

    Args:
        upload: FastAPI 之 `UploadFile`。
        ext: 已檢核之副檔名（不含點）。
        max_size_bytes: 單檔上限。

    Returns:
        `(暫存檔路徑, 實際寫入位元組數)`。

    Raises:
        AppError: 422 `ET_MATERIAL_003`——實際寫入量超過上限。半成品會被刪除。
    """
    tmp_dir = os.path.join(storage_root(), TMP_DIRNAME)
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}.{ext}")

    written = 0
    try:
        with open(tmp_path, "wb") as sink:
            while chunk := await upload.read(CHUNK_SIZE):
                written += len(chunk)
                # 邊寫邊數：`Content-Length` 由用戶端提供、可以說謊，唯一可信的是實際位元組數。
                if written > max_size_bytes:
                    raise _TOO_LARGE_OR_BAD_FORMAT
                sink.write(chunk)
    except BaseException:
        discard(tmp_path)
        raise
    return tmp_path, written


def _is_canonical_id(value: str) -> bool:
    """value 是否為 BigInteger id 的正規字串形式（純 ASCII 數字、無前導零、至多 19 位），即 `str(abs(id))`。

    位數上限不可省：超長數字字串在 `int()` 撞上位數上限拋 `ValueError`、在 `makedirs` 撞上檔名長度
    上限拋 `OSError`，兩者都會冒成 500。比對亦不經 `int()` 轉換，同一理由。
    """
    return value.isascii() and value.isdigit() and len(value) <= MAX_ID_DIGITS and (value == "0" or value[0] != "0")


def _is_video_dir_name(value: str) -> bool:
    """value 是否為 `video_dir_name` 的產出：`{id}` 或 `s{id}`（id 皆為正規形式）。"""
    if value.startswith(STAGED_DIR_PREFIX):
        value = value[len(STAGED_DIR_PREFIX) :]
        return value != "0" and _is_canonical_id(value)
    return _is_canonical_id(value)


def _is_staged_upload(root: str, path: str) -> bool:
    """path 是否為 `{root}/.tmp/` 下的一般檔（非 symlink、非目錄）——`promote` 唯一合法的來源。"""
    target = _entry_within(root, path) if isinstance(path, str) and os.path.isabs(path) else None
    if target is None or os.path.dirname(target) != os.path.join(root, TMP_DIRNAME):
        return False
    try:
        return stat.S_ISREG(os.lstat(target).st_mode)
    except (OSError, ValueError):
        return False


def promote(tmp_path: str, *, video_id_hint: str, ext: str) -> tuple[str, str]:
    r"""把暫存檔搬到正式路徑，回 `(絕對路徑, 相對於 root 之片段)`。

    同一檔案系統內的 `os.replace` 是原子操作——不會出現「搬一半」的檔案。

    ## 為何回兩個值（#233）

    兩者用途不同且**不可互換**：

    | 用途 | 要哪一個 | 拿錯的後果 |
    |------|---------|-----------|
    | 寫入 `ET_MATERIAL_VIDEO.FILE_PATH` | 相對片段 | 存絕對路徑 → 換 root / 清 worktree 即永久失聯 |
    | 失敗時 `discard()` 回滾刪檔 | 絕對路徑 | 傳相對片段 → `discard` 拒收（非絕對路徑，#240 A3），
    | | | 只留 warning，**靜默留下孤兒檔** |

    不讓 `discard` 自行 join root 的理由：它同時被 `save_video_stream` 以 `.tmp/` 下的
    **暫存絕對路徑**呼叫，改成吃相對片段會讓它變成「有時絕對、有時相對」的雙語意函式。

    相對片段之分隔符固定 `/`（不用 `os.path.join`：Windows 會產出 `\`，該值搬到 POSIX
    即讀不到，因為 `\` 在 POSIX 是合法檔名字元而非分隔符）。

    ## 為何在寫 DB 之前搬

    兩種失敗的後果不對稱：

    | 情形 | 後果 |
    |------|------|
    | 有檔案、沒 DB 紀錄 | 孤兒檔案，佔磁碟但無人可及——**無害** |
    | 有 DB 紀錄、沒檔案 | 學員點下去拿到 404，**影片是壞的** |

    故先落檔再寫紀錄，把風險留給無害的那一邊。外層交易若在 router 回傳後才
    rollback（`get_db` 於此時 commit），結果就是一個孤兒檔案——不阻塞任何人，
    亦可日後以清理作業回收。

    ## 寫入端圍籬（#240 A3）

    - **來源**須是 `{root}/.tmp/` 下的一般檔（非 symlink）——即 `save_video_stream` 的產出。只圈到
      root 不夠：root 內另一支被引用中的影片同樣在 root 內，搬走它即讓原教材失聯。
    - **目的地**目錄名須為 `video_dir_name` 的產出（`{id}` / `s{id}`，id 純數字、無前導零）——`..`
      即寫入端穿越，空字串 / `.tmp` 則會落在 root 頂層或暫存區，`007` 會與 `7/` 分成兩個目錄。

    攔截時暫存檔原地不動（由孤兒清理回收），不在此處刪——來源既已不可信，就不該拿它去 `os.remove`。

    ⚠️ 已知限制：來源檢查與 `os.replace` 之間有 TOCTOU 空窗（期間 `.tmp/` 內的檔可被換成 symlink）。
    `.tmp/` 為伺服器自建、外部無寫入途徑，在此威脅模型下接受；若日後 `.tmp/` 可被他方寫入須改以
    fd 為基準搬移。

    Raises:
        AppError: 422 `ET_MATERIAL_007`——來源或目的地不合上述條件。
    """
    root = storage_root()
    if not (_is_staged_upload(root, tmp_path) and _is_video_dir_name(video_id_hint)):
        logger.warning("ET 影片落盤圍籬攔截一筆非暫存區來源 / 不合法目錄名（不記路徑）")
        raise _BAD_STORAGE_PATH
    final_dir = _ensure_real_dir(root, video_id_hint, on_error=_BAD_STORAGE_PATH)
    final_path = os.path.join(final_dir, f"{uuid.uuid4().hex}.{ext}")
    os.replace(tmp_path, final_path)
    # 相對片段由實際落地的絕對路徑反推，而非另行組字串——避免「落地的」與「入 DB 的」
    # 是兩個各自組出來的東西，日後任一端重構即可能靜默產生落差
    return final_path, os.path.relpath(final_path, root).replace(os.sep, "/")


#: `os.link` 回這些 errno 代表「檔案系統不支援 hard link」，才退回複製。
_LINK_UNSUPPORTED = frozenset(
    code
    for code in (
        errno.EXDEV,
        errno.EPERM,
        errno.EMLINK,
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
    )
    if code is not None
)


def _ensure_real_dir(root: str, rel_dir: str, *, on_error: Exception | None = None) -> str:
    """建立 `{root}/{rel_dir}` 並確認它是實體目錄（不是指向他處的連結），回其絕對路徑。

    `os.makedirs(exist_ok=True)` 遇到既有的目錄連結會照樣放行，之後寫進去的檔就落在 root 外。

    預設拋 `NotADirectoryError`（`OSError`）而非 `ValueError`：這是影片目錄的**部署 / 檔案系統異常**，
    不是「來源不合格」。`stage_apply._adopt_video_file` 依此分流——前者在圍籬生效後須整批回滾，
    後者保留原路徑即可。
    """
    target = os.path.join(root, rel_dir)
    os.makedirs(target, exist_ok=True)
    if os.path.realpath(target) != os.path.normpath(target):
        logger.warning("ET 影片目錄圍籬攔截一個非實體目錄（不記路徑）")
        raise on_error if on_error is not None else NotADirectoryError("目標目錄不是 storage root 下的實體目錄")
    return target


def _regular_entry(root: str, path: str) -> str:
    """`path` 在 root 內的實際位置，且須為一般檔（檔名本身不解析、以 lstat 判定）。

    檔名若是連結，解析後是它指向的目標——掛過去等於把別支影片（或 root 外的檔）複製給這份教材。

    Raises:
        ValueError: 逃出 root 或不是一般檔。
        FileNotFoundError: 不存在。
    """
    entry = _entry_within(root, path)
    if entry is None or not stat.S_ISREG(os.lstat(entry).st_mode):
        raise ValueError("影片路徑不是 storage root 內的一般檔")
    return entry


def _link_entry(root: str, source: str, target: str) -> None:
    """以 hard link 從 source 建出 target（不支援時複製）；target 已是同一支檔則不動。

    ⚠️ **先刷新 mtime 再掛**：孤兒清理以 mtime 判寬限期，hard link 共用 inode、mtime 是當初上傳的
    時間；不刷新的話，剛掛上、交易還沒 commit 的新名字可能被當成舊孤兒刪掉。刷新放在 link 之前
    （刷的是同一個 inode），新名字出現的那一刻 mtime 就已是新的，不留空窗。

    Linux 上 link / utime 一律不跟隨連結：`_regular_entry` 檢查之後 source 若被換成連結，掛上的是連結
    本身，之後的讀取端圍籬會以解析後位置判定，不會把連結指向的檔當成本教材的。

    ## 平台差異（#937）

    - **Linux（正式環境、GitHub CI）**：`utime` / `link` 帶 `follow_symlinks=False`，強度同上、無空窗。
    - **Windows（開發機）**：先 `lstat` 確認 source 不是連結、是就拒絕，再一般呼叫。**強度較弱**：
      `lstat` 與 `utime` / `link` 之間有 TOCTOU 空窗，期間 source 若被換成連結即被跟隨。

    Windows 不支援這兩個呼叫的 `follow_symlinks`（呼叫即拋 `NotImplementedError`，按「更新」會 500）。
    空窗要被利用，須在影片目錄建立符號連結，而 Windows 建立符號連結需管理者權限或開發人員模式——
    在開發機上不構成實際威脅；正式環境不跑在 Windows 上。比照本檔 `_O_NOFOLLOW` 在 Windows 退化為 0 的處理。
    能力偵測決定「能不能走強路徑」，平台名稱只決定「可以接受降級」的範圍（`_WEAK_LINK_ALLOWED`）：
    非 Windows 平台判定為不支援時直接拋錯，不靜默改走較弱路徑。

    Raises:
        ValueError: Windows 路徑上 source 是連結。
        RuntimeError: 非 Windows 平台不支援 `follow_symlinks`——部署異常，刻意不讓呼叫端吞掉。
    """
    if os.utime in os.supports_follow_symlinks and os.link in os.supports_follow_symlinks:
        no_follow: dict[str, bool] = {"follow_symlinks": False}
    elif not _WEAK_LINK_ALLOWED:
        raise RuntimeError("此平台的 os.utime / os.link 不支援 follow_symlinks，拒絕以較弱方式掛檔")
    else:
        if stat.S_ISLNK(os.lstat(source).st_mode):
            raise ValueError("影片來源是連結")
        no_follow = {}
    os.utime(source, **no_follow)
    try:
        os.link(source, target, **no_follow)
    except FileExistsError:
        if not os.path.samefile(source, target):
            raise
    except OSError as exc:
        if exc.errno not in _LINK_UNSUPPORTED:
            raise
        logger.warning("ET 影片目錄所在檔案系統不支援 hard link，改以複製（%s）", type(exc).__name__)
        _copy_atomically(root, source, target)  # 複製出的新檔 mtime 本來就是新的


def link_into_material(file_path: str, material_id: int, *, allowed_source_dirs: frozenset[str] | None = None) -> str:
    """把影片掛進 `{root}/{material_id}/`（檔名不變），回新的相對片段（#871）。

    已在該目錄下者原樣回傳 `file_path`。供兩處使用：按「更新」把暫存目錄（`s{stage_id}/`）的影片
    掛回正式目錄（`stage_apply`），以及一次性遷移既有資料（`relocate_videos`）。

    ## 為何是 hard link 而非搬移

    呼叫端都是「先動檔案、再改 DB」，而 DB 那一步可能回滾：

    | 做法 | DB 回滾後 |
    |------|----------|
    | `os.replace` 搬走 | 暫存列 / 舊列仍指向原路徑，**檔案已不在**——影片壞掉 |
    | hard link | 原路徑照常有效；多出的新名字沒有列指向，由孤兒清理（#775）回收 |

    成功時則反過來：原路徑變成沒有列指向的名字，同樣由孤兒清理回收（刪的只是一個名字，
    內容仍由新路徑持有）。

    檔案系統不支援 hard link（`_LINK_UNSUPPORTED`）時退回複製（先寫 `.tmp/` 再 `os.replace`，不會
    留下半份檔）並記 warning——複製一支 500 MB 的影片要數十秒，影片目錄應放在支援 hard link 的檔案
    系統上。其餘錯誤（權限等）直接拋出，不先白複製一份才失敗。⚠️ 本函式是同步 I/O，在請求中呼叫時
    須丟到執行緒（`stage_apply._adopt_video_file`），否則複製退路會凍結 event loop。

    ## `allowed_source_dirs`：只掛本教材自己的暫存目錄

    掛進正式目錄等於宣告「這支檔屬於這份教材」，之後播放端的歸屬圍籬就會放行它。若不限來源，
    一筆指向他份教材檔案的 `FILE_PATH` 在下一次「更新」時就會被掛過來、從此合法——圍籬要擋的
    正是這種列。`stage_apply` 一律傳入該教材暫存節點的目錄（`s{stage_id}` 與 #871 前的
    `{stage_id}`）；遷移腳本不傳，改以「同一支檔被不同教材引用」另行偵測。

    Raises:
        ValueError: 來源逃出 root、不是一般檔，或不在 `allowed_source_dirs`。
        NotADirectoryError: 目標目錄不是實體目錄（影片目錄的部署異常，見 `_ensure_real_dir`）。
        FileNotFoundError: 來源不存在。
        FileExistsError: 目標位置已有**另一支**同名檔。
        OSError: 其他檔案系統錯誤。
    """
    root = storage_root()
    prefix = str(material_id)
    if not _is_canonical_id(prefix):
        raise ValueError("material_id 不是正式教材 id")
    resolved = _resolved_within_root(file_path, root)
    if resolved is None:
        raise ValueError("影片路徑逃出 storage root")
    if _belongs_to(resolved, prefix, root):
        return file_path
    source = _regular_entry(root, file_path)
    if allowed_source_dirs is not None and os.path.relpath(source, root).split(os.sep)[0] not in allowed_source_dirs:
        raise ValueError("影片不在本教材的暫存目錄")

    target = os.path.join(_ensure_real_dir(root, prefix), os.path.basename(source))
    _link_entry(root, source, target)
    return os.path.relpath(target, root).replace(os.sep, "/")


def link_back(new_path: str, old_path: str) -> None:
    """遷移回復用：old 不存在時從 new 掛回去（#871 `relocate_videos --revert`）。

    兩端都經 root 圍籬、來源須為一般檔、目標目錄須為實體目錄——輸入來自搬移紀錄檔，而那個檔
    放在影片目錄、任何對該目錄有寫入權者都改得到，不可當成可信資料。

    Raises:
        ValueError: 任一端逃出 root，或來源不是一般檔。
        FileNotFoundError: 來源不存在。
    """
    root = storage_root()
    target = _entry_within(root, old_path)
    if target is None:
        raise ValueError("舊路徑逃出 storage root")
    if os.path.lexists(target):
        return
    source = _regular_entry(root, new_path)
    parent = _ensure_real_dir(root, os.path.relpath(os.path.dirname(target), root))
    _link_entry(root, source, os.path.join(parent, os.path.basename(target)))


def _copy_atomically(root: str, source: str, target: str) -> None:
    """複製到 `.tmp/` 再 `os.replace` 到目標——中途失敗不會在目標位置留下半份檔。

    來源以 `O_NOFOLLOW` 開啟並以 `fstat` 確認是一般檔：檢查之後才被換成連結也讀不到它指向的檔。

    ⚠️ 已知限制：目標存在與否的檢查與 `os.replace` 之間有空窗，期間被建立的同名檔會被覆蓋。
    同一課程的「更新」由課程行鎖序列化、目標檔名是上傳時產生的 uuid，此路徑又只在檔案系統不支援
    hard link 時才走，故接受。
    """
    tmp_dir = os.path.join(root, TMP_DIRNAME)
    os.makedirs(tmp_dir, exist_ok=True)
    tmp = os.path.join(tmp_dir, f"{uuid.uuid4().hex}{os.path.splitext(target)[1]}")
    try:
        with os.fdopen(os.open(source, os.O_RDONLY | _O_NOFOLLOW), "rb") as src:
            if not stat.S_ISREG(os.fstat(src.fileno()).st_mode):
                raise ValueError("影片路徑不是一般檔")
            with open(tmp, "xb") as dst:
                shutil.copyfileobj(src, dst, CHUNK_SIZE)
        if os.path.exists(target):
            raise FileExistsError(errno.EEXIST, "目標位置已有同名檔")
        os.replace(tmp, target)
    except BaseException:
        discard(tmp)
        raise


def list_stored_files(root: str) -> list[tuple[str, float]]:
    """列出儲存根目錄下的所有**一般檔案**：`(相對路徑, 最後修改時間)`（#775 孤兒清理用）。

    相對路徑一律以 `/` 分隔，與 `ET_MATERIAL_VIDEO.FILE_PATH` 同格式。含 `.tmp/`：上傳中途
    當機留下的殘檔也在清理範圍內。

    ⚠️ **跳過 symlink**（security review L1）：根目錄內一個指向被引用檔的連結，本身不在白名單、
    又夠舊——若列出它，後續刪除一旦解析了連結，刪掉的是被引用的那支。`os.walk` 預設不跟隨
    目錄 symlink，檔案層級則在此以 `lstat` 判定。

    Args:
        root: 儲存根目錄的絕對路徑（呼叫端傳入，測試因此可指向暫存目錄）。

    Returns:
        根目錄不存在時回空清單（新環境尚未上傳過任何影片）。
    """
    if not os.path.isdir(root):
        return []
    unreadable: list[OSError] = []
    files: list[tuple[str, float]] = []
    for dirpath, _dirnames, filenames in os.walk(root, onerror=unreadable.append):
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                st = os.lstat(full)
            except OSError:
                continue  # 列舉與讀取之間被刪掉——不是孤兒，也不必報錯
            if not stat.S_ISREG(st.st_mode):
                continue
            files.append((os.path.relpath(full, root).replace(os.sep, "/"), st.st_mtime))
    if unreadable:
        # 讀不到的子目錄只會讓清理「少刪」，方向安全；但要看得出來，否則權限錯了永遠沒人知道
        logger.warning("ET 影片目錄有 %d 個子目錄無法讀取，其中的檔案未納入清理", len(unreadable))
    return files


def path_key(root: str, path: str) -> str:
    """把一個影片路徑正規化成「根目錄下的實際位置」，供白名單比對（#775）。

    DB 的 `FILE_PATH` 大多是 `/` 分隔的相對片段（#233），但 migration `676114dc0672` 轉不出來的
    列**原樣保留絕對路徑**，而讀取端（`_resolved_within_root`）仍接受落在根目錄內的絕對路徑。
    只比字串的話，那些列指向的檔會被當成孤兒刪掉。兩邊一律以 `os.path.join(root, path)` 解析，
    再以 `normcase` 抹平 Windows 的大小寫與分隔符。

    ⚠️ 只對**父目錄**做 `realpath`、檔名原樣接回——若檔案本身是連結，不追到它指向的目標
    （同 `list_stored_files` 的理由）。
    """
    joined = os.path.join(root, path)
    parent = os.path.realpath(os.path.dirname(joined))
    return os.path.normcase(os.path.join(parent, os.path.basename(joined)))


def _entry_within(real_root: str, path: str) -> str | None:
    """刪除用圍籬：父目錄以 `realpath` 解析後仍落在 `real_root` 內 → 回目標路徑，否則 `None`。

    ⚠️ **只解析父目錄、檔名原樣接回**——若解析檔名，一個指向他處的 symlink 會讓刪除落在它指向的
    檔上（security review L1）。`.` / `..` / 空檔名不是檔案，一律回 `None`。
    """
    joined = os.path.join(real_root, path)
    name = os.path.basename(joined)
    if name in ("", ".", ".."):
        return None
    try:
        parent = os.path.realpath(os.path.dirname(joined))
        if os.path.commonpath([real_root, parent]) != real_root:
            return None
    except (ValueError, OSError):  # 內嵌 NUL（POSIX realpath 拋 ValueError）、Windows 跨磁碟
        return None
    return os.path.join(parent, name)


def remove_stored_file(root: str, rel_path: str) -> bool:
    """刪除儲存根目錄下的一個一般檔案（#775 孤兒清理），回是否真的刪掉。

    圍籬：父目錄以 `realpath` 解析後**必須仍落在 root 內**，且目標必須是一般檔案（不是連結、
    不是目錄）。⚠️ 刪的是**連結本身的路徑**、不解析檔名——解析的話，一個指向被引用檔的連結
    會讓被引用的那支被刪掉（security review L1）。失敗（已不存在、權限）不拋錯：清理是盡力
    而為，一支刪不掉不該讓整批中止。
    """
    target = _entry_within(os.path.realpath(root), rel_path)
    if target is None:
        return False
    try:
        if not stat.S_ISREG(os.lstat(target).st_mode):
            return False
        os.remove(target)
    except OSError as exc:
        logger.warning("ET 孤兒影片檔刪除失敗（不記路徑）：%s", type(exc).__name__)
        return False
    return True


def discard(path: str) -> None:
    """刪除 storage root 內的一支檔（**絕對路徑**），失敗不拋錯（清理路徑上的失敗不該蓋掉原本的錯誤）。

    ## 圍籬（#240 A3）

    本函式原本「傳什麼就刪什麼」——目前呼叫端只傳伺服器自建路徑而安全，但日後任何人把 DB 值
    餵進來就是任意刪檔漏洞。故對非絕對路徑、root 外路徑（含 `..` 繞道、父目錄 symlink 逃逸）
    一律拒刪並記安全事件（**不記路徑**）。檔名本身是 symlink 時只刪連結、不碰其指向的檔。

    只吃絕對路徑的理由見 `promote` docstring（避免「有時絕對、有時相對」的雙語意）。

    ⚠️ **只圈到 root，不保護被引用中的檔**——root 內任何一支影片都刪得掉。目前呼叫端只傳
    `save_video_stream` 的暫存檔與 `promote` 剛回傳的絕對路徑；**不可把 DB 之 `FILE_PATH`
    換算後餵進來**，要刪被引用檔請走孤兒清理（`remove_stored_file`，有白名單比對）。
    """
    target = _entry_within(storage_root(), path) if isinstance(path, str) and os.path.isabs(path) else None
    if target is None:
        logger.warning("ET 影片刪除圍籬拒絕一筆非絕對或逃出 storage root 之路徑（不記路徑）")
        return
    try:
        os.remove(target)
    except (OSError, ValueError):  # ValueError：檔名段內嵌 NUL
        logger.warning("ET 影片暫存檔清理失敗（不記路徑）")
