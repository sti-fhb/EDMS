"""暫存區 ↔ 11 張內容表的對照（#631）。

本檔守的是**結構性的**東西：對照表有沒有涵蓋全部內容表、推導出的欄位集合有沒有
把「內容」與「非內容」分對邊。

⭐ 這些斷言多半不是在驗演算法，而是在**讓日後的遺漏變成紅燈**——內容表加欄位、
新增內容型別、改父子關係，都會在這裡爆出來。
"""

import pytest

from app.et.course.models import EtChapter, EtItem
from app.et.course.stage_entities import (
    APPLY_ORDER,
    LINK_PARENT_FK,
    SPEC_BY_TYPE,
    payload_fields,
)
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
    RETEST_PAYLOAD_KEY,
)

pytestmark = pytest.mark.unit

_ALL_ENTITY_TYPES = {
    ENTITY_CHAPTER,
    ENTITY_ITEM,
    ENTITY_MATERIAL,
    ENTITY_MATERIAL_VIDEO,
    ENTITY_MATERIAL_DOC,
    ENTITY_QUIZ,
    ENTITY_QUESTION,
    ENTITY_OPTION,
    ENTITY_SURVEY,
    ENTITY_SURVEY_QUESTION,
    ENTITY_SURVEY_OPTION,
}


class TestCoverage:
    def test_十一種內容型別全部都有對照(self) -> None:
        """🔴 少一種的症狀是**靜默**的：該型別在 seed 與套用時被略過，教師編了、
        按更新沒生效，而且不會有任何錯誤訊息。"""
        assert {s.entity_type for s in APPLY_ORDER} == _ALL_ENTITY_TYPES

    def test_沒有重複的型別(self) -> None:
        assert len(APPLY_ORDER) == len(SPEC_BY_TYPE) == len(_ALL_ENTITY_TYPES)


class TestApplyOrder:
    def test_每一列的父層都排在它前面(self) -> None:
        """套用時每建一列，它依賴的對象都必須已經有活表 id。"""
        seen: set[str] = set()
        for spec in APPLY_ORDER:
            if spec.parent_entity is not None and spec.link != LINK_PARENT_FK:
                assert spec.parent_entity in seen, f"{spec.entity_type} 的父層 {spec.parent_entity} 排在它後面"
            seen.add(spec.entity_type)

    def test_教材與測驗排在項目之前(self) -> None:
        """🔴 `ET_ITEM.MATERIAL_ID` / `QUIZ_ID` 指著它們（`LINK_PARENT_FK`），
        所以項目要填那兩欄就得先有它們的 id。

        這是本對照表唯一一處父子方向相反的地方，排錯了會在套用時撞 NOT NULL。
        """
        order = [s.entity_type for s in APPLY_ORDER]

        assert order.index(ENTITY_MATERIAL) < order.index(ENTITY_ITEM)
        assert order.index(ENTITY_QUIZ) < order.index(ENTITY_ITEM)


class TestPayloadFields:
    def test_不搬_pk_排序_樂觀鎖與稽核欄位(self) -> None:
        for spec in APPLY_ORDER:
            fields = set(payload_fields(spec))
            assert spec.pk not in fields, f"{spec.entity_type} 搬了 PK"
            assert "sort_order" not in fields, f"{spec.entity_type} 搬了 sort_order（暫存區有專屬欄位）"
            assert "version" not in fields, f"{spec.entity_type} 搬了 version（那是活表的樂觀鎖）"
            assert not fields & {"created_user", "created_date", "updated_user", "updated_date", "deleted"}

    def test_不搬父子連結欄位(self) -> None:
        """結構由 `PARENT_STAGE_ID` 表達，連結欄位在套用時才由 id 映射決定。"""
        assert "chapter_id" not in payload_fields(SPEC_BY_TYPE[ENTITY_ITEM])
        assert "material_id" not in payload_fields(SPEC_BY_TYPE[ENTITY_MATERIAL_VIDEO])
        assert "survey_id" not in payload_fields(SPEC_BY_TYPE[ENTITY_SURVEY_QUESTION])

    def test_項目不搬指向教材與測驗的兩個欄位(self) -> None:
        """🔴 `LINK_PARENT_FK` 的反向連結也不是內容。

        搬了的話，套用時會把**暫存期間記下的舊 id** 寫回活表——對新增的教材那是個
        還不存在的 id，對既有的則會蓋掉正確值。
        """
        fields = payload_fields(SPEC_BY_TYPE[ENTITY_ITEM])

        assert "material_id" not in fields
        assert "quiz_id" not in fields

    def test_每一種型別都至少搬一個欄位(self) -> None:
        """全部被排除代表對照寫錯了——那種實體搬過去會是一個空殼。"""
        for spec in APPLY_ORDER:
            assert payload_fields(spec), f"{spec.entity_type} 沒有任何 payload 欄位"

    @pytest.mark.parametrize(
        ("entity_type", "expected"),
        [
            (ENTITY_CHAPTER, ("chapter_name",)),
            (ENTITY_ITEM, ("item_type",)),
            (ENTITY_MATERIAL, ("material_name", "description_html")),
            (ENTITY_MATERIAL_VIDEO, ("file_path", "file_name", "duration_sec", "file_size_bytes")),
            (ENTITY_MATERIAL_DOC, ("doc_id",)),
            (ENTITY_QUIZ, ("quiz_name", "description", "pass_score", "time_limit_min", "max_retry")),
            (ENTITY_QUESTION, ("question_type", "stem", "points")),
            (ENTITY_OPTION, ("option_text", "is_correct")),
            (ENTITY_SURVEY, ("survey_name", "is_active")),
            (ENTITY_SURVEY_QUESTION, ("question_type", "stem")),
            (ENTITY_SURVEY_OPTION, ("option_text",)),
        ],
    )
    def test_推導結果逐型別釘住(self, entity_type: str, expected: tuple[str, ...]) -> None:
        """⚠️ 本條**會因為內容表加欄位而紅**——那是刻意的。

        紅的時候要做的判斷是：那個新欄位**是不是內容**？
        - 是 ⇒ 把它加進這裡的預期值（推導已自動納入，不必改程式）
        - 不是（例如另一個併發控制欄位）⇒ 加進 `stage_entities._NEVER_STAGED`

        🔴 兩者都不做而直接刪掉本條，等於讓那個欄位的版本化行為不再有任何人檢查過。
        """
        assert payload_fields(SPEC_BY_TYPE[entity_type]) == expected

    def test_配分欄位有被搬(self) -> None:
        """正向錨點：`POINTS` 是 issue 列的四個症狀之一（改配分後總分不再是 100）。

        少了它，暫存期間改的配分在套用時會被寫回舊值——而「推導」的那些泛用斷言
        不會發現，因為它們只說「不搬什麼」。
        """
        assert "points" in payload_fields(SPEC_BY_TYPE[ENTITY_QUESTION])

    def test_連結欄位確實長在宣告的那張表上(self) -> None:
        """對照表自己說 `fk` 長在哪，這條去 model 查證。

        寫錯了的症狀是套用時 `setattr` 到一個不存在的屬性——那會爆，但要等到有人
        真的按下「更新」而且暫存區剛好有那種實體。
        """
        for spec in APPLY_ORDER:
            holder = spec.model if spec.link != LINK_PARENT_FK else SPEC_BY_TYPE[spec.parent_entity].model
            assert hasattr(holder, spec.fk), f"{spec.entity_type} 的 fk={spec.fk} 不在 {holder.__name__} 上"

    def test_反向連結的持有者是項目(self) -> None:
        """釘住「只有教材與測驗是反向的」——多一個的話 `_parent_fk_fields_on` 的
        排除邏輯會悄悄改變別張表的 payload。"""
        reverse = [s for s in APPLY_ORDER if s.link == LINK_PARENT_FK]

        assert {s.entity_type for s in reverse} == {ENTITY_MATERIAL, ENTITY_QUIZ}
        assert all(SPEC_BY_TYPE[s.parent_entity].model is EtItem for s in reverse)

    def test_章節掛在課程下(self) -> None:
        assert SPEC_BY_TYPE[ENTITY_CHAPTER].parent_entity is None
        assert SPEC_BY_TYPE[ENTITY_CHAPTER].model is EtChapter
        assert SPEC_BY_TYPE[ENTITY_SURVEY].parent_entity is None


class TestNonFieldFlags:
    """寄在 payload 上、但**不是內容欄位**的旗標（目前只有 #361 的要求重測）。

    ## 這一層在守什麼

    `stage_apply._upsert` 寫活表時只取 `payload_fields(spec)` 列出的 key
    （`{f: node.payload[f] for f in payload_fields(spec) if f in node.payload}`），
    所以非欄位的旗標會被自動忽略。**旗標一旦與某個內容欄位同名，就會被當成內容寫進活表。**

    🔴 `stage_rules.RETEST_PAYLOAD_KEY` 的註解原本就宣稱「由本測試實際比對，不靠人記得」
    ——而 2026-10-19 跑 #631 的 close 盤點時發現**那條測試從來沒有被寫出來**。註解在說謊，
    而它的作用正是讓下一個人不去查。

    ⚠️ 既有的 `test_payload_只含內容欄位`（integration）擋不到這件事：它的前置只跑
    `seed_from_live`、從不勾重測，旗標在它的母體裡**永遠不出現**。那是觸發條件被 harness
    預設排除，不是斷言寫錯。
    """

    def test_重測旗標不得與_ET_QUIZ_的欄位同名(self) -> None:
        assert RETEST_PAYLOAD_KEY not in payload_fields(SPEC_BY_TYPE[ENTITY_QUIZ]), (
            f"{RETEST_PAYLOAD_KEY} 與 ET_QUIZ 的內容欄位同名 ⇒ 按「更新」時會被當成內容寫進活表"
        )

    def test_重測旗標不得與任何型別的欄位同名(self) -> None:
        """旗標今天只掛在 QUIZ 節點上，但哪天被移到別層（例如改掛 QUESTION）時，
        上一條就看不到了。這一條把 11 種型別一次掃完，**移動旗標不需要記得回來改測試**。"""
        collisions = [s.entity_type for s in APPLY_ORDER if RETEST_PAYLOAD_KEY in payload_fields(s)]

        assert not collisions, f"{RETEST_PAYLOAD_KEY} 與這些型別的內容欄位同名：{collisions}"

    def test_正向錨點_真的欄位查得到(self) -> None:
        """🔴 少了它，`payload_fields` 哪天回空集合，上面兩條會**恆真**地全綠。

        「不該出現」的斷言要配一條「該出現」且用**同一個查詢方式**——否則它驗的不是
        「沒有撞名」，而是「這個函式還有沒有在回東西」。
        """
        assert "quiz_name" in payload_fields(SPEC_BY_TYPE[ENTITY_QUIZ])
