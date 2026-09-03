"""ET05 章節學習 API（US5 / #255）——學員端內容取用。

router-level 只掛 `get_et_context`（任一 ET 角色）。真正的授權在**每個端點各自**的
「在籍 OR 擁有者」判定——見 `rules.ensure_can_access`。

## 四個端點各自判定，不共用一次查詢結果

理由不是效能，是**遺漏的形狀**：共用一次前置查詢時，新增第五個端點的人很容易忘記
掛上，而那個遺漏在測試裡看不出來（他的測試會用有權限的帳號）。故四個端點各自呼叫
service 的授權路徑，且**各有一條「無權」的 integration 測試**。

影片與 DM 文件是**實體檔案**——少一道判定，任何登入者（ET 學員角色人人都有）知道
`video_id` 就能抓走全站教材。

## 取檔一律 `FileResponse`

Starlette 之 `FileResponse` **原生支援 Range 請求**（`_parse_range_header`），HTML5
播放器拖動進度條所需的 206 由框架處理。**不要自行實作**——Range 的邊界語意、
`Content-Range` 格式、multipart ranges 都容易寫壞，而寫壞的表現是「影片只能從頭播」
這種不易歸因的症狀。
"""

from pathlib import Path as FsPath
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import AppError
from app.et.course.schemas import MAX_BIGINT
from app.et.deps import EtContext, get_et_context
from app.et.learning.schemas import LearnStructure, MaterialContent, VideoTicket
from app.et.learning.service import EtLearningService
from app.et.learning.video_ticket import TICKET_TTL_SECONDS, issue_video_ticket, verify_video_ticket

router = APIRouter(
    prefix="/api/et",
    tags=["et-learning"],
    dependencies=[Depends(get_et_context)],
)
_service = EtLearningService()

#: `ET_MATERIAL_DOC.DOC_ID` 為 `VARCHAR(20)`。
_DOC_ID_MAX_LEN = 20


@router.get("/courses/{course_id}/learn", response_model=LearnStructure)
async def learn_structure(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> LearnStructure:
    """ET05 左側導覽結構（章節 → 項目）+ 課程狀態 + 可選倍速。

    非在籍且非擁有者回 **403 `ET_LEARN_002`**——課程的存在對學員不是秘密（他可能正要
    加入），而「你尚未加入此課程」是可行動的訊息。**以 id 定址的資源端點則一律 404**
    （見 service 之 `_FILE_NOT_FOUND`）。
    """
    return await _service.structure(db, course_id, user_id=ctx.user_id)


@router.get("/materials/{material_id}/content", response_model=MaterialContent)
async def material_content(
    material_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> MaterialContent:
    """教材內容：說明文字 + 影片清單 + DM 文件清單（含廢止旗標與可否內嵌預覽）。"""
    return await _service.material_content(db, material_id, user_id=ctx.user_id)


@router.post("/videos/{video_id}/ticket", response_model=VideoTicket)
async def video_ticket(
    video_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> VideoTicket:
    """簽發短效播放票，供 `<video src>` 取檔（見 `video_ticket` 模組）。

    **授權在此完成**：走與其他端點相同的「在籍 OR 擁有者」判定；取檔端點只驗票。
    """
    await _service.ensure_video_accessible(db, video_id, user_id=ctx.user_id)
    return VideoTicket(ticket=issue_video_ticket(user_id=ctx.user_id, video_id=video_id), expires_in=TICKET_TTL_SECONDS)


@router.get("/materials/{material_id}/docs/{doc_id}/file")
async def material_doc_file(
    material_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    doc_id: Annotated[str, Path(min_length=1, max_length=_DOC_ID_MAX_LEN)],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """教材引用之 DM 文件實體檔（PDF 供頁內預覽、其餘供下載）。

    授權由 `material_id` 那側判定，另驗證 `doc_id` **確實被此教材引用**——否則在籍
    任一課程者即可用自己有權的 `material_id` 搭配任意 `doc_id` 取走全站被引用的文件。
    """
    content = await _service.doc_file(db, material_id, doc_id, user_id=ctx.user_id)
    _ensure_file_present(content.path)
    return FileResponse(content.path, media_type=content.mime, filename=content.name)


def _ensure_file_present(path: str) -> None:
    """實體檔缺失（DB↔磁碟不一致）時回統一 404。

    `resolve_within_root` 只做 storage-root 圍籬、**不檢查存在性**；少了本檢查，
    `FileResponse` 會拋 `RuntimeError: File at path ... does not exist` 而成為 500，
    **且 traceback 含落盤絕對路徑**。

    這個情境不是理論：`ET_VIDEO_STORAGE_ROOT` 預設為相對路徑（`./var/et_videos`），
    從不同工作目錄啟動後端就會指向不同的 root，DB 裡的所有 `FILE_PATH` 一起對不到
    ——2026-09-03 DM 那側正是這樣掉了 9 筆檔案實體。

    比照 `dm/detail/router.get_version_file` 之既有作法。
    """
    if not FsPath(path).is_file():
        raise AppError(status_code=404, detail="查無此課程內容", error_code="ET_LEARN_001")


# ── 媒體 router：**不掛 router-level 認證** ──────────────────────────────────
#
# `<video src>` 送不出 `Authorization` header，故本 router 的唯一端點以**播放票**
# 認證（`video_ticket` 模組）。它必須與上面的 `router` 分開——後者的 router-level
# `get_et_context` 會強制 Bearer，掛在同一個 router 上就永遠拿不到票的路徑。
#
# ⚠️ **不要往這個 router 加其他端點**。它是唯一一處沒有 router-level 認證的地方，
# 新端點掛進來等於預設無認證，而那種遺漏在測試裡看不出來（測試會帶票）。
media_router = APIRouter(prefix="/api/et", tags=["et-learning-media"])


@media_router.get("/videos/{video_id}/file")
async def video_file(
    video_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    t: Annotated[str, Query(min_length=1, max_length=2048)],
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """影片實體檔（**憑票取用**）。

    Range 由 `FileResponse` 處理，播放器可正常拖動進度條。票的驗證不查 DB——見
    `video_ticket` 模組「取檔時不重跑授權」一節之取捨說明。
    """
    verify_video_ticket(t, video_id=video_id)
    path, file_name = await _service.video_file_by_ticket(db, video_id)
    _ensure_file_present(path)
    # `inline`：本端點的用途是**串流播放**。Starlette 預設 `attachment`，把這個 URL
    # 貼到網址列會被強制下載而非播放——語意不符，且對「複製連結確認影片能不能開」
    # 這種日常操作很不直覺。
    return FileResponse(path, filename=file_name, content_disposition_type="inline")
