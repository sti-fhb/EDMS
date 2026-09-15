"""排程三支信件之 params 與內文組法（US14 / #325）。

## 為何釘住 key 集合

params key 與範本佔位對不上時，平台 `_SafeFormatter` 拋 `KeyError` → 該封記為
`DP_EMAIL_LOG.STATUS='FAILED'`、`queued_count=0`，**且不外拋**。呼叫端看不出差別，
integration 若只查「有沒有列」也看不出差別——只有收件人會收到一封空信。

故三組 key 逐字對照 seed migration（`20260820_1700_c4e8f1a6d372`）的 `VARIABLES` 欄。
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.et.notify.schedule_mail import (
    MAX_NOT_STARTED_NAMES,
    NO_BASELINE,
    URGENT_REMIND_PARAM_KEYS,
    WEEKLY_REMIND_PARAM_KEYS,
    WEEKLY_REPORT_PARAM_KEYS,
    CourseReportLine,
    RemindCourse,
    build_urgent_remind_params,
    build_weekly_remind_params,
    build_weekly_report_params,
    format_delta,
    format_not_started,
)
from app.et.stats.rules import CourseStat

pytestmark = pytest.mark.unit


def _stat(**over) -> CourseStat:
    base = {
        "avg_progress_pct": Decimal("62.00"),
        "cnt_not_started": 3,
        "cnt_in_progress": 12,
        "cnt_completed": 20,
        "completion_rate": Decimal("57.14"),
        "cnt_enrolled": 35,
    }
    return CourseStat(**{**base, **over})


class TestParamKeys:
    """逐字對照 seed migration 的 `VARIABLES`。"""

    def test_weekly_report(self) -> None:
        assert WEEKLY_REPORT_PARAM_KEYS == {"RECIPIENT_NAME", "REPORT_SUMMARY", "REPORT_CSV_URL"}

    def test_weekly_remind(self) -> None:
        assert WEEKLY_REMIND_PARAM_KEYS == {"USER_NAME", "COURSE_LIST"}

    def test_urgent_remind(self) -> None:
        assert URGENT_REMIND_PARAM_KEYS == {"USER_NAME", "COURSE_NAME", "OPEN_END_AT", "COURSE_URL"}

    def test_組出的params恰好等於宣告的key(self) -> None:
        """宣告與實作分岔時，宣告會通過測試而實際寄出去的是空信。"""
        report = build_weekly_report_params(
            recipient_name="王老師",
            lines=[CourseReportLine("課程A", _stat(), Decimal("8.00"), 14, ["甲"])],
            csv_url="https://example.test/et/reports/weekly",
        )
        assert set(report) == WEEKLY_REPORT_PARAM_KEYS

        remind = build_weekly_remind_params(
            user_name="學員", courses=[RemindCourse(1, "課程A", datetime(2026, 10, 1, tzinfo=UTC))]
        )
        assert set(remind) == WEEKLY_REMIND_PARAM_KEYS

        urgent = build_urgent_remind_params(
            user_name="學員", course_id=1, course_name="課程A", open_end_at=datetime(2026, 10, 1, tzinfo=UTC)
        )
        assert set(urgent) == URGENT_REMIND_PARAM_KEYS

    def test_所有值皆為字串(self) -> None:
        """`_SafeFormatter` 吃 `str`；傳進 `Decimal` / `datetime` 會在渲染時才爆。"""
        params = build_weekly_report_params(
            recipient_name="王老師",
            lines=[CourseReportLine("課程A", _stat(), None, 3, [])],
            csv_url="https://example.test/x",
        )
        assert all(isinstance(v, str) for v in params.values())


class TestFormatDelta:
    def test_進步(self) -> None:
        assert format_delta(Decimal("8.00")) == "↑ 8.00"

    def test_退步(self) -> None:
        """新增章節會讓分母變大、平均進度下降——如實呈現，不藏。"""
        assert format_delta(Decimal("-15.00")) == "↓ 15.00"

    def test_持平(self) -> None:
        assert format_delta(Decimal("0.00")) == "持平"

    def test_無基準顯示破折號(self) -> None:
        """AC 5：首次統計顯示「—」。用 0 會讓「沒有基準」與「持平」變成同一件事。"""
        assert format_delta(None) == NO_BASELINE


class TestFormatNotStarted:
    def test_全員已開始顯示無(self) -> None:
        assert format_not_started([], 0) == "（無）"

    def test_未超過上限全列(self) -> None:
        assert format_not_started(["甲", "乙"], 2) == "甲、乙"

    def test_超過上限截斷並附總數(self) -> None:
        """掛「全體」標籤的課程開課第一週幾乎全是 0%，不設限會讓單封信塞進數百個姓名。"""
        names = [f"學員{i}" for i in range(50)]
        out = format_not_started(names, 50)
        assert out.count("、") == MAX_NOT_STARTED_NAMES - 1
        assert "…等共 50 人" in out
        assert "學員0" in out and "學員49" not in out


class TestReportSummary:
    def test_逐課一段且含六項指標(self) -> None:
        params = build_weekly_report_params(
            recipient_name="王老師",
            lines=[
                CourseReportLine("課程A", _stat(), Decimal("8.00"), 14, ["甲", "乙", "丙"]),
                CourseReportLine("課程B", _stat(cnt_not_started=0), None, 3, []),
            ],
            csv_url="https://example.test/x",
        )
        summary = params["REPORT_SUMMARY"]

        assert "・課程A" in summary and "・課程B" in summary
        assert "平均進度 62.00%" in summary
        assert "↑ 8.00" in summary and NO_BASELINE in summary
        assert "未開始 3 / 進行中 12 / 已完課 20（共 35 人）" in summary
        assert "完課率 57.14%｜距訖止 14 天" in summary
        assert "未開始名單：甲、乙、丙" in summary
        assert "未開始名單：（無）" in summary

    def test_無課程時摘要為空字串(self) -> None:
        """呼叫端不該寄出這封（空清單不寄信），但組法本身不得拋例外。"""
        params = build_weekly_report_params(recipient_name="王老師", lines=[], csv_url="https://example.test/x")
        assert params["REPORT_SUMMARY"] == ""


class TestWeeklyRemind:
    def test_列出所有未開始課程與截止時間(self) -> None:
        params = build_weekly_remind_params(
            user_name="學員",
            courses=[
                RemindCourse(7, "課程A", datetime(2026, 10, 1, 0, 0, tzinfo=UTC)),
                RemindCourse(8, "課程B", None),
            ],
        )
        course_list = params["COURSE_LIST"]

        assert "・課程A（截止 2026/10/01 08:00）" in course_list  # 台北時間
        assert "・課程B（截止 未設定）" in course_list
        assert "/et/courses/7/learn" in course_list and "/et/courses/8/learn" in course_list
