"""ffprobe 輸出解析（#203）。

純函式部分以 unit test 覆蓋；真的呼叫 ffprobe 的路徑留一條 integration test
（`test_et_video.py::TestProbe`）——那條需要真的 ffmpeg 與真的影片檔。

**為何不全部 mock**：mock 掉 `probe_duration_sec` 後，參數打錯、timeout 沒設、
輸出解析寫錯，CI 一概不會知道。純函式測得再滿也驗不到接線。
"""

import subprocess

import pytest

from app.core.exceptions import AppError
from app.et.material import video_probe
from app.et.material.video_probe import parse_duration_output, probe_duration_sec

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


class TestProbeFailureBranches:
    """`probe_duration_sec` 的四條失敗路徑——**都回同一個錯誤碼**（使用者能做的事
    一樣：換個檔案），但「找不到 ffprobe」另記 ERROR log。

    這些分支平常不會執行到，卻正是出事時最需要它們行為正確的時候：ffprobe 沒裝的
    症狀是「所有影片都傳不上去」，缺了那行 log 會被誤判為程式壞掉。
    """

    def _completed(self, *, returncode: int, stdout: bytes) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=b"")

    async def test_找不到_ffprobe_時回_422_並記_error(self, monkeypatch, caplog) -> None:
        def boom(path: str):
            raise FileNotFoundError(2, "No such file or directory", "ffprobe")

        monkeypatch.setattr(video_probe, "_run_ffprobe", boom)
        with caplog.at_level("ERROR"):
            with pytest.raises(AppError) as exc:
                await probe_duration_sec("whatever.mp4")

        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_MATERIAL_004"
        assert any(r.levelname == "ERROR" for r in caplog.records), "環境缺件須留下 ERROR log"
        assert "ffmpeg" in caplog.text, "訊息要指出該裝什麼"

    async def test_逾時回_422(self, monkeypatch) -> None:
        def slow(path: str):
            raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=video_probe.PROBE_TIMEOUT_SEC)

        monkeypatch.setattr(video_probe, "_run_ffprobe", slow)
        with pytest.raises(AppError) as exc:
            await probe_duration_sec("whatever.mp4")
        assert exc.value.error_code == "ET_MATERIAL_004"

    async def test_非零結束碼回_422(self, monkeypatch) -> None:
        monkeypatch.setattr(video_probe, "_run_ffprobe", lambda p: self._completed(returncode=1, stdout=b""))
        with pytest.raises(AppError) as exc:
            await probe_duration_sec("whatever.mp4")
        assert exc.value.error_code == "ET_MATERIAL_004"

    async def test_輸出無法解析回_422(self, monkeypatch) -> None:
        monkeypatch.setattr(video_probe, "_run_ffprobe", lambda p: self._completed(returncode=0, stdout=b"N/A"))
        with pytest.raises(AppError) as exc:
            await probe_duration_sec("whatever.mp4")
        assert exc.value.error_code == "ET_MATERIAL_004"

    async def test_正常輸出回整數秒(self, monkeypatch) -> None:
        monkeypatch.setattr(video_probe, "_run_ffprobe", lambda p: self._completed(returncode=0, stdout=b"12.9"))
        assert await probe_duration_sec("whatever.mp4") == 12

    async def test_輸出讀取設有上限(self, monkeypatch) -> None:
        """異常時 ffprobe 不該灌爆記憶體——只解碼前 `MAX_OUTPUT_BYTES` 個位元組。

        構造方式使「有沒有截斷」得出相反結果：前段是合法數字加空白、後段是垃圾。
        有截斷 → 解析成功；沒截斷 → `float()` 失敗。單純餵一大包數字驗不出差別
        （那會溢位成 inf 而被 NaN/inf 防護擋下，兩種情況都失敗）。
        """
        head = b"12.5"
        payload = head + b" " * (video_probe.MAX_OUTPUT_BYTES - len(head)) + b"NOT-A-NUMBER" * 500
        monkeypatch.setattr(video_probe, "_run_ffprobe", lambda p: self._completed(returncode=0, stdout=payload))
        assert await probe_duration_sec("whatever.mp4") == 12

    async def test_數值溢位視為無法解析(self, monkeypatch) -> None:
        """一長串數字會被 `float()` 轉成 inf——那不是有效長度，須擋下。"""
        payload = b"9" * (video_probe.MAX_OUTPUT_BYTES * 2)
        monkeypatch.setattr(video_probe, "_run_ffprobe", lambda p: self._completed(returncode=0, stdout=payload))
        with pytest.raises(AppError) as exc:
            await probe_duration_sec("whatever.mp4")
        assert exc.value.error_code == "ET_MATERIAL_004"
