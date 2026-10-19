"""payload 的 `datetime` 來回（#720）。

## 🔴 前 11 種型別的 payload 全是 JSON 原生型別，課程打破了這個前提

`ET_COURSE.OPEN_START_AT` / `OPEN_END_AT` 是 `datetime`，而 payload 走 `json.dumps`。

`to_payload` 的 docstring 原本就預言了這件事，並**刻意讓它爆**：

> `json.dumps` 在遇到不可序列化的型別時會 `TypeError`——那是刻意不接住的。…
> **靜默塞個字串進去才是真正的問題**（套用時寫回活表會變成錯的型別）。

⛔ 那道擋牌擋的是**目的**（套用時寫回活表的型別不能錯），不是手段。所以這裡做的是
**型別安全的來回**——序列化成 ISO 8601、讀回來還原成 `datetime`——而不是把它改成
字串了事。

⚠️ 承重點因此從「`json.dumps` 會爆」轉移到「`parse_payload` 會還原」。本檔就是那個
承重點的測試：少了還原，`evaluate_publish` 會拿字串去跟 `datetime` 比較而 `TypeError`，
或更糟——`_upsert` 把字串寫進 `TIMESTAMPTZ` 欄位。

## 🔴 序列化有三道門，不是一道

`seed_from_live` 走 `to_payload`（活表列 → JSON）只是其中一道。**從請求寫入**另有兩道：
`stage_writer.append`（新增節點）與 `update_payload`（改欄位）。#720 之前兩者裸呼叫
`json.dumps` 完全沒事，因為 11 種內容型別的 payload 全是 JSON 原生型別。

⇒ 只修 `to_payload` 的症狀是：seed 得起來，但教師一改基本資料就 500。
"""

import json
from datetime import datetime, timezone

import pytest

from app.et.course.stage_entities import (
    SPEC_BY_TYPE,
    datetime_fields,
    dumps_payload,
    parse_payload,
    to_payload_dict,
)
from app.et.course.stage_rules import ENTITY_CHAPTER, ENTITY_COURSE, ENTITY_QUIZ, RETEST_PAYLOAD_KEY

pytestmark = pytest.mark.unit

_AWARE = datetime(2030, 3, 1, 9, 30, tzinfo=timezone.utc)


class TestDatetimeFields:
    def test_由_model_推導而非手寫(self) -> None:
        """⚠️ 推導，不是清單——`ET_COURSE` 日後多一個時間欄位會自動納入。

        手寫清單漏掉一個的症狀：那一欄序列化時爆 `TypeError`（看得見，還好），
        但若有人為了讓它過而加了 `default=str`，就會變成靜默寫入字串。
        """
        assert datetime_fields(SPEC_BY_TYPE[ENTITY_COURSE]) == frozenset({"open_start_at", "open_end_at"})

    def test_沒有時間欄位的型別回空集合(self) -> None:
        assert datetime_fields(SPEC_BY_TYPE[ENTITY_CHAPTER]) == frozenset()


class TestRoundTrip:
    def test_datetime_來回之後仍是_datetime(self) -> None:
        """🥇 本檔的核心。字串進了 `CourseSnapshot` 會讓檢核拿它跟 `datetime` 比較。"""
        raw = to_payload_dict(SPEC_BY_TYPE[ENTITY_COURSE], _fake_course(open_start_at=_AWARE))

        back = parse_payload(ENTITY_COURSE, raw)

        assert back["open_start_at"] == _AWARE
        assert isinstance(back["open_start_at"], datetime)

    def test_時區不會在來回中遺失(self) -> None:
        """⚠️ naive 的 `datetime` 與 aware 的比較會 `TypeError`，而全專案的時間一律 aware。"""
        raw = to_payload_dict(SPEC_BY_TYPE[ENTITY_COURSE], _fake_course(open_start_at=_AWARE))

        assert parse_payload(ENTITY_COURSE, raw)["open_start_at"].tzinfo is not None

    def test_None_仍然是_None(self) -> None:
        """教師清空訖止時間——那正是檢核要擋下的情形，不能在來回中變成別的東西。"""
        raw = to_payload_dict(SPEC_BY_TYPE[ENTITY_COURSE], _fake_course(open_end_at=None))

        assert parse_payload(ENTITY_COURSE, raw)["open_end_at"] is None

    def test_非時間欄位原樣帶過(self) -> None:
        """正向錨點：少了它，把 `parse_payload` 寫成「只回時間欄位」也會讓上面幾條通過。"""
        back = parse_payload(ENTITY_COURSE, to_payload_dict(SPEC_BY_TYPE[ENTITY_COURSE], _fake_course()))

        assert back["course_name"] == "課程甲"
        assert back["require_approval"] is False

    def test_沒有時間欄位的型別不被動到(self) -> None:
        payload = {"chapter_name": "第一章"}

        assert parse_payload(ENTITY_CHAPTER, payload) == payload


class TestDumpsPayload:
    """**三道門共用同一個編碼器**——所以它要能吃「請求送來的 dict」，不只是活表列。"""

    def test_datetime_編成_ISO_字串(self) -> None:
        raw = json.loads(dumps_payload(ENTITY_COURSE, {"open_start_at": _AWARE}))

        assert raw["open_start_at"] == _AWARE.isoformat()

    def test_與_parse_payload_成對(self) -> None:
        """🥇 **本組的核心契約：寫進去什麼，讀回來就是什麼。**

        經過真正的 JSON 字串來回（而非只到 dict）——資料庫 `PAYLOAD` 欄位存的就是那個字串。
        """
        original = {
            "course_name": "課程甲",
            "description": None,
            "open_start_at": _AWARE,
            "open_end_at": None,
            "require_approval": False,
        }

        back = parse_payload(ENTITY_COURSE, json.loads(dumps_payload(ENTITY_COURSE, original)))

        assert back == original

    def test_沒有時間欄位的型別照原樣編碼(self) -> None:
        """正向錨點：少了它，把編碼器寫成「只輸出時間欄位」也會讓上面兩條通過。"""
        assert json.loads(dumps_payload(ENTITY_CHAPTER, {"chapter_name": "第一章"})) == {"chapter_name": "第一章"}

    def test_非欄位的旗標原樣帶過(self) -> None:
        """⚠️ `update_payload` 會把工作階段旗標併回 payload 再送進編碼器（見其「保留非欄位
        的旗標」段）。編碼器若只認得 `payload_fields` 就會把它吃掉——那正是 2026-10-18
        code review HIGH 1 修掉的靜默失效，不要在這一層復活它。
        """
        raw = json.loads(dumps_payload(ENTITY_QUIZ, {"quiz_name": "小考", RETEST_PAYLOAD_KEY: True}))

        assert raw[RETEST_PAYLOAD_KEY] is True

    def test_未宣告為時間欄位的_datetime_要當場爆(self) -> None:
        """⛔ **不要為了讓它過而加 `default=str`。**

        `datetime` 出現在沒宣告成時間欄位的 key 上，代表 `payload_fields` 與實際送的東西
        對不上。此時靜默轉成字串，`parse_payload` 不會還原它，套用時就把字串寫進活表
        ——`to_payload` 的擋牌從 #631 起擋的就是這件事。爆掉是正確行為。
        """
        with pytest.raises(TypeError):
            dumps_payload(ENTITY_CHAPTER, {"chapter_name": _AWARE})


class _Fake:
    pass


def _fake_course(**over):
    row = _Fake()
    values = {
        "course_name": "課程甲",
        "description": None,
        "open_start_at": _AWARE,
        "open_end_at": _AWARE,
        "require_approval": False,
    } | over
    for k, v in values.items():
        setattr(row, k, v)
    return row
