"""課程內容更新通知信之參數組法（ET-13 / #303）。

params 的 key 若與範本佔位對不上，平台 `_SafeFormatter` 會拋 `KeyError` → 該批寫成
`DP_EMAIL_LOG.STATUS='FAILED'`、`queued_count=0`，**且不外拋**——呼叫方看起來一切正常，
只是沒有人收到信。本檔把 key 集合釘死，比照 `test_et_invitation_mail.py`。
"""

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.et.course.models import EtCourse
from app.et.notify.course_update import (
    COURSE_UPDATE_PARAM_KEYS,
    TEMPLATE_COURSE_UPDATE,
    build_course_update_params,
)

pytestmark = pytest.mark.unit

_UTC_0100 = datetime(2026, 4, 15, 1, 0, tzinfo=timezone.utc)


def _course(course_id: int = 7, name: str = "採血作業訓練") -> EtCourse:
    return EtCourse(course_id=course_id, course_name=name, status="PUBLISHED", open_start_at=_UTC_0100)


class TestTemplateParamKeys:
    def test_範本代碼為COURSE_UPDATE(self) -> None:
        """⚠️ `issues.md` AC 1 誤寫為 `ET_NEW_CHAPTER`，但 T113 / data-model:696 /
        contracts:105 三處與實際 seed 皆為 `COURSE_UPDATE`，且 ET-14 明訂 ET 僅有 7 類
        固定範本、不可新增，清單中不含 `ET_NEW_CHAPTER`。
        """
        assert TEMPLATE_COURSE_UPDATE == "COURSE_UPDATE"

    def test_四個佔位一個不多一個不少(self) -> None:
        """對齊 `contracts/ext-et-email-server.md` §COURSE_UPDATE 之變數表。"""
        assert COURSE_UPDATE_PARAM_KEYS == frozenset({"USER_NAME", "COURSE_NAME", "NEW_CHAPTER_NAME", "COURSE_URL"})

    def test_build回傳的key與常數一致(self) -> None:
        params = build_course_update_params(user_name="陳小明", course=_course(), new_chapter_name="第三章 異常處理")
        assert set(params) == set(COURSE_UPDATE_PARAM_KEYS)


class TestBuildParams:
    def test_帶入課程名稱與新章節名稱(self) -> None:
        params = build_course_update_params(
            user_name="陳小明", course=_course(name="血品安全"), new_chapter_name="第三章 異常處理"
        )
        assert params["USER_NAME"] == "陳小明"
        assert params["COURSE_NAME"] == "血品安全"
        assert params["NEW_CHAPTER_NAME"] == "第三章 異常處理"

    def test_課程連結指向ET05學習頁(self) -> None:
        """收件人**已在課程中**（章節更新只寄給在籍學員），故連結是學習頁而非邀請頁。"""
        params = build_course_update_params(user_name="陳小明", course=_course(course_id=42), new_chapter_name="第二章")
        assert params["COURSE_URL"] == f"{settings.FRONTEND_BASE_URL.rstrip('/')}/et/courses/42/learn"

    def test_所有值皆為字串(self) -> None:
        """平台 `_SafeFormatter` 直接把值代入字串範本；非字串會渲染出 repr。"""
        params = build_course_update_params(user_name="陳小明", course=_course(), new_chapter_name="第二章")
        assert all(isinstance(v, str) for v in params.values())
