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
"""

from datetime import datetime, timezone

import pytest

from app.et.course.stage_entities import SPEC_BY_TYPE, datetime_fields, parse_payload, to_payload_dict
from app.et.course.stage_rules import ENTITY_CHAPTER, ENTITY_COURSE

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
