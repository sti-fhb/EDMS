/**
 * 判斷文字中是否含網址（#942，姓名欄位即時提示用）。
 *
 * 後端 `app/core/link_scan.py` 的鏡像：郵件軟體會自動轉成連結的四種寫法——`協定://`、開頭 `//`、
 * 開頭 `www.`、開頭反斜線兩個（UNC 路徑），不分大小寫；比對前先 NFKC 正規化、`。` 換成 `.`、刪掉瀏覽器會忽略的不可見字元。
 * 此處僅供即時提示；權威在後端，兩邊不一致時以後端為準。
 *
 * ⚠️ 不可見字元以字元碼列出、不寫字面字元：字面字元在編輯器與 diff 裡看不見，容易被當成多餘空白清掉。
 */

export const NAME_LINK_MESSAGE = "姓名不得包含網址"

/** 瀏覽器解析主機時會忽略的字元（UTS46 default ignorable），對齊後端 `_IGNORABLE_CHARS`。 */
const IGNORABLE_CODE_POINTS = new Set([
  0x00ad, 0x034f, 0x180e, 0x200b, 0x200c, 0x200d, 0x200e, 0x200f, 0x2060, 0x2061, 0x2062, 0x2063, 0x2064, 0xfeff,
])

const IDEOGRAPHIC_FULL_STOP = String.fromCodePoint(0x3002)

/** RegExp 原始碼中代表「一個字面反斜線」的寫法（兩個反斜線字元），以字元碼組出、不寫跳脫序列。 */
const RE_BACKSLASH = String.fromCodePoint(92).repeat(2)

// 四種寫法：任何「://」（協定整段由後端判斷，這裡只問有沒有）、前面不是英數或 : / 的「//」後接網址字元、
// 前面不是英數的「www.」、前面不是英數或反斜線的「\\」後接主機字元（UNC 路徑，#942）。
// 斜線一律寫成字元類 [/]，反斜線以字元碼組出，避免跳脫字元在傳遞中走樣。
const LINK_PATTERN = new RegExp(
  [
    "[:][/][/]",
    "(?<![A-Za-z0-9:/])[/][/][A-Za-z0-9._~:/?#@!$&'()*+,;=%-]",
    "(?<![A-Za-z0-9])www[.]",
    `(?<![A-Za-z0-9${RE_BACKSLASH}])${RE_BACKSLASH}${RE_BACKSLASH}[A-Za-z0-9._~%-]`,
  ].join("|"),
  "i",
)

function normalizeForLinkScan(text: string): string {
  const normalized = text.normalize("NFKC").split(IDEOGRAPHIC_FULL_STOP).join(".")
  return Array.from(normalized)
    .filter((ch) => !IGNORABLE_CODE_POINTS.has(ch.codePointAt(0) ?? 0))
    .join("")
}

/** `text` 中是否含任何網址（不論指向哪裡）。 */
export function containsLink(text: string): boolean {
  return LINK_PATTERN.test(normalizeForLinkScan(text))
}
