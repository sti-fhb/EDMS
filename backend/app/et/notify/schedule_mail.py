"""排程信件之參數組法（US14 / #325）：週報、每週未看提醒、截止前加急提醒。

三支範本皆由 `20260820_1700_c4e8f1a6d372` seed 進 `DP_NOTIFY_TEMPLATE`（`MODULE='ET'`）。

## params key 對不上是**靜默**失敗

平台 `_SafeFormatter` 在 key 與佔位對不上時拋 `KeyError`，`NotifyService` 將該封記為
`DP_EMAIL_LOG.STATUS='FAILED'`、`queued_count=0`，**且不外拋**。於是「寄出一封空信」
在呼叫端看起來與成功無異。故三組 key 各自以 `Final[frozenset]` 釘住並由 unit test
比對，改範本時會先讓測試紅。

## 三支各自的收件粒度

| 範本 | 一封信涵蓋 | 為何 |
|---|---|---|
| `WEEKLY_REPORT` | 一位收件人的**所有**課程 | `{REPORT_SUMMARY}` 是單一字串，範本不能迴圈 |
| `WEEKLY_REMIND` | 一位學員的**所有**未開始課程 | FR-ET-US14-05 明訂「一人一信彙整」 |
| `URGENT_REMIND` | **一門**課程 | 範本有 `{COURSE_NAME}` / `{OPEN_END_AT}`，本質是單課 |

三者都有 per-person 的 `{USER_NAME}` / `{RECIPIENT_NAME}`，而平台 `send_email` 對整批
收件人**只渲染一次**——故一律逐人一封（同 `CourseInviteMailer`）。
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Final, NamedTuple

from app.et.notify.course_invite import format_open_at, learn_link
from app.et.stats.rules import CourseStat

#: `DP_NOTIFY_TEMPLATE.TEMPLATE_CODE`（`MODULE='ET'`）。
TEMPLATE_WEEKLY_REPORT: Final = "WEEKLY_REPORT"
TEMPLATE_WEEKLY_REMIND: Final = "WEEKLY_REMIND"
TEMPLATE_URGENT_REMIND: Final = "URGENT_REMIND"

WEEKLY_REPORT_PARAM_KEYS: Final[frozenset[str]] = frozenset({"RECIPIENT_NAME", "REPORT_SUMMARY", "REPORT_CSV_URL"})
WEEKLY_REMIND_PARAM_KEYS: Final[frozenset[str]] = frozenset({"USER_NAME", "COURSE_LIST"})
URGENT_REMIND_PARAM_KEYS: Final[frozenset[str]] = frozenset({"USER_NAME", "COURSE_NAME", "OPEN_END_AT", "COURSE_URL"})

#: 週報之未開始名單最多列幾人（SA Q2 裁示 B）。
#:
#: 掛「全體」標籤的課程開課第一週幾乎全部是 0%，不設限會讓單封信塞進數百個姓名，
#: 管理者版再乘上課程數。完整名單一律看 CSV。
MAX_NOT_STARTED_NAMES: Final = 10

#: 無前次快照時「與上週比較」之呈現（AC 5）。**不可用 `0`**——那會讓「沒有比較基準」
#: 與「與上週持平」變成同一件事。
NO_BASELINE: Final = "—"


class CourseReportLine(NamedTuple):
    """週報中的一門課程。"""

    course_name: str
    stat: CourseStat
    delta: Decimal | None
    days_left: int
    not_started_names: Sequence[str]


def format_delta(delta: Decimal | None) -> str:
    """與上週比較之呈現：`↑ 8.00` / `↓ 15.00` / `持平` / `—`（無基準）。"""
    if delta is None:
        return NO_BASELINE
    if delta > 0:
        return f"↑ {delta}"
    if delta < 0:
        return f"↓ {-delta}"
    return "持平"


def format_not_started(names: Sequence[str], total: int) -> str:
    """未開始名單；超過 `MAX_NOT_STARTED_NAMES` 者截斷並附總數（SA Q2 裁示 B）。"""
    if total == 0:
        return "（無）"
    shown = list(names[:MAX_NOT_STARTED_NAMES])
    listed = "、".join(shown)
    if total > len(shown):
        return f"{listed} …等共 {total} 人（完整名單請由 CSV 下載）"
    return listed


def build_report_summary(lines: Sequence[CourseReportLine]) -> str:
    """組 `{REPORT_SUMMARY}`——逐課一段的多行純文字。

    平台渲染**內文時保留 LF**（僅主旨剝換行），故可安全使用換行排版
    （同 `build_digest_params` 的 `{COURSE_LIST}`）。
    """
    blocks = []
    for line in lines:
        stat = line.stat
        blocks.append(
            f"・{line.course_name}\n"
            f"  平均進度 {stat.avg_progress_pct}%（與上週 {format_delta(line.delta)}）\n"
            f"  未開始 {stat.cnt_not_started} / 進行中 {stat.cnt_in_progress} / 已完課 {stat.cnt_completed}"
            f"（共 {stat.cnt_enrolled} 人）\n"
            f"  完課率 {stat.completion_rate}%｜距訖止 {line.days_left} 天\n"
            f"  未開始名單：{format_not_started(line.not_started_names, stat.cnt_not_started)}"
        )
    return "\n\n".join(blocks)


def build_weekly_report_params(*, recipient_name: str, lines: Sequence[CourseReportLine], csv_url: str) -> dict:
    """組 `WEEKLY_REPORT` 之範本參數。

    Args:
        recipient_name: 收件人顯示名稱。**不可留空**——範本開頭為「{RECIPIENT_NAME} 您好：」。
        csv_url: 逐學員明細之下載連結（前端中繼路由；見 `reports/router`）。
    """
    return {
        "RECIPIENT_NAME": recipient_name,
        "REPORT_SUMMARY": build_report_summary(lines),
        "REPORT_CSV_URL": csv_url,
    }


class RemindCourse(NamedTuple):
    """每週未看提醒中的一門課程。"""

    course_id: int
    course_name: str
    open_end_at: datetime | None


def build_weekly_remind_params(*, user_name: str, courses: Sequence[RemindCourse]) -> dict:
    """組 `WEEKLY_REMIND` 之範本參數（一人一信，列出其所有未開始課程）。"""
    blocks = [
        f"・{c.course_name}（截止 {format_open_at(c.open_end_at)}）\n  {learn_link(c.course_id)}" for c in courses
    ]
    return {"USER_NAME": user_name, "COURSE_LIST": "\n\n".join(blocks)}


def build_urgent_remind_params(*, user_name: str, course_id: int, course_name: str, open_end_at) -> dict:
    """組 `URGENT_REMIND` 之範本參數（一門課一封）。"""
    return {
        "USER_NAME": user_name,
        "COURSE_NAME": course_name,
        "OPEN_END_AT": format_open_at(open_end_at),
        "COURSE_URL": learn_link(course_id),
    }
