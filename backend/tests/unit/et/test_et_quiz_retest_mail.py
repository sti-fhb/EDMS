"""測驗變更需重新測驗通知信之參數組法（#361）。

params 的 key 若與範本佔位對不上，平台 `_SafeFormatter` 會拋 `KeyError` → 該批寫成
`DP_EMAIL_LOG.STATUS='FAILED'`、`queued_count=0`，**且不外拋**——呼叫方看起來一切正常，
只是沒有人收到信。本檔把 key 集合釘死，比照 `test_et_course_update_mail.py`。
"""

import pytest

from app.core.config import settings
from app.et.course.models import EtCourse
from app.et.notify.quiz_retest_required import (
    QUIZ_RETEST_REQUIRED_PARAM_KEYS,
    TEMPLATE_QUIZ_RETEST_REQUIRED,
    build_quiz_retest_params,
)

pytestmark = pytest.mark.unit


def _course(course_id: int = 7, name: str = "輸血作業標準流程教育訓練") -> EtCourse:
    return EtCourse(course_id=course_id, course_name=name, status="PUBLISHED")


def _params(**over):
    base = {
        "user_name": "陳小明",
        "course": _course(),
        "quiz_name": "輸血作業概念測驗",
        "course_url": f"{settings.FRONTEND_BASE_URL.rstrip('/')}/et/courses/7/learn",
    }
    return build_quiz_retest_params(**{**base, **over})


class TestTemplateParamKeys:
    def test_範本代碼為QUIZ_RETEST_REQUIRED(self) -> None:
        """⚠️ 須與 `20260921_1500_a7c31f5e9d24` 種入的 `TEMPLATE_CODE` 逐字相同。

        對不上時 `notify` 查不到範本，同樣是「不外拋、沒有人收到信」。
        """
        assert TEMPLATE_QUIZ_RETEST_REQUIRED == "QUIZ_RETEST_REQUIRED"

    def test_四個佔位一個不多一個不少(self) -> None:
        """對齊 migration 中 `VARIABLES` 欄位的四個變數名。"""
        assert QUIZ_RETEST_REQUIRED_PARAM_KEYS == frozenset({"USER_NAME", "COURSE_NAME", "QUIZ_NAME", "COURSE_URL"})

    def test_build回傳的key與常數一致(self) -> None:
        assert set(_params()) == set(QUIZ_RETEST_REQUIRED_PARAM_KEYS)


class TestBuildParams:
    def test_帶入課程名稱與測驗名稱(self) -> None:
        params = _params(course=_course(name="血品保存與冷鏈管理"), quiz_name="冷鏈概念測驗")
        assert params["USER_NAME"] == "陳小明"
        assert params["COURSE_NAME"] == "血品保存與冷鏈管理"
        assert params["QUIZ_NAME"] == "冷鏈概念測驗"

    def test_課程連結指向ET05學習頁(self) -> None:
        # 學員收到信要能直接點進去重考，連結指向學習頁而非課程列表。
        assert _params()["COURSE_URL"].endswith("/et/courses/7/learn")
