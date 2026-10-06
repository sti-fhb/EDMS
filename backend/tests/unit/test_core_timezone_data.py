"""時區資料必須由宣告過的相依提供，不能只靠執行環境碰巧有（#501）。

`app/core/utils.py` 與 `app/et/notify/course_invite.py` 的 `ZoneInfo("Asia/Taipei")` 都在
**模組層**——取不到 IANA 時區資料時不是某個功能壞掉，是 import 期就拋
`ZoneInfoNotFoundError`、整個後端起不來。

## ⚠️ 本檔只在 Linux 上有鑑別力，在 Windows 開發機恆綠

`zoneinfo` 取資料的順序是「**先找系統 `TZPATH`，找不到才退到 `tzdata` 套件**」：

| 環境 | 系統 `TZPATH` | `tzdata` 套件 |
|---|---|---|
| Windows 開發機 | 空（Windows 無 IANA 資料庫）| 有——`tzlocal` 的相依 marker 是 `sys_platform == 'win32'` |
| CI runner / Linux | `/usr/share/zoneinfo` 等 | **#501 之前沒有**（同一個 marker 把 Linux 排除了）|

所以直接寫 `assert ZoneInfo("Asia/Taipei")` 是**假證據**——兩種環境、改與不改都會過。
本檔的做法是**清空 `TZPATH`**，逼 `zoneinfo` 只能走套件那條路：

- Linux：#501 之前沒裝 `tzdata` → 紅；宣告之後 → 綠。**真的分得出來**
- Windows：兩種情況都綠（套件本來就在）。這是限制，不是缺陷

⛔ 不要因為「在我機器上怎麼改都綠」就判定本檔無用而刪掉它——它守的是 CI 與正式映像。
另一道獨立的守門在 `.github/workflows/cd.yml` 的「驗證映像可解析時區」，驗的是實際映像。
"""

import zoneinfo
from zoneinfo import ZoneInfo

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def tzpath_cleared():
    """暫時清空系統時區搜尋路徑，使 `ZoneInfo` 只能依賴 `tzdata` 套件。

    ⚠️ `TZPATH` 與 `ZoneInfo` 的快取都是**行程層級的全域狀態**，故務必成對還原——
    漏還原會讓同一個 worker 之後的所有時間相關測試都查不到時區，而且錯誤訊息
    （`No time zone found with key ...`）完全看不出是被這條測試弄壞的。

    ⚠️ 還原的自我檢查**必須放在這裡**，不能寫成另一條 test function。CI 跑
    `pytest -n auto`（`ci.yml:165`），xdist 的 `--dist load` 會把同檔測試**打散到不同行程**
    ——實測 `gw0` / `gw1` 各拿一條，那麼「檢查還原」的那條所在的行程根本沒執行過本 fixture，
    於是把下面整段 `finally` 刪掉它照樣綠。寫在 fixture 內才保證同行程、且在還原之後執行。
    """
    original = zoneinfo.TZPATH
    zoneinfo.reset_tzpath(to=[])
    ZoneInfo.clear_cache()
    try:
        yield
    finally:
        zoneinfo.reset_tzpath(to=list(original))
        ZoneInfo.clear_cache()
        assert zoneinfo.TZPATH == original, "TZPATH 未還原，同 worker 後續的時間測試會被污染"
        assert ZoneInfo("Asia/Taipei") is not None, "還原後仍解析不到時區，快取未正確重建"
        # ⚠️ 這兩條斷言與本檔的主測試一樣，**在 Windows 上無法以變異檢查驗證**：
        # Windows 的 `TZPATH` 原本就是 `()`，所以「清空」與「沒還原」兩種狀態完全相同，
        # 拿掉上面的 `reset_tzpath` 仍會綠（2026-10-06 實測）。別據此判定它沒用——
        # 在 Linux 上 `TZPATH` 非空，漏還原會立刻被這兩條抓到。


def test_不靠系統時區檔也要解析得到台灣時區(tzpath_cleared):
    """沒有系統 IANA 資料時仍須解析成功——即 `tzdata` 套件確實被安裝了。

    這條紅掉代表 `backend/pyproject.toml` 的 `tzdata` 宣告被移除，或被加上了
    `sys_platform` marker（那等於只裝在 Windows，Linux 恢復成裸奔）。
    """
    assert zoneinfo.TZPATH == (), "fixture 未生效，本條將失去鑑別力"

    assert ZoneInfo("Asia/Taipei") is not None
