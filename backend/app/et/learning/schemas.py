"""ET05 章節學習（US5 / #255）schema。

## 學員端與教師端不共用 schema

教師端的教材回應含 `version`（樂觀鎖）、`file_path` 等編輯用欄位；學員端只需要呈現
所需的東西。共用會讓落盤路徑隨教材內容一起發給每位學員——那是取檔端點要保護的
東西，不該從另一個端點漏出去。
"""

from pydantic import BaseModel

#: 可於頁內嵌入預覽的 MIME（AC 15）。其餘一律走「下載原檔」（AC 16）。
PREVIEWABLE_MIMES = frozenset({"application/pdf"})


class ItemNode(BaseModel):
    """章節下的一個項目（教材或測驗）。

    Attributes:
        title: 側欄顯示名稱——教材取 `MATERIAL_NAME`、測驗取 `QUIZ_NAME`。
        locked: 是否鎖定。**本 issue 恆為 `False`**——解鎖判定依賴 `ET_PROGRESS`
            （`ET-5b`）。欄位先備妥，`ET-5b` 交付時只需換掉取值來源，前端不必再改。
        completed: 是否已完成。**本 issue 恆為 `False`**，同上。
    """

    item_id: int
    item_type: str
    sort_order: int
    title: str
    material_id: int | None
    quiz_id: int | None
    locked: bool
    completed: bool


class ChapterNode(BaseModel):
    chapter_id: int
    chapter_name: str
    sort_order: int
    items: list[ItemNode]


class LearnStructure(BaseModel):
    """ET05 左側導覽所需之完整結構。

    Attributes:
        is_owner: 當前使用者為課程擁有者（教師預覽，#255 裁示 Q1=A）。前端據此顯示
            「預覽模式」提示，避免教師誤以為自己是以學員身分在累積進度。
        is_closed: 課程已關閉 → 前端顯示唯讀提示（ET-MSG-ET05-005）。
            **不過濾任何內容**（#255 裁示 Q2=A）——關閉限制的是寫入，不是讀取。
        playback_rates: 可選倍速，已依 `ET_VIDEO_PLAYBACK_MAX_RATE` 往下限縮。
    """

    course_id: int
    course_name: str
    status: str
    is_owner: bool
    is_closed: bool
    playback_rates: list[float]
    chapters: list[ChapterNode]


class MaterialVideoRow(BaseModel):
    """教材下的一支影片。**不含 `FILE_PATH`**——落盤路徑不對學員端外洩。"""

    video_id: int
    file_name: str
    duration_sec: int
    sort_order: int


class MaterialDocRow(BaseModel):
    """教材引用之 DM 文件。

    Attributes:
        version_id: 當前發布版之 ID。取檔端點需要它——`read_file_for_reference` 只放行
            當前版（D-1），舊版一律拒絕。
        obsolete: 已廢止（AC 17 / ET-MSG-ET05-003）。**仍可閱讀**廢止前最後版本——
            `CURRENT_VERSION_ID` 此時指向的就是那一版。
        previewable: 可否頁內嵌入（PDF → true；其餘走下載，AC 15 / 16）。
        available: 文件可否取得。DM 端查無 / 非可引用分類時為 `false`——此時前端顯示
            「文件無法取得」而非給一個點了會 404 的連結。
    """

    doc_id: str
    doc_name: str | None
    file_name: str | None
    file_mime: str | None
    version_id: int | None
    obsolete: bool
    previewable: bool
    available: bool
    sort_order: int


class MaterialContent(BaseModel):
    """教材內容（中間內容區）。"""

    material_id: int
    material_name: str
    description_html: str | None
    videos: list[MaterialVideoRow]
    docs: list[MaterialDocRow]


class VideoTicket(BaseModel):
    """短效播放票（#255）。

    `<video src>` 送不出 Authorization header，故以票放進 query string 取檔——形同
    S3 presigned URL。見 `video_ticket` 模組之三道限制（60 秒、綁單一影片、`typ` 與
    access token 嚴格區隔）。
    """

    ticket: str
    expires_in: int
