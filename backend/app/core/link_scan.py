"""找出文字中的網址（#940 抽出、#942 共用）。

只負責「哪裡有網址、協定與主機部分是什麼」，不判斷網址可不可以：
- 通知範本（`dp/notify/service.ensure_links_same_site`）要求主機等於本系統。
- 姓名（`core/schema_types.SafeNameStr`）一律不允許網址。

⚠️ 本檔的不可見字元一律寫成 `\\uXXXX` 跳脫序列，不放字面字元：字面的不可見字元在
編輯器與 diff 裡看不出來，下一個人「順手清空白」就會靜默拆掉防線（`core/schema_types.py` 踩過）。
"""

import re
import unicodedata
from collections.abc import Iterator
from typing import NamedTuple

#: 網址可由哪些字元組成：RFC 3986 的 unreserved + reserved + `%`。遇到空白、非 ASCII（中文、
#: 全形標點）或 `\` 即視為網址結束——瀏覽器把 `\` 當 `/`，在該處截斷得到的主機正是瀏覽器實際
#: 連線的主機（`https://evil\@本站` → evil）。
_URL_CHARS = r"[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]"

#: 郵件軟體會自動轉成連結的四種寫法：`協定://`、開頭 `//`、開頭 `www.`、開頭 `\\`（UNC），不分大小寫。
#:
#: - 協定分支以 `://` 為錨點、往前取**整段**連續的協定字元，由呼叫端判斷協定是否可接受。
#:   ⚠️ 不要改回「協定須以字母開頭 + 前方否定斷言」：`.https://`、`1https://` 會因此在任何
#:   位置都匹配不到而整條放行（#940 review），郵件軟體卻仍從 `https://` 轉連結。
#:   ⚠️ 但前方否定斷言**本身**要留著（字元集與協定字元相同）：它只保證「從整段的開頭起算」，
#:   不影響取到哪些字元。拿掉的話，每個起點都會往後掃到整串英數的結尾再失敗，掃描變成 O(n²)，
#:   10000 字的範本內文會卡住 event loop 數秒（#942 security review；`test_scan_time_grows_linearly`）。
#: - `//` 分支排除前面是英數、`:`、`/` 的情況：`https://` 已由協定分支吃掉，`a/b//c` 不是網址。
#: - `www.` 分支只排除前面是英數（`awww.` 不是起點）；`-www.`、`.www.` 照樣抓。
#: - UNC 分支（#942）：開頭 `\\` 後接主機字元。Outlook 桌面版會把純文字中的 UNC 路徑轉成
#:   `file:` 連結，點擊即以 SMB 連到該主機，可能送出使用者的 Windows 憑證。比照 `//` 分支，
#:   前面是英數或反斜線者不算起點。反斜線以 `chr(92)` 組出，不在原始碼寫跳脫序列。
_BACKSLASH = re.escape(chr(92))

_LINK_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9+.\-])(?P<scheme>[A-Za-z0-9+.\-]*)://(?P<rest>{_URL_CHARS}*)"
    rf"|(?<![A-Za-z0-9:/])//(?P<relative>{_URL_CHARS}+)"
    rf"|(?<![A-Za-z0-9])(?P<www>www\.{_URL_CHARS}*)"
    rf"|(?<![A-Za-z0-9{_BACKSLASH}]){_BACKSLASH}{_BACKSLASH}(?P<unc>[A-Za-z0-9\-._~%]+)",
    re.IGNORECASE,
)

#: UNC 分支命中時 `LinkHit.scheme` 的值；不在 http(s) 之內，範本檢核會一律視為外部網址。
UNC_SCHEME = "unc"

#: 掃描前先刪掉的字元：瀏覽器解析主機時會忽略它們（UTS46 的 default ignorable），留著的話
#: `本站\u00adevil.com` 會在該字元處被截成「本站」而放行，瀏覽器實際連的卻是 `本站evil.com`。
_IGNORABLE_CHARS = dict.fromkeys(
    (0x00AD, 0x034F, 0x180E, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2060, 0x2061, 0x2062, 0x2063, 0x2064, 0xFEFF)
)

#: 瀏覽器會當成 `.` 的全形句點；NFKC 已把 U+FF0E、U+FF61 轉成 `.` 或 U+3002，剩下 U+3002 要自己換。
_IDEOGRAPHIC_FULL_STOP = "\u3002"


class LinkHit(NamedTuple):
    """一筆網址命中。

    Attributes:
        scheme: 協定分支為整段協定字元（小寫，可能是 `""`、`"ftp"`、`".https"`）；
            UNC 分支為 `UNC_SCHEME`；`//`、`www.` 分支為 `None`。
        target: 協定或 `//` 之後的部分（`www.` 分支含 `www.` 本身），未剝尾端句讀。
    """

    scheme: str | None
    target: str


def normalize_for_link_scan(text: str) -> str:
    """掃描前的正規化：NFKC、`。` 換成 `.`、刪掉瀏覽器解析主機時會忽略的字元。

    瀏覽器解析主機時會這樣處理；不先做的話 `本站。evil.com`、全形 `ｈｔｔｐｓ://` 會在非 ASCII
    處被截斷而放行。
    """
    return unicodedata.normalize("NFKC", text).replace(_IDEOGRAPHIC_FULL_STOP, ".").translate(_IGNORABLE_CHARS)


def iter_links(text: str) -> Iterator[LinkHit]:
    """逐筆列出 `text`（先經 `normalize_for_link_scan`）中的網址。

    Args:
        text: 待掃描的文字。

    Returns:
        依出現順序的 `LinkHit`。
    """
    for match in _LINK_PATTERN.finditer(normalize_for_link_scan(text)):
        if match.group("rest") is not None:
            yield LinkHit(scheme=match.group("scheme").lower(), target=match.group("rest"))
        elif match.group("relative") is not None:
            yield LinkHit(scheme=None, target=match.group("relative"))
        elif match.group("unc") is not None:
            yield LinkHit(scheme=UNC_SCHEME, target=match.group("unc"))
        else:
            yield LinkHit(scheme=None, target=match.group("www"))


def contains_link(text: str) -> bool:
    """`text` 中是否含任何網址（不論指向哪裡）。

    Args:
        text: 待掃描的文字。

    Returns:
        含網址為 True。
    """
    return next(iter_links(text), None) is not None
