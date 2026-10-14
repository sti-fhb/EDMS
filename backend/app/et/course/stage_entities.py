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

from dataclasses import dataclass
from typing import Any, Final

from app.et.course.models import EtChapter, EtItem
from app.et.course.stage_rules import (
    ENTITY_CHAPTER,
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


#: 🔴 **順序即套用順序**：每一列被建立時，它依賴的對象都已經有活表 id。
#:
#: `MATERIAL` / `QUIZ` 排在 `ITEM` 之前，因為項目要填 `MATERIAL_ID` / `QUIZ_ID`
#: （`LINK_PARENT_FK`）。其餘一律父先於子。
APPLY_ORDER: Final[tuple[EntitySpec, ...]] = (
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
    return frozenset(
        s.fk for s in APPLY_ORDER if s.link == LINK_PARENT_FK and SPEC_BY_TYPE[s.parent_entity].model is model
    )  # type: ignore[index]


def payload_fields(spec: EntitySpec) -> tuple[str, ...]:
    """要搬進 / 搬出 `PAYLOAD` 的欄位（Python 屬性名，依 model 宣告順序）。

    ⚠️ **推導而非手寫**（理由見模組 docstring）。欄位集合＝全部欄位扣掉：
    PK、父子連結欄位、`SORT_ORDER`、`VERSION`、稽核欄位。
    """
    excluded = {spec.pk} | _AUDIT_FIELDS | _NEVER_STAGED | _parent_fk_fields_on(spec.model)
    if spec.link == LINK_CHILD_FK:
        excluded.add(spec.fk)
    return tuple(attr.key for attr in spec.model.__mapper__.column_attrs if attr.key not in excluded)
