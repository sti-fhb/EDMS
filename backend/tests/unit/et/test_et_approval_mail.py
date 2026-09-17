"""核可通過通知信之參數組法（US16 / #352）。

params 的 key 若與範本佔位對不上，平台 `_SafeFormatter` 會拋 `KeyError` → 該批寫成
`DP_EMAIL_LOG.STATUS='FAILED'`、`queued_count=0`，**且不外拋**——呼叫方看起來一切正常，
只是沒有人收到信。本檔把 key 集合釘死，比照 `test_et_course_update_mail.py`。

`APPROVAL_PASSED` 的 seed 於 `c4e8f1a6d372`，`VARIABLES` 欄為
`USER_NAME,COURSE_NAME,APPROVED_BY_NAME,APPROVED_AT`。**本 issue 是它的第一個引用點**
——在此之前全 codebase 沒有任何地方寄過這個範本，所以沒有既有行為可以參照，錯了也
不會有別的測試變紅。
"""

from datetime import datetime, timezone

import pytest

from app.et.course.models import EtCourse
from app.et.notify.approval_passed import (
    APPROVAL_PASSED_PARAM_KEYS,
    TEMPLATE_APPROVAL_PASSED,
    build_approval_passed_params,
)

pytestmark = pytest.mark.unit

#: UTC 01:00 = 台北 09:00（跨日界線，換算寫反會看得出來）。
_UTC_0100 = datetime(2026, 5, 19, 1, 0, tzinfo=timezone.utc)


def _course(course_id: int = 7, name: str = "採血作業訓練") -> EtCourse:
    return EtCourse(course_id=course_id, course_name=name, status="PUBLISHED")


class TestTemplateParamKeys:
    def test_範本代碼為APPROVAL_PASSED(self) -> None:
        assert TEMPLATE_APPROVAL_PASSED == "APPROVAL_PASSED"

    def test_四個佔位一個不多一個不少(self) -> None:
        """逐字對齊 `c4e8f1a6d372` seed 的 `VARIABLES` 與
        `contracts/ext-et-email-server.md` §APPROVAL_PASSED 的變數表。
        """
        assert APPROVAL_PASSED_PARAM_KEYS == frozenset({"USER_NAME", "COURSE_NAME", "APPROVED_BY_NAME", "APPROVED_AT"})

    def test_build回傳的key與常數一致(self) -> None:
        params = build_approval_passed_params(
            user_name="陳小明", course=_course(), approved_by_name="王主任", approved_at=_UTC_0100
        )
        assert set(params) == set(APPROVAL_PASSED_PARAM_KEYS)


class TestBuildParams:
    def test_帶入學員與課程與核可人(self) -> None:
        params = build_approval_passed_params(
            user_name="陳小明", course=_course(name="血品安全"), approved_by_name="王主任", approved_at=_UTC_0100
        )
        assert params["USER_NAME"] == "陳小明"
        assert params["COURSE_NAME"] == "血品安全"
        assert params["APPROVED_BY_NAME"] == "王主任"

    def test_核可時間換算台北時區(self) -> None:
        """🔴 直接輸出 UTC 會讓信裡的核可時間比教師在 ET03 看到的**早 8 小時**。

        沿用 `course_invite.format_open_at` 的同一支換算與同一個格式
        （`YYYY/MM/DD HH:mm`，對齊前端 `utils/date.ts`），使教師在畫面上看到的與學員
        信裡讀到的是同一串字。
        """
        params = build_approval_passed_params(
            user_name="陳小明", course=_course(), approved_by_name="王主任", approved_at=_UTC_0100
        )
        assert params["APPROVED_AT"] == "2026/05/19 09:00"

    def test_所有值皆為字串(self) -> None:
        """平台 `_SafeFormatter` 直接把值代入字串範本；非字串會渲染出 repr。

        `approved_at` 是 `datetime`，這一格擋的就是「忘了格式化直接塞進去」。
        """
        params = build_approval_passed_params(
            user_name="陳小明", course=_course(), approved_by_name="王主任", approved_at=_UTC_0100
        )
        assert all(isinstance(v, str) for v in params.values())

    def test_核可人姓名查無時不留空字串(self) -> None:
        """核可人帳號查無姓名（已刪）時內文會變成「已由  核可通過」。

        與 `COURSE_INVITE` 的 `{TEACHER_NAME}` 同一個問題，取同樣保守的一側：
        呼叫端傳空字串時以「系統管理者」替代，不讓信件出現殘句。
        """
        params = build_approval_passed_params(
            user_name="陳小明", course=_course(), approved_by_name="", approved_at=_UTC_0100
        )
        assert params["APPROVED_BY_NAME"] == "系統管理者"
