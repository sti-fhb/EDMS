"""ET05 章節學習之純業務規則（US5 / #255）。"""

import pytest

from app.core.exceptions import AppError
from app.et.learning.rules import (
    PLAYBACK_RATE_OPTIONS,
    ensure_can_access,
    playback_rates,
)

pytestmark = pytest.mark.unit


class TestEnsureCanAccess:
    """授權：在籍 **OR** 擁有者（#255 SA Q1 裁示 A）。"""

    def test_在籍學員可存取(self) -> None:
        ensure_can_access(enrolled=True, is_owner=False)

    def test_擁有者可存取(self) -> None:
        """裁示 A：教師需能驗收學員視角。

        他在 ET02 看到的是編輯表單（上傳欄位、文件下拉），與學員實際看到的呈現完全
        不同——影片能不能播、PDF 內嵌會不會爆版，不進 ET05 無從得知。而「自己加入
        自己的課」會讓他被計入完課率分母（US9 AC 22 只排除已移除者）。
        """
        ensure_can_access(enrolled=False, is_owner=True)

    def test_既在籍又是擁有者可存取(self) -> None:
        ensure_can_access(enrolled=True, is_owner=True)

    def test_兩者皆非被擋(self) -> None:
        """影片與 DM 文件是實體檔案；少了這道判定，任何登入者知道 id 就能抓走全站教材。"""
        with pytest.raises(AppError) as exc:
            ensure_can_access(enrolled=False, is_owner=False)
        assert exc.value.status_code == 403
        assert exc.value.error_code == "ET_LEARN_002"


class TestPlaybackRates:
    """倍速上限只能**往下限縮**（FR-ET-US5-03）。"""

    def test_預設上限回全部選項(self) -> None:
        assert playback_rates(max_rate=2) == PLAYBACK_RATE_OPTIONS

    def test_固定選項為五段(self) -> None:
        assert PLAYBACK_RATE_OPTIONS == (0.75, 1.0, 1.25, 1.5, 2.0)

    @pytest.mark.parametrize(
        ("max_rate", "expected"),
        [
            (1.5, (0.75, 1.0, 1.25, 1.5)),
            (1.0, (0.75, 1.0)),
            (0.75, (0.75,)),
        ],
    )
    def test_上限往下限縮(self, max_rate: float, expected: tuple[float, ...]) -> None:
        assert playback_rates(max_rate=max_rate) == expected

    def test_上限調高不會多出選項(self) -> None:
        """**這是本規則的重點**。

        `ET_VIDEO_PLAYBACK_MAX_RATE` 看起來像一個「設定倍速上限」的參數，很容易被
        實作成 `range(...)` 之類的動態產生——那樣設 3 就會多出 3x。FR-ET-US5-03 明訂
        選項清單為前端寫死、參數**只能往下限縮**（DP #171 將此參數判為 `READONLY`
        正是這個理由）。
        """
        assert playback_rates(max_rate=3) == PLAYBACK_RATE_OPTIONS
        assert playback_rates(max_rate=10) == PLAYBACK_RATE_OPTIONS
        assert 3.0 not in playback_rates(max_rate=3)

    def test_上限低於最小選項仍保留最慢一段(self) -> None:
        """避免回空清單——播放器沒有任何可選倍速等於壞掉。

        參數被設成 0.5（低於最小選項 0.75）是設定錯誤，但它不該讓播放器不能用。
        """
        assert playback_rates(max_rate=0.5) == (0.75,)
