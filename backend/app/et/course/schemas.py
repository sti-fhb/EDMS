"""ET02 課程骨架與章節編排（US3 / #202）schema。

本 issue 只涵蓋課程骨架與章節；教材 / 測驗屬 #203、問卷 / 發布屬 #204。
`STATUS` 於本 issue 僅寫入 `DRAFT`——發布為 #204 之職責。
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# 課程描述長度上限（spec_us3 AC 1「至多 500 字」）。
# data-model 之 `DESCRIPTION` 為 TEXT 無長度限制，故由應用層把關；前端另以 Zod 同步檢核。
DESCRIPTION_MAX_LEN = 500
COURSE_NAME_MAX_LEN = 100
CHAPTER_NAME_MAX_LEN = 100


def _strip_or_none(value: str | None) -> str | None:
    """前後空白去除；全空白視同未填。"""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class CourseCreateReq(BaseModel):
    """建立草稿課程。

    **僅課程名稱必填**——受訓單位標籤與起訖時間為「發布時」必填（FR-ET-US3-01），
    草稿階段允許留空，故此處皆為選填。`OWNER_ID` 取自 JWT，不由請求帶入。
    """

    course_name: str = Field(min_length=1, max_length=COURSE_NAME_MAX_LEN)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LEN)
    open_start_at: datetime | None = None
    open_end_at: datetime | None = None
    require_approval: bool = False
    tag_ids: list[int] = Field(default_factory=list)

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


class CourseUpdateReq(CourseCreateReq):
    """更新課程基本資料；`version` 供樂觀鎖檢核。

    繼承建立之欄位與驗證：本表單為全量覆寫（前端一次送出整張基本資料卡），
    非 partial update，故不使用 `exclude_unset`。
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

    chapter_ids: list[int]
    version: int = Field(ge=0)


class ChapterItem(BaseModel):
    """章節列（回應）。"""

    model_config = {"from_attributes": True}

    chapter_id: int
    chapter_name: str
    sort_order: int
    version: int


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


class TagOption(BaseModel):
    """受訓單位標籤下拉項。

    `is_active=False` 只會出現在「課程既有已掛之停用標籤」——新掛時不得選取
    （FR-ET-US3-03：停用標籤排除於可選清單、既有已掛保留）。
    """

    model_config = {"from_attributes": True}

    tag_id: int
    tag_name: str
    is_active: bool
