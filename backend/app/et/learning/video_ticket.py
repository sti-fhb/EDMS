"""影片播放票（US5 / #255）——讓 `<video src>` 能通過認證。

## 為什麼需要它

JWT 是 **memory-only**（刻意不落 cookie），而 `<video src>` / `<iframe src>` **不會帶
`Authorization` header**。DM 的既有解法是以 axios 取 blob（`dm/detail/detailService`），
文件幾 MB 沒問題——**但影片單檔上限 500MB**（`DP_PARAM.ET_VIDEO_MAX_SIZE_MB`）：
blob 要整支下載完才能播、失去 Range（拖不動進度條）、整支進記憶體。

故影片改發**短效播放票**放進 query string，形同 S3 presigned URL。

## 三道限制讓「憑證進 URL」的代價可接受

1. **5 分鐘有效**——足以涵蓋一次正常的開啟→播放；過期後前端自動重取
2. **綁單一影片**（`vid` claim 與路徑比對）——外洩也只能取那一支
3. **`typ` 嚴格區隔**——票**不可**當一般 access token 用，access token 也**不可**當票用

第 3 點是關鍵。若共用 claim 集，一個從 access log 撈到的票就等於一組帳號憑證；反過來
若接受一般 token 當票，等於把長效憑證引進 URL。兩個方向都要擋，故簽發與驗證各自檢查
`typ`。

## 取檔時不重跑授權——這是刻意的

拖動進度條會讓瀏覽器對**同一個 URL** 連續發出多個 Range 請求。若每次都重跑「查課程 →
查在籍」，一次拖拉就是數十次 DB 往返，而它們的答案在 60 秒內不可能改變。

故採 presigned URL 的標準模型：**票本身即授權**，取檔端點只驗票、不查 DB。

代價是一個**最長 5 分鐘的窗口**——學員在發票後被移除、或帳號被停用，仍可繼續播放
當下這一支影片。這在內部訓練系統可接受：他本來就已經看過那些內容，而下一支影片、
以及過期後的自動重取，都會因發票端點的授權失敗而拿不到票。

**但教師刪除內容不受此窗口影響**：`video_file_by_ticket` 仍過濾
`EtMaterialVideo.deleted == 0`，而刪章節會連帶軟刪影片，故立即生效。
"""

from typing import Final

import jwt

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.utils import utcnow

#: 票的有效秒數。
#:
#: ⚠️ **不可設成「夠發起一次連線」的長度**（初版設 60 秒，錯的）。`<video>` 對同一個
#: URL 會**反覆**發出新請求，而它們都帶著同一張票：
#:
#: 1. `preload="metadata"` 只預抓 metadata——真正的內容請求要等使用者**按下播放**才
#:    發出。學員先看完教材說明文字再點播放（本頁同時呈現說明 / 影片 / 文件三塊），
#:    第一次播放就可能已經超過票的效期。
#: 2. 長時間暫停後續播，瀏覽器多半已關閉底層連線，續播是一個全新請求。
#: 3. 拖曳到未緩衝區段同理。
#:
#: 故 TTL 需涵蓋「開啟頁面到實際互動」的典型停留，另由前端於播放失敗時自動重取票
#: （`VideoPlayer` 的 `onError`）處理超出此長度的情形。
TICKET_TTL_SECONDS: Final = 300

#: `typ` claim 之值。與 access token 區隔的唯一依據——**改動即破壞隔離**。
_TICKET_TYPE: Final = "et-video-ticket"

_INVALID = AppError(status_code=404, detail="查無此課程內容", error_code="ET_LEARN_001")


def issue_video_ticket(*, user_id: str, video_id: int) -> str:
    """簽發綁定「使用者 × 單一影片」之短效票。

    呼叫端**必須先完成授權**（在籍 OR 擁有者）——本函式只負責簽章，不做任何權限判斷。
    """
    now = utcnow()
    claims = {
        "sub": user_id,
        "vid": video_id,
        "typ": _TICKET_TYPE,
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + TICKET_TTL_SECONDS,
    }
    return jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_video_ticket(token: str, *, video_id: int) -> str:
    """驗票並回傳 `USER_ID`。

    三道檢查缺一不可：簽章與過期（`jwt.decode`）、`typ` 為票（**不接受一般 access
    token**）、`vid` 與請求路徑相符（**不接受別支影片的票**）。

    失敗一律回 `ET_LEARN_001`（404）——與「查無此影片」同一個回應，不讓錯誤碼洩漏
    「這支影片存在，只是你的票不對」。

    Raises:
        AppError: 404 `ET_LEARN_001`。
    """
    try:
        raw = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise _INVALID from exc

    if raw.get("typ") != _TICKET_TYPE:
        # 一般 access token 沒有這個 claim——擋住「拿登入 token 當播放票」。
        raise _INVALID
    if raw.get("vid") != video_id:
        # 擋住「用 A 影片的票取 B 影片」。
        raise _INVALID
    sub = raw.get("sub")
    if not isinstance(sub, str) or not sub:
        raise _INVALID
    return sub
