"""教材說明文字之 HTML allow-list 消毒（#203 / #188 前瞻風險 B1）。

`ET_MATERIAL.DESCRIPTION_HTML` 由教師以 WYSIWYG 產生並存成 HTML，供**該課程全體
學員**閱讀。若不消毒，取得任一教師帳號者即可對所有學員種下**持久性 XSS**——
一次寫入、每個開啟該教材的學員都執行。

**這裡是第一道防線，不是唯一一道也不是第二道**：前端的 DOMPurify 只擋得住經由
UI 的輸入，攻擊者直接打 API 就繞過了。`sti-coding-style` 要求注入 HTML 前先
`DOMPurify.sanitize()`，該規則講的是**渲染端**；寫入端的把關在這裡。

## 為何用 `nh3` 而非 `bleach`

`bleach` 已於 2023 年由 Mozilla **封存、停止維護**，其 README 明確建議改用
`nh3`（Rust `ammonia` 之 Python 綁定）。本專案對依賴健康度有前例可循——#146 曾為了
一個無解的上游告警把 `fastapi-mail` 整個移除——引入一個已停止維護的解析器來做
安全關鍵的工作並不合適。

## 白名單的取捨

只放行 WYSIWYG 實際會產出、且語意上屬於「說明文字」的標籤。刻意**不**放行：

- `<a>` —— 2026-08-26 移除。編輯器的「插入連結」工具已依實測回饋拿掉，教師要放
  連結直接把 URL 打進文字即可。**白名單跟著收斂**：留著一個沒有任何入口會產出的
  標籤，只是憑空多一塊攻擊面。
- `<img>` —— 教材圖片應走影片 / DM 文件，放行等於開一條可外連任意 URL 的路徑
  （即使不執行腳本，`<img src>` 也能用於追蹤學員閱讀行為與 IP）
- `<table>` —— WYSIWYG 產出的表格 HTML 結構複雜、消毒後常破版，需求也未提及
- `style` 屬性 —— CSS 可用於 UI 偽裝（把假的登入框疊在畫面上）
- `class` / `id` —— 會與系統樣式表衝突，且可被用來干擾頁面版面

移除 `<a>` 之後，既有內容中的連結會在下次存檔時**降級為純文字**（nh3 剝標籤但保留
文字），不會整段消失。此舉經 SA 於 2026-08-26 確認——當時尚無正式資料需保存。

日後要放寬，改這裡的常數即可；但每加一項都應先想清楚它能被拿來做什麼。
"""

import nh3

#: 放行之標籤。加項前請先確認該標籤無法承載腳本或外部請求。
ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "p",
        "br",
        "strong",
        "em",
        "u",
        "s",
        "ul",
        "ol",
        "li",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "code",
        "pre",
    }
)

#: 放行之屬性。目前**全部標籤都不帶屬性**——`<a>` 已於 2026-08-26 移出白名單。
#:
#: 這裡與下方兩個常數刻意保留（而非一併刪除）：日後若有人把 `a` 加回
#: `ALLOWED_TAGS`，scheme 限制與 `rel` 就已經在位。少了它們而重新放行 `a`，等於
#: 默默開了一條 `javascript:` 的路——那種疏漏不會有人察覺。
ALLOWED_ATTRIBUTES: dict[str, set[str]] = {"a": {"href", "title"}}

#: 放行之 URL scheme。`javascript:` / `data:` / `vbscript:` / `file:` 皆不在其中——
#: 前三者可直接執行腳本，`file:` 則可探測本機路徑。
ALLOWED_URL_SCHEMES: set[str] = {"http", "https"}

#: 外部連結一律補上——缺 `noopener` 時，被開啟的頁面可經 `window.opener` 操控原分頁
#: （導向釣魚頁）；`noreferrer` 則避免把學員所在的內部網址洩漏給外部站台。
_LINK_REL = "noopener noreferrer"


def sanitize_material_html(raw: str | None) -> str | None:
    """以 allow-list 消毒教材說明 HTML；內容為空（或消毒後為空）時回 `None`。

    回 `None` 而非空字串：`DESCRIPTION_HTML` 為選填欄位，DB 存 `NULL` 表示未填。
    若整段內容都被消毒掉（例如通篇只有 `<script>`），結果等同未填——留一個空殼字串
    只會讓「有說明但顯示不出來」與「沒有說明」在下游難以區辨。

    Args:
        raw: WYSIWYG 產出的原始 HTML，或 `None`。

    Returns:
        消毒後之 HTML；無實質內容時為 `None`。
    """
    if raw is None or not raw.strip():
        return None
    cleaned = nh3.clean(
        raw,
        tags=set(ALLOWED_TAGS),
        attributes={tag: set(attrs) for tag, attrs in ALLOWED_ATTRIBUTES.items()},
        url_schemes=set(ALLOWED_URL_SCHEMES),
        link_rel=_LINK_REL,
        strip_comments=True,
    )
    return cleaned if cleaned.strip() else None
