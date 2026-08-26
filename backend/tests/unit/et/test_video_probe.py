"""ffprobe 輸出解析（#203）。

純函式部分以 unit test 覆蓋；真的呼叫 ffprobe 的路徑留一條 integration test
（`test_et_video.py::TestProbe`）——那條需要真的 ffmpeg 與真的影片檔。

**為何不全部 mock**：mock 掉 `probe_duration_sec` 後，參數打錯、timeout 沒設、
輸出解析寫錯，CI 一概不會知道。純函式測得再滿也驗不到接線。
"""

import pytest

from app.et.material.video_probe import parse_duration_output

pytestmark = pytest.mark.unit


class TestParseDurationOutput:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("180.000000\n", 180),
            ("180", 180),
            ("  180.5  \n", 180),
            ("3.999999", 3),
            ("1.0", 1),
            ("7200.123", 7200),
        ],
    )
    def test_正常輸出(self, raw: str, expected: int) -> None:
        assert parse_duration_output(raw) == expected

    def test_向下取整而非四捨五入(self) -> None:
        """180.7 → 180。

        取 181 會讓分母大於學員可累積的最大值（區段為整數秒，最多到 180），
        覆蓋率永遠到不了 100%、章節永久解不了鎖。
        """
        assert parse_duration_output("180.7") == 180

    def test_不足一秒夾到_1(self) -> None:
        """向下取整會得到 0，使覆蓋率分母為零。"""
        assert parse_duration_output("0.4") == 1

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "\n",
            "N/A",
            "abc",
            "duration=180",
            "180,5",
        ],
    )
    def test_無法解析回_none(self, raw: str) -> None:
        assert parse_duration_output(raw) is None

    @pytest.mark.parametrize("raw", ["0", "0.0", "-1", "-180.5"])
    def test_非正數回_none(self, raw: str) -> None:
        """零長度或負長度不是有效影片，不可當成分母。"""
        assert parse_duration_output(raw) is None

    @pytest.mark.parametrize("raw", ["nan", "NaN", "inf", "-inf", "Infinity"])
    def test_nan_與無限大回_none(self, raw: str) -> None:
        """`float()` 接受這些字面值，但它們都不是有效長度——漏擋會讓 NaN 進到 DB。"""
        assert parse_duration_output(raw) is None

    def test_多行輸出僅取首行前之數值(self) -> None:
        """ffprobe 正常只吐一行；多行時 `float()` 會失敗而回 None，屬預期。"""
        assert parse_duration_output("180.0\n240.0") is None
