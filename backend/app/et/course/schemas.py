"""ET02 課程骨架、章節編排與章節項目（US3 / #202、#203）schema。

課程骨架與章節屬 #202；章節項目（教材 / 測驗之掛載與排序）屬 #203。
教材與測驗**內容**之 schema 另置於 `app/et/material/schemas.py` 與
`app/et/quiz/schemas.py`——本檔只到「項目」這層容器。
問卷 / 發布屬 #204；`STATUS` 目前僅寫入 `DRAFT`。
"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# 課程描述長度上限（spec_us3 AC 1「至多 500 字」）。
# data-model 之 `DESCRIPTION` 為 TEXT 無長度限制，故由應用層把關；前端另以 Zod 同步檢核。
DESCRIPTION_MAX_LEN = 500
COURSE_NAME_MAX_LEN = 100
CHAPTER_NAME_MAX_LEN = 100

# 一次請求可帶的受訓單位標籤上限（比照 #185 `assign` 之 `_MAX_GROUPS`）。
# 無上限時，數萬筆的 `IN (...)` 會讓 SQLAlchemy / asyncpg 拋未處理例外（500）——
# 標籤庫實務上僅個位數～數十筆，此界限不影響正常使用。
MAX_TAG_IDS = 100
# 一門課程之章節數上限——重排送完整陣列，無界限同樣可被當成放大攻擊面。
MAX_CHAPTER_IDS = 500
# 一個章節之項目數上限（同上理由）。
MAX_ITEM_IDS = 500
# 教材 / 測驗名稱長度上限（data-model：`MATERIAL_NAME` / `QUIZ_NAME` 皆 VARCHAR(100)）。
ITEM_TITLE_MAX_LEN = 100
# BIGINT 上限：路徑參數與 ID 超出時，asyncpg 比對會溢位成 500 而非 404。
MAX_BIGINT = 9_223_372_036_854_775_807


def _strip_or_none(value: str | None) -> str | None:
    """前後空白去除；全空白視同未填。"""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class _CourseFields(BaseModel):
    """課程基本資料之共用欄位與驗證（建立 / 更新皆適用）。

    **僅課程名稱必填**——受訓單位標籤與起訖時間為「發布時」必填（FR-ET-US3-01），
    草稿階段允許留空，故此處皆為選填。`OWNER_ID` 取自 JWT，不由請求帶入。
    """

    course_name: str = Field(min_length=1, max_length=COURSE_NAME_MAX_LEN)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LEN)
    open_start_at: datetime | None = None
    open_end_at: datetime | None = None
    require_approval: bool = False
    tag_ids: list[int] = Field(default_factory=list, max_length=MAX_TAG_IDS)

    @field_validator("course_name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        """全空白之名稱等同未填——`min_length` 擋不掉 `"   "`。"""
        stripped = v.strip()
        if not stripped:
            raise ValueError("課程名稱不得為空白")
        return stripped

    @field_validator("description")
    @classmethod
    def _normalise_description(cls, v: str | None) -> str | None:
        return _strip_or_none(v)

    @field_validator("tag_ids")
    @classmethod
    def _valid_tag_ids(cls, v: list[int]) -> list[int]:
        """`TAG_ID` 為 Identity 正整數；非正數或超出 BIGINT 者於 DB 比對會溢位成 500。"""
        if any(not (0 < tag_id <= MAX_BIGINT) for tag_id in v):
            raise ValueError("受訓單位標籤 ID 不合法")
        return v

    @field_validator("open_start_at", "open_end_at")
    @classmethod
    def _ensure_aware(cls, v: datetime | None) -> datetime | None:
        """外部進來的 naive datetime 補 UTC（`sti-backend-modules` §時間處理）。

        `OPEN_START_AT` / `OPEN_END_AT` 於 DB 為 `TIMESTAMPTZ`；若收到無時區之值
        （如 `<input type="datetime-local">` 原樣送出的 `2026-04-15T09:00`），
        PostgreSQL 會以**連線時區**解讀而靜默位移，使「起始時間前學員不可見」
        （#204）與「到期自動關閉」（#16 SCHET002）等時間判定算錯。

        本專案前端已於 `utils/date.fromDateTimeLocalInput` 轉為帶時區之 ISO 8601；
        此處為深度防禦，涵蓋其他客戶端與直呼 API 的情況。
        """
        return v.replace(tzinfo=timezone.utc) if v is not None and v.tzinfo is None else v

    @model_validator(mode="after")
    def _end_after_start(self) -> "_CourseFields":
        """課程訖止時間須晚於起始時間。

        兩者皆填時才檢核——草稿允許留空（FR-ET-US3-01），發布必填之檢核屬 #204。

        **「起始須 ≥ 當下」不在此檢核**：該規則只對「使用者這次改動的值」成立
        （SA 裁示，2026-08-24）。已發布課程的起始時間必然落在過去，若後端無條件檢核，
        教師之後編輯該課程（AC 28 允許）會因為沿用原值而永遠存不了檔。故該約束落在
        前端輸入層（選擇器 `minDateTime` + 僅對已變更之值驗證）。
        """
        if self.open_start_at and self.open_end_at and self.open_end_at <= self.open_start_at:
            raise ValueError("課程訖止時間須晚於起始時間")
        return self


class CourseCreateReq(_CourseFields):
    """建立草稿課程，**可一併帶入章節名稱**。

    章節有 `COURSE_ID` 外鍵，課程不存在時掛不上去——若要求使用者「先存草稿才能加章節」，
    新增流程會出現一個沒有業務意義的斷點。改由前端於新增模式將章節暫存於畫面、
    儲存時一次送出，後端在**同一交易內**建立課程與章節：不會出現「課程建好但章節
    建到一半失敗」的殘局。

    課程建立後，章節改由 `/courses/{id}/chapters` 等端點各自維護，故 `CourseUpdateReq`
    **不含**本欄位。
    """

    chapters: list[str] = Field(default_factory=list, max_length=MAX_CHAPTER_IDS)

    @field_validator("chapters")
    @classmethod
    def _valid_chapter_names(cls, v: list[str]) -> list[str]:
        names = [name.strip() for name in v]
        if any(not name for name in names):
            raise ValueError("章節名稱不得為空白")
        if any(len(name) > CHAPTER_NAME_MAX_LEN for name in names):
            raise ValueError(f"章節名稱不可超過 {CHAPTER_NAME_MAX_LEN} 字元")
        return names


class CourseUpdateReq(_CourseFields):
    """更新課程基本資料；`version` 供樂觀鎖檢核。

    本表單為全量覆寫（前端一次送出整張基本資料卡），非 partial update，
    故不使用 `exclude_unset`。**不含 `chapters`**——課程存在後章節由專屬端點維護。
    """

    version: int = Field(ge=0)


class ChapterCreateReq(BaseModel):
    """新增章節（追加至最末，`SORT_ORDER` 由後端計算）。"""

    chapter_name: str = Field(min_length=1, max_length=CHAPTER_NAME_MAX_LEN)

    @field_validator("chapter_name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("章節名稱不得為空白")
        return stripped


class ChapterRenameReq(ChapterCreateReq):
    """更名章節；`version` 供樂觀鎖檢核。"""

    version: int = Field(ge=0)


class ChapterReorderReq(BaseModel):
    """章節重排：送**完整順序陣列**而非相對移動。

    相對移動（上移 / 下移）在並行編輯時會疊加出非預期結果；完整陣列表達的是
    最後寫入者的完整意圖。`version` 為**課程層**版本——重排是課程結構的變更。
    """

    chapter_ids: list[int] = Field(max_length=MAX_CHAPTER_IDS)
    version: int = Field(ge=0)


class ItemCreateReq(BaseModel):
    """新增章節項目（教材或測驗），追加至章節最末。

    後端於**同一交易**內建立對應之 `ET_MATERIAL` / `ET_QUIZ` 空殼——前端不需先建
    教材再建項目，避免中途失敗留下孤兒。

    ## 名稱可留空（2026-08-27 依實測回饋）

    原本前端會代填「新教材」/「新測驗」。那是替使用者做決定——他開了視窗第一件事
    就是把那串字選起來刪掉。改為建立時可空、開啟視窗即為空白欄位讓他直接輸入。

    **儲存時仍必填**（`MaterialUpdateReq` / `QuizUpdateReq` 之 `min_length=1`）——
    空名稱只是「還沒填」的過渡狀態，不是可以存檔的樣子。
    """

    item_type: Literal["MATERIAL", "QUIZ"]
    title: str = Field(default="", max_length=ITEM_TITLE_MAX_LEN)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, v: str) -> str:
        return v.strip()


class ItemReorderReq(BaseModel):
    """項目重排：送**完整順序陣列**（同章節重排之契約）。

    `version` 為**章節層**版本——項目順序是章節結構的一部分。不用項目自身版本：
    重排一次動多列，且遞增各項目版本會讓正在編輯該教材內容的另一裝置無故衝突
    （FR-ET-US3-15「不同實體並行編輯互不衝突」）。
    """

    item_ids: list[int] = Field(max_length=MAX_ITEM_IDS)
    version: int = Field(ge=0)


class ItemRow(BaseModel):
    """章節項目列（回應）。

    `title` 取自對應之 `MATERIAL_NAME` / `QUIZ_NAME`——項目本身不存名稱，避免
    與教材 / 測驗改名後不同步。
    """

    item_id: int
    item_type: str
    title: str
    sort_order: int
    material_id: int | None
    quiz_id: int | None
    version: int


class ChapterItem(BaseModel):
    """章節列（回應），含其下項目。"""

    model_config = {"from_attributes": True}

    chapter_id: int
    chapter_name: str
    sort_order: int
    version: int
    items: list[ItemRow] = Field(default_factory=list)


class CourseDetail(BaseModel):
    """課程詳細（回應）。

    `is_owner` 由 service 依當前操作者計算——前端據此決定是否唯讀
    （`spec.md` §擁有權判定：他人課程僅可閱覽）。`owner_name` 取自 `DP_USER`
    之唯讀 JOIN，供檢視模式 banner 顯示「此課程由 {建立者} 建立」。
    """

    model_config = {"from_attributes": True}

    course_id: int
    course_name: str
    description: str | None
    status: str
    open_start_at: datetime | None
    open_end_at: datetime | None
    require_approval: bool
    version: int
    owner_id: str
    owner_name: str | None
    is_owner: bool
    tag_ids: list[int]
    chapters: list[ChapterItem]


class CourseCreateResult(BaseModel):
    """建立結果——前端據 `course_id` 導向編輯頁。"""

    course_id: int
    version: int


class Capabilities(BaseModel):
    """當前使用者於 ET 課程之操作能力（供前端決定入口顯示）。

    **回「能力」而非「角色」**，比照 DM 之 `app/dm/library/schemas.Capabilities`：
    若回角色清單，前端得自己再寫一次「有 TEACHER 就顯示」的判斷，那份邏輯會與後端
    `require_et_roles(ET_TEACHER)` 各自演化、遲早不一致。回能力則只有一個判斷來源。

    > 前端無從自行推導：JWT **刻意不含角色**（`sti-backend-modules`——角色即時查
    > `ET_USER_ROLE`，使撤銷權限下一個請求即生效，不必等 token 過期），
    > 而 `/dp/user/module-summary` 只回「有無任一 ET 角色」之布林（最小知悉）。
    """

    can_create_course: bool  # 具教師角色（SA 裁示 Q2）→ 顯示「新增課程」入口


class TagOption(BaseModel):
    """受訓單位標籤下拉項。

    `is_active=False` 只會出現在「課程既有已掛之停用標籤」——新掛時不得選取
    （FR-ET-US3-03：停用標籤排除於可選清單、既有已掛保留）。
    """

    model_config = {"from_attributes": True}

    tag_id: int
    tag_name: str
    is_active: bool


class PublishBlockerRow(BaseModel):
    """一條發布缺漏（回應）。

    `message` 為**靜態**文案、不內插使用者輸入；出問題的對象以 `target_id` 表達，
    前端自行從已載入的課程詳細對照出名稱（見 `publish_rules` 模組 docstring）。
    """

    code: str
    message: str
    target_id: int | None = None


class PublishCheckResult(BaseModel):
    """發布預檢結果（回應）。

    預檢是**體驗**、不是把關——讓教師在按下發布**之前**就看到缺漏。發布端點自身
    會重跑同一套檢核，繞過預檢直接打 POST 一樣擋得下來。
    """

    can_publish: bool
    blockers: list[PublishBlockerRow]


class PublishResult(BaseModel):
    """發布成功之結果（回應）。

    `invitation_code` 於發布時產生、**發布後永久不可變更**（data-model §ET_COURSE）。
    `first_published_at` 僅供稽核、不顯示於 UI，故**不在此回傳**。
    """

    course_id: int
    status: str
    invitation_code: str
    version: int
