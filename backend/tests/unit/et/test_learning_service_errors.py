"""ET06 學員端拒絕路徑：每次 raise 新的 `AppError` 實例（#289 裁示 A）。

`GET /api/et/courses/{任意 id}/learn` 與 `GET /api/et/materials/{任意 id}/content` 不需
在籍、不需該課程存在——任一登入者迴圈呼叫即可觸發（限流只降速、不止累積）。若拒絕用的是
模組層級常數，每次 raise 都會把本次 frame 附加到同一個 traceback 上而只增不減。

`main.app_error_handler` 已清 traceback（裁示 B）；本檔釘住的是不依賴 handler 的第二道
防線：查無即拒的路徑在 repository 第一步就返回，用假 repository 即可驗，不需真 DB。
"""

import traceback
from typing import Any

import pytest

from app.core.exceptions import AppError
from app.et.learning.service import EtLearningService

pytestmark = pytest.mark.unit

_ROUNDS = 10


class _EmptyRepo:
    """一律查無：課程、教材、影片皆不存在。"""

    async def get_course(self, db: Any, course_id: int) -> None:
        return None

    async def course_id_of_material_any(self, db: Any, material_id: int) -> None:
        return None

    async def get_video(self, db: Any, video_id: int) -> None:
        return None


def _service() -> EtLearningService:
    return EtLearningService(repository=_EmptyRepo())  # type: ignore[arg-type]


async def _collect(call) -> list[AppError]:
    errors: list[AppError] = []
    for _ in range(_ROUNDS):
        with pytest.raises(AppError) as exc:
            await call()
        errors.append(exc.value)
    return errors


def _assert_fresh_each_time(errors: list[AppError], error_code: str) -> None:
    assert {e.error_code for e in errors} == {error_code}
    # 持有全部實例時 id 不會被回收重用，故 id 相異即代表每次都是新實例。
    assert len({id(e) for e in errors}) == len(errors)
    assert len({len(traceback.extract_tb(e.__traceback__)) for e in errors}) == 1


class TestLearningService拒絕不累積:
    async def test_structure查無課程(self) -> None:
        """`/courses/{id}/learn`：`_not_found`。"""
        svc = _service()
        errors = await _collect(lambda: svc.structure(None, 999, user_id="U1"))  # type: ignore[arg-type]
        _assert_fresh_each_time(errors, "ET_LEARN_001")

    async def test_material_content查無教材(self) -> None:
        """`/materials/{id}/content`：`_file_not_found`。"""
        svc = _service()
        errors = await _collect(lambda: svc.material_content(None, 999, user_id="U1"))  # type: ignore[arg-type]
        _assert_fresh_each_time(errors, "ET_LEARN_001")

    async def test_video_file_by_ticket查無影片(self) -> None:
        svc = _service()
        errors = await _collect(lambda: svc.video_file_by_ticket(None, 999))  # type: ignore[arg-type]
        _assert_fresh_each_time(errors, "ET_LEARN_001")
