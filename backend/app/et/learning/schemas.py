"""ET05 章節學習（US5 / #255）schema。

## 學員端與教師端不共用 schema

教師端的教材回應含 `version`（樂觀鎖）、`file_path` 等編輯用欄位；學員端只需要呈現
所需的東西。共用會讓落盤路徑隨教材內容一起發給每位學員——那是取檔端點要保護的
東西，不該從另一個端點漏出去。
"""

from pydantic import BaseModel

from app.et.survey_fill.schemas import SurveyEntry

#: 可於頁內嵌入預覽的 MIME（AC 15）。其餘一律走「下載原檔」（AC 16）。
PREVIEWABLE_MIMES = frozenset({"application/pdf"})


class ItemNode(BaseModel):
    """章節下的一個項目（教材或測驗）。

    Attributes:
        title: 側欄顯示名稱——教材取 `MATERIAL_NAME`、測驗取 `QUIZ_NAME`。
        locked: 是否鎖定（#274）。章節依序 + 章節內依序，見
            `progress.rules.locked_item_ids`。**教師預覽恆為 `False`**——他沒有進度可
            累積（#255 裁示 Q1），照學員規則算會把他鎖在第 1 項，預覽就失去意義。
        completed: 是否已完成（#274）。測驗項目的完成 = **該測驗已及格**（#279 起於提交
            及格時回寫 `ET_PROGRESS`）。

            ⚠️ 自 #361 起未及格的測驗**會擋住後續**（`spec_us5` AC 12）。例外只有一題
            都沒有的測驗——那種考不了也就救不了，見 `progress.rules.build_item_state`。
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
        last_item_id: 上次檢視之項目（#274 SA Q1 裁示 B）。`None` = 還沒看過任何項目
            → 前端定位第 1 章第 1 項。影片內的秒數是另一半，在
            `MaterialVideoRow.last_position_sec`。
        survey: 課後問卷入口狀態（#284）。**`None` = 該課程沒有問卷**（問卷為選配，
            US3 AC 23），此時側欄整塊不渲染。

            隨本回應一併回傳而非另開端點：側欄必須在第一次繪製就決定「渲染入口 /
            不渲染」，二次請求會造成可見的跳動，而「未完課 → 不顯示」是最常見的狀態，
            為它多打一趟請求不划算。
        blocking_item_type: 擋住學習前緣的那一項之 `ITEM_TYPE`（`MATERIAL` / `QUIZ`），
            全部完成或教師預覽時為 `None`。供前端對鎖定項目給出**正確**的提示
            （`spec_us5` AC 12「阻擋並提示」）。

            🔴 **由後端給而非前端自行推導**：推導要用到解鎖規則（依序 + 0 題測驗例外），
            前端自己算一份就是把同一條規則寫成兩個版本。前端只做「型別 → 文案」的對應。

            ⚠️ 是**整份結構一個值**，不是逐項一個：解鎖規則嚴格依序，故所有鎖定都追溯
            到同一項（見 `progress/rules.first_blocking_item`）。

            ℹ️ 型別為 `str` 而非 `Literal["MATERIAL", "QUIZ"]`——本專案的**請求** schema
            用 `Literal`（如 `course/schemas.ItemCreateReq.item_type`），**回應** schema
            一律用 `str`（本檔 `ItemNode.item_type`、`course/schemas.ItemRow.item_type`）。
            只收斂這一個會讓它變成同一組回應裡的異類。值出自本系統自己的 DB，不是外部
            輸入，故 `Literal` 的驗證價值也有限。
    """

    course_id: int
    course_name: str
    status: str
    is_owner: bool
    is_closed: bool
    playback_rates: list[float]
    last_item_id: int | None
    survey: SurveyEntry | None
    chapters: list[ChapterNode]
    blocking_item_type: str | None


class MaterialVideoRow(BaseModel):
    """教材下的一支影片。**不含 `FILE_PATH`**——落盤路徑不對學員端外洩。

    Attributes:
        coverage_pct: 該學員對這支影片的累計覆蓋率（#274）。播放器下方顯示「完成 65%」，
            達 80% 即解鎖。**教師預覽恆為 0**——他不累積進度。
        last_position_sec: 上次播放到第幾秒，供續看（AC 11 的另一半）。`None` = 從頭播。
    """

    video_id: int
    file_name: str
    duration_sec: int
    sort_order: int
    coverage_pct: int
    last_position_sec: int | None


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
