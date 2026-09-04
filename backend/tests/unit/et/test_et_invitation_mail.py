"""課程邀請信之參數組法（US8 / #273）。

## 為何這支測試存在

平台 `NotifyService` 的渲染失敗是**靜默的**：params 少一個範本要的 key →
`_SafeFormatter` 拋 `KeyError` → 該批寫成 `DP_EMAIL_LOG.STATUS='FAILED'`、
`queued_count=0`，但**不外拋**，呼叫方一切正常。本檔把 params 的 key 集合釘死在
已 seed 之範本佔位上，讓「對不上」在單元測試就變成紅燈，而不是使用者收不到信。

> 真正的把關仍是 integration（斷言 `STATUS='PENDING'` 且內文確實代入課程名稱）——
> 本檔只讓失敗提早、且指得出是哪一個 key。
"""

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.et.course.models import EtCourse
from app.et.notify.course_invite import (
    COURSE_INVITE_PARAM_KEYS,
    DIGEST_PARAM_KEYS,
    build_course_invite_params,
    build_digest_params,
    format_open_at,
    invite_link,
    learn_link,
    preview_invite_link,
)

pytestmark = pytest.mark.unit

# 2026-04-15 09:00 台北 == 01:00 UTC；本檔多處用它驗時區換算
_UTC_0100 = datetime(2026, 4, 15, 1, 0, tzinfo=timezone.utc)
_UTC_0900 = datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc)


def _course(course_id: int, name: str, start=_UTC_0100, end=_UTC_0900) -> EtCourse:
    return EtCourse(course_id=course_id, course_name=name, status="PUBLISHED", open_start_at=start, open_end_at=end)


class TestParamKeys:
    """key 必須逐字對齊 `DP_NOTIFY_TEMPLATE`（`MODULE='ET'`）之佔位。"""

    def test_課程邀請信七個佔位一個不多一個不少(self) -> None:
        """對齊 `COURSE_INVITE` 之 VARIABLES 欄位（見 et_seed_templates_params_into_dp）。"""
        assert COURSE_INVITE_PARAM_KEYS == frozenset(
            {
                "USER_NAME",
                "TEACHER_NAME",
                "COURSE_NAME",
                "OPEN_START_AT",
                "OPEN_END_AT",
                "COURSE_URL",
                "INVITATION_CODE",
            }
        )

    def test_彙整信兩個佔位(self) -> None:
        assert DIGEST_PARAM_KEYS == frozenset({"USER_NAME", "COURSE_LIST"})

    def test_build_course_invite_params_回傳的_key_與常數一致(self) -> None:
        params = build_course_invite_params(
            user_name="王小明",
            teacher_name="李老師",
            course=_course(12, "採血作業新進人員訓練"),
            course_url="https://example.test/et/courses/12/learn",
            invitation_code="83052617",
        )
        assert set(params) == COURSE_INVITE_PARAM_KEYS

    def test_build_digest_params_回傳的_key_與常數一致(self) -> None:
        params = build_digest_params(user_name="王小明", courses=[_course(12, "採血作業")])
        assert set(params) == DIGEST_PARAM_KEYS

    def test_所有值皆為字串(self) -> None:
        """`_SafeFormatter` 會 `str()` 代入值，但傳非字串會讓 key 對照失去意義。"""
        params = build_course_invite_params(
            user_name="王小明",
            teacher_name="李老師",
            course=_course(12, "採血作業"),
            course_url="https://example.test/x",
            invitation_code="83052617",
        )
        assert all(isinstance(v, str) for v in params.values())


class TestFormatOpenAt:
    """信件時間必須與教師在 ET02 看到的一致（台北時間）。"""

    def test_轉為台北時間而非直接印_utc(self) -> None:
        """前端送 `toISOString()`（UTC）、UI 以本地時區顯示。

        直接 `strftime` UTC 值會讓信件寫出比教師設定**早 8 小時**的閱課期間——
        學員據此以為課程已開放或已截止。
        """
        assert format_open_at(_UTC_0100) == "2026/04/15 09:00"

    def test_跨日邊界正確進位(self) -> None:
        """UTC 2026-04-14 17:00 == 台北 2026-04-15 01:00（跨日）。"""
        assert format_open_at(datetime(2026, 4, 14, 17, 0, tzinfo=timezone.utc)) == "2026/04/15 01:00"

    def test_未設定回可讀字樣而非空字串(self) -> None:
        """欄位 DB 端可為 NULL；空字串會讓信件出現「閱課期間： ～ 」這種殘句。"""
        assert format_open_at(None) == "未設定"

    def test_格式與前端_formatDateTime_一致(self) -> None:
        """`frontend/src/utils/date.ts` 之 `formatDateTime` 為 `YYYY/MM/DD HH:mm`。"""
        assert format_open_at(_UTC_0900) == "2026/07/31 17:00"


class TestLinks:
    """連結一律由 `settings.FRONTEND_BASE_URL` 組出，且容忍設定值尾端斜線。"""

    def test_學習連結指向_et05_學習頁(self) -> None:
        assert learn_link(12).endswith("/et/courses/12/learn")

    def test_邀請連結帶明文_token(self) -> None:
        assert invite_link("abc123").endswith("/et/invite?token=abc123")

    def test_連結以設定之_base_url_起頭(self) -> None:
        base = settings.FRONTEND_BASE_URL.rstrip("/")
        assert learn_link(12).startswith(base)
        assert invite_link("abc123").startswith(base)

    def test_base_url_尾端斜線不會產生雙斜線(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://edms.example/")
        assert learn_link(7) == "https://edms.example/et/courses/7/learn"

    def test_預覽連結不含真實_token(self) -> None:
        """預覽當下尚未產生 token（每位收件人各自獨立），不可出現可用的連結。"""
        preview = preview_invite_link()
        assert preview.endswith("/et/invite?token=…")


class TestDigestCourseList:
    """`{COURSE_LIST}` 為多行純文字——內文渲染保留 LF（主旨才剝換行）。"""

    def test_每門課一段_含名稱_期間與連結(self) -> None:
        params = build_digest_params(
            user_name="王小明",
            courses=[_course(12, "採血作業新進人員訓練"), _course(34, "感染管制年度訓練")],
        )
        course_list = params["COURSE_LIST"]
        assert "採血作業新進人員訓練" in course_list
        assert "感染管制年度訓練" in course_list
        assert course_list.count("/et/courses/") == 2
        assert "2026/04/15 09:00" in course_list

    def test_課程順序與傳入順序一致(self) -> None:
        params = build_digest_params(user_name="王小明", courses=[_course(1, "甲課程"), _course(2, "乙課程")])
        course_list = params["COURSE_LIST"]
        assert course_list.index("甲課程") < course_list.index("乙課程")

    def test_單一課程不留尾端空行(self) -> None:
        params = build_digest_params(user_name="王小明", courses=[_course(1, "甲課程")])
        assert params["COURSE_LIST"] == params["COURSE_LIST"].strip()
