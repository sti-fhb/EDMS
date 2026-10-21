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

import logging
import os
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
    """影片儲存根目錄之正規化絕對路徑（單一事實來源：`settings.ET_VIDEO_STORAGE_ROOT`）。"""
    return os.path.realpath(settings.ET_VIDEO_STORAGE_ROOT)


def _resolved_within_root(path: str) -> str | None:
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
    root = storage_root()
    try:
        resolved = os.path.realpath(os.path.join(root, path))
        return resolved if os.path.commonpath([root, resolved]) == root else None
    except (ValueError, TypeError):
        return None


def resolve_within_root(file_path: str, *, not_found: AppError) -> str:
    """讀取端圍籬：回正規化後之安全路徑；逃逸出根目錄則 raise 呼叫端提供之 `not_found`。

    錯誤文案由呼叫端自帶，避免與該端點其他 404 措辭不一致。逃逸時記安全事件但
    **不記落盤路徑**（遵 `sti-backend-logging`）。

    ⚠️ **播放端點落地時必須比照 DM，先做 `Path(resolved).is_file()` 再開檔**（見
    `app/dm/detail/router.py`）。Windows 的 `os.path.realpath` 不拒絕內嵌 NUL 字元
    （CPython gh-106242），帶 NUL 的路徑會通過本圍籬；`pathlib` 的 `is_file()` 內部
    `except ValueError: return False`，能把它收斂成統一 404，但若直接 `open(resolved)`
    則會拋 `ValueError` 冒成 500。POSIX 端 `realpath` 本身就會拋、由此處 fail-closed
    接住，兩平台行為因而一致。此為 #233 security review INFO-6。
    """
    resolved = _resolved_within_root(file_path)
    if resolved is None:
        logger.warning("ET 影片 storage-root 圍籬攔截一筆逃逸 / 無效之 FILE_PATH（不記路徑）")
        raise not_found
    return resolved


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


def promote(tmp_path: str, *, video_id_hint: str, ext: str) -> tuple[str, str]:
    r"""把暫存檔搬到正式路徑，回 `(絕對路徑, 相對於 root 之片段)`。

    同一檔案系統內的 `os.replace` 是原子操作——不會出現「搬一半」的檔案。

    ## 為何回兩個值（#233）

    兩者用途不同且**不可互換**：

    | 用途 | 要哪一個 | 拿錯的後果 |
    |------|---------|-----------|
    | 寫入 `ET_MATERIAL_VIDEO.FILE_PATH` | 相對片段 | 存絕對路徑 → 換 root / 清 worktree 即永久失聯 |
    | 失敗時 `discard()` 回滾刪檔 | 絕對路徑 | 傳相對片段 → `os.remove` 依 CWD 解析而找不到，`discard`
    | | | 吞掉 `OSError` 只留 warning，**靜默留下孤兒檔** |

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
    """
    root = storage_root()
    final_dir = os.path.join(root, video_id_hint)
    os.makedirs(final_dir, exist_ok=True)
    final_path = os.path.join(final_dir, f"{uuid.uuid4().hex}.{ext}")
    os.replace(tmp_path, final_path)
    # 相對片段由實際落地的絕對路徑反推，而非另行組字串——避免「落地的」與「入 DB 的」
    # 是兩個各自組出來的東西，日後任一端重構即可能靜默產生落差
    return final_path, os.path.relpath(final_path, root).replace(os.sep, "/")


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


def remove_stored_file(root: str, rel_path: str) -> bool:
    """刪除儲存根目錄下的一個一般檔案（#775 孤兒清理），回是否真的刪掉。

    圍籬：父目錄以 `realpath` 解析後**必須仍落在 root 內**，且目標必須是一般檔案（不是連結、
    不是目錄）。⚠️ 刪的是**連結本身的路徑**、不解析檔名——解析的話，一個指向被引用檔的連結
    會讓被引用的那支被刪掉（security review L1）。失敗（已不存在、權限）不拋錯：清理是盡力
    而為，一支刪不掉不該讓整批中止。
    """
    real_root = os.path.realpath(root)
    joined = os.path.join(real_root, rel_path)
    parent = os.path.realpath(os.path.dirname(joined))
    target = os.path.join(parent, os.path.basename(joined))
    try:
        if os.path.commonpath([real_root, parent]) != real_root:
            return False
    except ValueError:  # Windows 跨磁碟
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
    """刪除檔案，失敗不拋錯（清理路徑上的失敗不該蓋掉原本的錯誤）。"""
    try:
        os.remove(path)
    except OSError:
        logger.warning("ET 影片暫存檔清理失敗（不記路徑）")
