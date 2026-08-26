"""ET 教材純業務規則（#203）。"""

import pytest

from app.core.exceptions import AppError
from app.et.material.rules import ensure_material_has_media, ensure_video_name_unused

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


class TestEnsureVideoNameUnused:
    """同一教材不可上傳同名影片。"""

    def test_新檔名通過(self) -> None:
        ensure_video_name_unused(existing_names={"a.mp4"}, file_name="b.mp4")

    def test_教材無影片時通過(self) -> None:
        ensure_video_name_unused(existing_names=set(), file_name="a.mp4")

    def test_同名被擋(self) -> None:
        with pytest.raises(AppError) as exc:
            ensure_video_name_unused(existing_names={"a.mp4"}, file_name="a.mp4")
        assert exc.value.status_code == 409
        assert exc.value.error_code == "ET_MATERIAL_005"

    def test_大小寫不同視為不同檔名(self) -> None:
        """不做大小寫正規化——Windows 與 Linux 的檔案系統對此的認定本就不同，
        自行折衷只會讓行為在兩邊不一致。"""
        ensure_video_name_unused(existing_names={"A.mp4"}, file_name="a.mp4")

    def test_訊息告知可行的下一步(self) -> None:
        """只說「重複」不夠——要讓教師知道能做什麼。"""
        with pytest.raises(AppError) as exc:
            ensure_video_name_unused(existing_names={"a.mp4"}, file_name="a.mp4")
        assert "移除" in exc.value.detail or "其他檔名" in exc.value.detail
