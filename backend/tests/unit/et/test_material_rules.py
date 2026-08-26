"""ET 教材純業務規則（#203）。"""

import pytest

from app.core.exceptions import AppError
from app.et.material.rules import ensure_material_has_media

pytestmark = pytest.mark.unit


class TestEnsureMaterialHasMedia:
    """三類媒材至少擇一（data-model §ET_MATERIAL）。"""

    @pytest.mark.parametrize(
        ("video", "doc", "desc"),
        [
            (True, False, False),
            (False, True, False),
            (False, False, True),
            (True, True, False),
            (True, False, True),
            (False, True, True),
            (True, True, True),
        ],
    )
    def test_任一有值即通過(self, video: bool, doc: bool, desc: bool) -> None:
        ensure_material_has_media(has_video=video, has_doc=doc, has_description=desc)

    def test_三者皆空被擋(self) -> None:
        with pytest.raises(AppError) as exc:
            ensure_material_has_media(has_video=False, has_doc=False, has_description=False)
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_MATERIAL_002"

    def test_錯誤訊息不含動態值(self) -> None:
        """對齊 sti-error-codes：訊息不嵌入教材名稱等動態內容。"""
        with pytest.raises(AppError) as exc:
            ensure_material_has_media(has_video=False, has_doc=False, has_description=False)
        assert "教材須至少提供影片、文件或說明文字其中一項" == exc.value.detail
