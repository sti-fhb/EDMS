"""暫存區 ↔ 11 張內容表的對照（#631）。

本模組只描述「哪個 `ENTITY_TYPE` 對應哪張表、父層是誰、哪些欄位要搬」，不含 I/O，也不含
業務規則（規則在 `stage_rules.py`，純函式）。

## 🔴 `payload_fields` 是**推導**的，不是手寫清單

搬哪些欄位由 model metadata 算出來：全部欄位扣掉 PK、父子連結欄位、`SORT_ORDER`、
`VERSION` 與稽核欄位。

手寫清單的失效方式是**靜默的**：日後有人幫 `ET_QUESTION` 加一個欄位、忘了補進清單，
seed 不會搬它、套用時會把活表那一欄寫回預設值——教師看到的是「我改的東西按更新就不見
了」，而測試全綠。推導讓那個遺漏不可能發生。

⚠️ 代價是反過來：**新欄位會自動被納入**。若某個新欄位**不該**版本化（例如又一個
`VERSION` 之類的併發控制欄位），必須明確加進 `_NEVER_STAGED`，否則它會被當成內容。

## `VERSION` 不搬

那是活表列的樂觀鎖，不是內容。搬了會在套用時把教師編輯期間別處遞增的版本號蓋回去。

## 為什麼有 `LINK_PARENT_FK`

`ET_MATERIAL` / `ET_QUIZ` 不存「自己屬於哪個項目」——反過來是 `ET_ITEM.MATERIAL_ID` /
`QUIZ_ID` 指著它們。所以這兩種的父子連結欄位長在**父層**身上，套用時必須**先建它們、
再建項目**（`APPLY_ORDER` 已排好）。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from sqlalchemy import DateTime

from app.et.catalog.models import EtCourseTag
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.course.stage_rules import (
    ENTITY_CHAPTER,
    ENTITY_COURSE,
    ENTITY_COURSE_TAG,
    ENTITY_ITEM,
    ENTITY_MATERIAL,
    ENTITY_MATERIAL_DOC,
    ENTITY_MATERIAL_VIDEO,
    ENTITY_OPTION,
    ENTITY_QUESTION,
    ENTITY_QUIZ,
    ENTITY_SURVEY,
    ENTITY_SURVEY_OPTION,
    ENTITY_SURVEY_QUESTION,
)
from app.et.material.models import EtMaterial, EtMaterialDoc, EtMaterialVideo
from app.et.quiz.models import EtOption, EtQuestion, EtQuiz
from app.et.survey.models import EtSurvey, EtSurveyOption, EtSurveyQuestion

#: 本表有欄位指向父層 PK（常態）。
LINK_CHILD_FK: Final = "CHILD_FK"
#: **父層**有欄位指向本表 PK（只有 `MATERIAL` / `QUIZ`，見模組 docstring）。
LINK_PARENT_FK: Final = "PARENT_FK"

#: 稽核欄位——由套用端以操作者資訊重新填寫，不搬。
_AUDIT_FIELDS: Final[frozenset[str]] = frozenset(
    {"created_user", "created_date", "updated_user", "updated_date", "deleted"}
)
#: 不屬於「內容」的欄位。`sort_order` 在暫存區有專屬欄位；`version` 是活表列的樂觀鎖。
_NEVER_STAGED: Final[frozenset[str]] = frozenset({"sort_order", "version"})


@dataclass(frozen=True)
class EntitySpec:
    """一種內容實體的對照。

    Attributes:
        entity_type: `stage_rules.ENTITY_*` 之一。
        model: 對應的活表 model。
        pk: PK 的 Python 屬性名。
        parent_entity: 父層的 `ENTITY_*`；`None` ＝ 掛在課程下（章節與問卷）。
        link: `LINK_CHILD_FK` 或 `LINK_PARENT_FK`。
        fk: 連結欄位的 Python 屬性名——`CHILD_FK` 時長在本表、`PARENT_FK` 時長在父層。
    """

    entity_type: str
    model: type[Any]
    pk: str
    parent_entity: str | None
    link: str
    fk: str
    #: 明確白名單——**只有課程主檔用它**（#720）。`None` ＝ 照常推導。
    #:
    #: 🔴 推導的預設是「新欄位自動納入」，那對內容表是對的（新欄位多半是內容），
    #: 但對 `ET_COURSE` 是**反的**：它 13 個欄位裡只有 5 個是教師編的基本資料，
    #: 其餘是系統狀態（狀態、擁有者、邀請碼、首次發布、最近關閉、加急提醒旗標）。
    #: 自動納入會讓新加的系統欄位被當成內容搬進暫存、再寫回活表——最危險的是
    #: `status`，那等於讓「更新」繞過整條狀態機。
    #:
    #: ⚠️ 白名單會過期，所以 `test_課程主檔的每個欄位都要明確分類` 強制
    #: 「`ET_COURSE` 加欄位時必須二選一」。⛔ 不要為了讓那條變綠而把新欄位
    #: 隨手丟進 `COURSE_SYSTEM_FIELDS`。
    only_fields: tuple[str, ...] | None = None


#: 🔴 **順序即套用順序**：每一列被建立時，它依賴的對象都已經有活表 id。
#:
#: `MATERIAL` / `QUIZ` 排在 `ITEM` 之前，因為項目要填 `MATERIAL_ID` / `QUIZ_ID`
#: （`LINK_PARENT_FK`）。其餘一律父先於子。
#: 課程主檔中**不是**教師編輯之基本資料的欄位（#720）。
#:
#: 它與 `COURSE_PAYLOAD_FIELDS` 互補、合起來必須涵蓋 `ET_COURSE` 的全部欄位——由
#: `test_課程主檔的每個欄位都要明確分類` 強制。⚠️ 新增欄位時**必須二選一**，
#: 沒分類的症狀是教師改了卻不生效，而畫面上沒有任何訊息。
COURSE_SYSTEM_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "course_id",  # PK
        "status",  # 🔴 狀態機專屬——搬了會讓「更新」把狀態改回編輯開始那一刻的值
        "owner_id",  # 建立當下記錄，永久不可變更
        "invitation_code",  # 發布當下產生，之後沿用
        "first_published_at",  # 稽核用時間戳
        "closed_at",  # 最近一次關閉時間
        "urgent_remind_sent",  # 加急提醒的簿記旗標
        "version",  # 活表列的樂觀鎖
        *_AUDIT_FIELDS,
    }
)

#: 教師在基本資料區真正編輯的五個欄位。
COURSE_PAYLOAD_FIELDS: Final[tuple[str, ...]] = (
    "course_name",
    "description",
    "open_start_at",
    "open_end_at",
    "require_approval",
)

APPLY_ORDER: Final[tuple[EntitySpec, ...]] = (
    # 🔴 課程本體排第一：章節與問卷的 `COURSE_ID` 指向它。今天課程列必然已存在
    # （暫存只對已發布 / 已關閉開啟），所以這是「更新順序」而非「建立順序」；
    # 但排錯了會在日後若支援草稿暫存時靜默壞掉。
    EntitySpec(ENTITY_COURSE, EtCourse, "course_id", None, LINK_CHILD_FK, "course_id", COURSE_PAYLOAD_FIELDS),
    EntitySpec(ENTITY_COURSE_TAG, EtCourseTag, "course_tag_id", ENTITY_COURSE, LINK_CHILD_FK, "course_id"),
    EntitySpec(ENTITY_CHAPTER, EtChapter, "chapter_id", None, LINK_CHILD_FK, "course_id"),
    EntitySpec(ENTITY_MATERIAL, EtMaterial, "material_id", ENTITY_ITEM, LINK_PARENT_FK, "material_id"),
    EntitySpec(ENTITY_QUIZ, EtQuiz, "quiz_id", ENTITY_ITEM, LINK_PARENT_FK, "quiz_id"),
    EntitySpec(ENTITY_ITEM, EtItem, "item_id", ENTITY_CHAPTER, LINK_CHILD_FK, "chapter_id"),
    EntitySpec(ENTITY_MATERIAL_VIDEO, EtMaterialVideo, "video_id", ENTITY_MATERIAL, LINK_CHILD_FK, "material_id"),
    EntitySpec(ENTITY_MATERIAL_DOC, EtMaterialDoc, "mat_doc_id", ENTITY_MATERIAL, LINK_CHILD_FK, "material_id"),
    EntitySpec(ENTITY_QUESTION, EtQuestion, "question_id", ENTITY_QUIZ, LINK_CHILD_FK, "quiz_id"),
    EntitySpec(ENTITY_OPTION, EtOption, "option_id", ENTITY_QUESTION, LINK_CHILD_FK, "question_id"),
    EntitySpec(ENTITY_SURVEY, EtSurvey, "survey_id", None, LINK_CHILD_FK, "course_id"),
    EntitySpec(ENTITY_SURVEY_QUESTION, EtSurveyQuestion, "sq_id", ENTITY_SURVEY, LINK_CHILD_FK, "survey_id"),
    EntitySpec(ENTITY_SURVEY_OPTION, EtSurveyOption, "so_id", ENTITY_SURVEY_QUESTION, LINK_CHILD_FK, "sq_id"),
)

SPEC_BY_TYPE: Final[dict[str, EntitySpec]] = {s.entity_type: s for s in APPLY_ORDER}


def _parent_fk_fields_on(model: type[Any]) -> frozenset[str]:
    """長在 `model` 身上、指向其**子**實體 PK 的連結欄位（`ET_ITEM.material_id` / `quiz_id`）。

    這些不是內容、是結構連結，套用時由子節點的 id 決定，故不搬。
    """
    # `LINK_PARENT_FK` 的 spec 必定有 `parent_entity`（`APPLY_ORDER` 裡只有教材與測驗，
    # 兩者的父層都是項目），但型別上仍是 `str | None`——以區域變數收斂，不用 type: ignore。
    reverse = [s for s in APPLY_ORDER if s.link == LINK_PARENT_FK and s.parent_entity is not None]
    return frozenset(s.fk for s in reverse if SPEC_BY_TYPE[str(s.parent_entity)].model is model)


def datetime_fields(spec: EntitySpec) -> frozenset[str]:
    """該型別 payload 裡屬於 `datetime` 的欄位——**由 model 的欄位型別推導**。

    ⚠️ 手寫清單漏掉一個的症狀：序列化時爆 `TypeError`（看得見，還好）；但若有人為了
    讓它過而給 `json.dumps` 加上 `default=str`，就會變成**靜默寫入字串**——而那正是
    `to_payload` 的擋牌要防的事。
    """
    return frozenset(f for f in payload_fields(spec) if isinstance(spec.model.__mapper__.columns[f].type, DateTime))


def to_payload_dict(spec: EntitySpec, row: object) -> dict[str, Any]:
    """活表列 → payload 的 dict（`datetime` 轉 ISO 8601 字串）。

    🔴 **型別安全的來回**：`to_payload` 的 docstring 原本預言了「內容表日後加 `datetime`
    會當場爆」，並明寫「靜默塞個字串進去才是真正的問題（套用時寫回活表會變成錯的型別）」。
    #720 的課程本體帶來了兩個時間欄位，所以那個「日後」到了。

    ⛔ 擋牌擋的是**目的**（套用時型別不能錯），不是手段。所以這裡成對提供 `parse_payload`
    把它還原成 `datetime`——承重點從「`json.dumps` 會爆」轉移到「讀回來會還原」，
    由 `test_et_course_stage_payload_datetime.py` 守住。
    """
    dt = datetime_fields(spec)
    return {
        f: (v.isoformat() if f in dt and (v := getattr(row, f)) is not None else getattr(row, f))
        for f in payload_fields(spec)
    }


def parse_payload(entity_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """payload → 可直接使用的值（ISO 8601 字串還原成 `datetime`）。

    ⚠️ 少了這一步，`evaluate_publish` 會拿字串去跟 `datetime` 比較而 `TypeError`，
    或更糟——`stage_apply._upsert` 把字串寫進 `TIMESTAMPTZ` 欄位。

    ⚠️ 未知的 `entity_type` 原樣回傳：`stage_apply._validate_tree` 才是該報錯的地方，
    這裡多擋一次只會讓錯誤出現在比較難讀的位置。
    """
    spec = SPEC_BY_TYPE.get(entity_type)
    if spec is None:
        return dict(payload)
    dt = datetime_fields(spec)
    if not dt:
        return dict(payload)
    return {k: (datetime.fromisoformat(v) if k in dt and isinstance(v, str) else v) for k, v in payload.items()}


def payload_fields(spec: EntitySpec) -> tuple[str, ...]:
    """要搬進 / 搬出 `PAYLOAD` 的欄位（Python 屬性名，依 model 宣告順序）。

    ⚠️ **推導而非手寫**（理由見模組 docstring）。欄位集合＝全部欄位扣掉：
    PK、父子連結欄位、`SORT_ORDER`、`VERSION`、稽核欄位。
    """
    if spec.only_fields is not None:
        return spec.only_fields
    excluded = {spec.pk} | _AUDIT_FIELDS | _NEVER_STAGED | _parent_fk_fields_on(spec.model)
    if spec.link == LINK_CHILD_FK:
        excluded.add(spec.fk)
    return tuple(attr.key for attr in spec.model.__mapper__.column_attrs if attr.key not in excluded)
