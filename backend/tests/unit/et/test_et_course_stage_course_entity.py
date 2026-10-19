"""課程本體與受訓對象進暫存區（#720）。

## 🔴 這一層與其他 11 種型別的預設**相反**

`stage_entities` 的 `payload_fields` 是**推導**的，預設「新欄位自動納入」。那個預設對
內容表是對的——`ET_QUESTION` 多一欄幾乎一定是題目的內容。

但 `ET_COURSE` 的 13 個欄位裡，只有 **5 個**是教師在基本資料區編輯的東西
（名稱、描述、起訖、需核可），其餘 8 個是**系統狀態**：PK、狀態、擁有者、邀請碼、
首次發布時間、最近關閉時間、加急提醒旗標、樂觀鎖。

⇒ 在課程主檔上，「新欄位自動納入」是**錯的預設**：日後加的欄位多半是系統狀態，自動
納入會讓它被當成教師編輯的內容搬進暫存、再寫回活表。所以課程本體改用**明確白名單**。

⛔ 這是對推導原則的**刻意例外**，理由如上，不是漏寫。⚠️ 代價是白名單會過期，所以
`test_課程主檔的每個欄位都要明確分類` 強制「`ET_COURSE` 加欄位時必須二選一」。
"""

import pytest

from app.et.catalog.models import EtCourseTag
from app.et.course.models import EtCourse
from app.et.course.stage_entities import (
    APPLY_ORDER,
    COURSE_SYSTEM_FIELDS,
    SPEC_BY_TYPE,
    payload_fields,
)
from app.et.course.stage_rules import ENTITY_CHAPTER, ENTITY_COURSE, ENTITY_COURSE_TAG

pytestmark = pytest.mark.unit


class TestCourseEntity:
    def test_課程本體在對照表裡(self) -> None:
        spec = SPEC_BY_TYPE[ENTITY_COURSE]

        assert spec.model is EtCourse
        assert spec.pk == "course_id"
        assert spec.parent_entity is None, "課程是樹根"

    def test_只搬教師編輯的五個基本資料欄位(self) -> None:
        """🔴 多搬一個系統欄位，套用時就會把它寫回活表。

        最危險的是 `status`——教師按「更新」會把課程狀態改回編輯開始那一刻的值，
        而那正好繞過整條狀態機（發布 / 關閉 / 再開課都是狀態轉換）。
        """
        assert set(payload_fields(SPEC_BY_TYPE[ENTITY_COURSE])) == {
            "course_name",
            "description",
            "open_start_at",
            "open_end_at",
            "require_approval",
        }

    def test_課程主檔的每個欄位都要明確分類(self) -> None:
        """🥇 **讓「`ET_COURSE` 加了欄位卻沒決定它算不算基本資料」變成紅燈。**

        白名單的代價就是會過期，而過期的方式是靜默的：新欄位既不在白名單、也沒人
        說它是系統欄位，於是它**不會被搬**——教師改了它、按「更新」卻沒生效，而
        畫面上沒有任何訊息。

        本條強制二選一：要嘛是基本資料（進 `payload_fields`），要嘛明確列為系統欄位。
        """
        staged = set(payload_fields(SPEC_BY_TYPE[ENTITY_COURSE]))
        all_columns = {a.key for a in EtCourse.__mapper__.column_attrs}
        unclassified = all_columns - staged - COURSE_SYSTEM_FIELDS

        assert not unclassified, (
            f"`ET_COURSE` 的這些欄位沒有被分類：{sorted(unclassified)}\n"
            "⛔ 不要為了讓這條變綠而隨手丟進 `COURSE_SYSTEM_FIELDS`——先問："
            "「教師會在基本資料區改它嗎？」會改就該進暫存。"
        )

    @pytest.mark.parametrize(
        "field",
        ["status", "owner_id", "invitation_code", "first_published_at", "closed_at", "urgent_remind_sent"],
    )
    def test_系統欄位不得被搬進暫存(self, field: str) -> None:
        """逐個點名——上一條驗「有沒有分類」，這條驗「分對邊」。

        只有上一條的話，把全部欄位都丟進 `COURSE_SYSTEM_FIELDS` 也會通過。
        """
        assert field not in payload_fields(SPEC_BY_TYPE[ENTITY_COURSE])

    def test_正向錨點_教師真的會改的欄位有搬(self) -> None:
        """少了它，把全部欄位都列為系統欄位也會讓上面幾條通過。"""
        fields = payload_fields(SPEC_BY_TYPE[ENTITY_COURSE])

        assert "course_name" in fields
        assert "open_end_at" in fields


class TestCourseTagEntity:
    def test_受訓對象掛在課程下(self) -> None:
        spec = SPEC_BY_TYPE[ENTITY_COURSE_TAG]

        assert spec.model is EtCourseTag
        assert spec.pk == "course_tag_id"
        assert spec.parent_entity == ENTITY_COURSE, "受訓對象的父層是課程本體"

    def test_搬的是配對的兩個標籤(self) -> None:
        """`course_id` 是父子連結欄位，由套用時的 id 映射決定，不搬。"""
        assert set(payload_fields(SPEC_BY_TYPE[ENTITY_COURSE_TAG])) == {"tag_id", "unit_tag_id"}


class TestApplyOrderWithCourse:
    def test_課程本體排在最前面(self) -> None:
        """🔴 **順序即套用順序**：章節與問卷的 `COURSE_ID` 指向課程，所以課程要先在。

        今天課程列必然已存在（暫存只對已發布 / 已關閉課程開啟），所以這不是「建立順序」
        而是「更新順序」；但排錯了會讓日後若支援草稿暫存時靜默壞掉。
        """
        order = [s.entity_type for s in APPLY_ORDER]

        assert order[0] == ENTITY_COURSE
        assert order.index(ENTITY_COURSE_TAG) < order.index(ENTITY_CHAPTER)
