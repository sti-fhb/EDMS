"""網址掃描（#942）：從 #940 的範本網址檢核抽出，供姓名欄位共用。

`contains_link` 判斷文字中有沒有郵件軟體會自動轉成連結的寫法：`協定://`、開頭 `//`、開頭
`www.`（不分大小寫），比對前先做 NFKC 正規化、`。` 換成 `.`、刪掉瀏覽器會忽略的不可見字元。
"""

import time

import pytest

from app.core.link_scan import contains_link

pytestmark = pytest.mark.unit

#: 反斜線以字元碼組出，不在原始碼直接寫跳脫序列（傳遞過程中容易被改寫）
_BS = chr(92)
_UNC = f"{_BS}{_BS}evil.example.com{_BS}share"


@pytest.mark.parametrize(
    "text",
    [
        _UNC,  # Outlook 桌面版會把 UNC 路徑轉成 file: 連結，點擊即以 SMB 連線
        f"請至 {_UNC} 下載",
        f"{_BS}{_BS}10.0.0.1{_BS}x",
        f"請至{_UNC}",  # 前面緊貼中文
        f"-{_UNC}",
    ],
)
def test_contains_unc_path(text):
    assert contains_link(text) is True


@pytest.mark.parametrize(
    "text",
    [
        f"a{_BS}{_BS}b",  # 前面是英數，不是起點
        f"{_BS}{_BS} 後面接空白",
        f"王{_BS}小明",  # 單一反斜線
    ],
)
def test_backslashes_that_are_not_unc(text):
    assert contains_link(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "https://evil.example.com",
        "http://evil.example.com/x",
        "HTTPS://EVIL.EXAMPLE.COM",
        "帳號異常請至 https://evil.example.com 處理",
        "ftp://evil.example.com",
        "//evil.example.com/x",
        "www.evil.example.com",
        "WWW.EVIL.EXAMPLE.COM",
        "Www.evil.example.com",
        "-www.evil.example.com",
        ".https://evil.example.com",
        "1https://evil.example.com",
        "-//evil.example.com",
        "ｈｔｔｐｓ://evil.example.com",  # 全形協定
        "ｗｗｗ．evil．example．com",  # 全形 www 與句點
        "請至https://evil.example.com處理",  # 前後緊貼中文
        "h\u00adttps://evil.example.com",  # 軟連字號插在協定中
        "www\u200b.evil.example.com",  # 零寬空白插在 www 後
        "請至 www。evil.example.com",  # U+3002 當成句點
    ],
)
def test_contains_link(text):
    assert contains_link(text) is True


def _interleaved_min_times(texts: list[str], reps: int = 7) -> list[float]:
    """各段文字交錯量 `reps` 輪、各取最小值：避免「量小的時機器剛好閒、量大的時剛好忙」。"""
    best = [float("inf")] * len(texts)
    for _ in range(reps):
        for i, text in enumerate(texts):
            start = time.perf_counter()
            contains_link(text)
            best[i] = min(best[i], time.perf_counter() - start)
    return best


@pytest.mark.parametrize("unit", ["a", "a.", "1+", _BS * 2 + "a"])
def test_scan_time_grows_linearly(unit):
    """長串協定字元不得讓掃描變成 O(n²)（#942 security review）。

    範本內文上限 10000 字，檢核在 async 的 `update_template` 中同步執行，平方成長會卡住整個
    event loop。協定分支若沒有前方否定斷言，每個起點都會往後掃到整串英數的結尾。

    量成長比例而非絕對秒數：多 session 並行時絕對值會飄好幾倍，比例不會。
    長度放大 4 倍：線性約 4、平方約 16，門檻 8 讓兩邊各留一倍餘裕。初版用「長度加倍、門檻 3、
    取 3 次最小值」，量到的時間不到 1ms，在另一個 session 吃滿 CPU 時被排程雜訊撐到 6.7 倍而假紅。
    """
    n = 5000
    small, large = _interleaved_min_times([unit * (n // len(unit)), unit * (4 * n // len(unit))])
    assert large / small < 8, (
        f"長度放大 4 倍耗時成長 {large / small:.1f} 倍（{small * 1000:.1f}ms → {large * 1000:.1f}ms）"
    )


@pytest.mark.parametrize(
    "text",
    [
        "王小明",
        "John Smith",
        "J. Smith",
        "O'Brien",
        "王-小明",
        "Mary-Jane Watson",
        "A/B 組",
        "a//b",  # 前面是英數，不是網址起點
        "張三 // 李四",  # // 後面接空白，沒有主機
        "lawww.example",  # www 前面是英數，不是起點
        "v1.2",
        "08:30",
        "user@example.com",  # Email 地址不是網址
        "",
    ],
)
def test_no_link(text):
    assert contains_link(text) is False
