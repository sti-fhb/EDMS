"""教材說明文字之 HTML 消毒（#203 / #188 B1）。

`ET_MATERIAL.DESCRIPTION_HTML` 由教師以 WYSIWYG 產生並存 HTML，供**全體學員**閱讀。
未消毒時，取得教師帳號者可對所有學員種下持久性 XSS——本模組是後端的第一道防線
（前端 DOMPurify 只是第二道，繞過前端直打 API 即失效）。

以 **allow-list** 為準：預設拒絕，只放行明確列出的標籤與屬性。
"""

import pytest

from app.et.common.html_sanitize import sanitize_material_html

pytestmark = pytest.mark.unit


class TestAllowed:
    """白名單內的標籤與屬性須原樣保留——消毒過頭會讓編輯器產出的內容被吃掉。"""

    @pytest.mark.parametrize(
        "html",
        [
            "<p>段落</p>",
            "<strong>粗體</strong>",
            "<em>斜體</em>",
            "<u>底線</u>",
            "<ul><li>項目</li></ul>",
            "<ol><li>編號</li></ol>",
            "<h3>標題</h3>",
            "<blockquote>引用</blockquote>",
            "<p>換行<br>之後</p>",
        ],
    )
    def test_白名單標籤保留(self, html: str) -> None:
        assert sanitize_material_html(html) == html

    def test_自閉合標籤正規化為_html5_空元素(self) -> None:
        """`<br />` → `<br>`：nh3 以 HTML5 序列化輸出。

        記在這裡是因為它會影響前端——編輯器送出 XHTML 風格的自閉合標籤時，存回來的
        內容與送出的字串不同。這是正規化不是資料遺失，且正因為有正規化，消毒才具
        冪等性（見 `test_消毒具冪等性`）。
        """
        assert sanitize_material_html("<p>換行<br />之後</p>") == "<p>換行<br>之後</p>"

    def test_巢狀結構保留(self) -> None:
        html = "<ul><li><strong>重點</strong>說明</li></ul>"
        assert sanitize_material_html(html) == html

    def test_純文字原樣通過(self) -> None:
        assert sanitize_material_html("純文字沒有標籤") == "純文字沒有標籤"


class TestScriptRemoval:
    """腳本注入——本模組存在的理由。"""

    def test_script_標籤連內容一併移除(self) -> None:
        got = sanitize_material_html("<p>正常</p><script>alert(1)</script>")
        assert "script" not in got.lower()
        assert "alert" not in got, "只移除標籤而留下內容，換個上下文仍可能被執行"

    def test_行內事件處理器被剝除(self) -> None:
        got = sanitize_material_html('<p onclick="steal()">文字</p>')
        assert "onclick" not in got.lower()
        assert "文字" in got, "剝屬性不應連內容一起吃掉"

    @pytest.mark.parametrize("attr", ["onerror", "onload", "onmouseover", "onfocus"])
    def test_各類事件屬性皆被剝除(self, attr: str) -> None:
        got = sanitize_material_html(f'<p {attr}="x()">文字</p>')
        assert attr not in got.lower()

    def test_iframe_被移除(self) -> None:
        got = sanitize_material_html('<iframe src="https://evil.example"></iframe><p>後續</p>')
        assert "iframe" not in got.lower()
        assert "後續" in got

    def test_style_標籤被移除(self) -> None:
        """`<style>` 可用於 UI 偽裝與資料外洩（如以背景圖 URL 帶出資訊）。"""
        got = sanitize_material_html("<style>body{display:none}</style><p>內容</p>")
        assert "<style" not in got.lower()
        assert "display:none" not in got


class TestLinks:
    """連結是唯一放行屬性的標籤，須逐項限制。"""

    def test_https_連結保留(self) -> None:
        got = sanitize_material_html('<a href="https://example.com">連結</a>')
        assert 'href="https://example.com"' in got
        assert "連結" in got

    def test_http_連結保留(self) -> None:
        assert 'href="http://example.com"' in sanitize_material_html('<a href="http://example.com">x</a>')

    @pytest.mark.parametrize(
        "href",
        [
            "javascript:alert(1)",
            "JaVaScRiPt:alert(1)",
            "data:text/html;base64,PHNjcmlwdD4=",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
        ],
    )
    def test_危險_scheme_被擋(self, href: str) -> None:
        """只放行 http(s)——`javascript:` 是最典型的繞過路徑，大小寫混寫亦須擋下。"""
        got = sanitize_material_html(f'<a href="{href}">點我</a>')
        assert "javascript" not in got.lower()
        assert "vbscript" not in got.lower()
        assert "data:text/html" not in got.lower()
        assert "file://" not in got.lower()

    def test_外部連結加上_rel_noopener(self) -> None:
        """新視窗開啟時，缺 `noopener` 會讓目標頁能以 `window.opener` 操控原分頁。"""
        got = sanitize_material_html('<a href="https://example.com">x</a>')
        assert "noopener" in got
        assert "noreferrer" in got

    def test_連結不得夾帶事件屬性(self) -> None:
        got = sanitize_material_html('<a href="https://example.com" onclick="x()">x</a>')
        assert "onclick" not in got.lower()


class TestEdgeCases:
    def test_none_原樣回傳(self) -> None:
        """說明文字為選填；`None` 與空字串須可區辨（未填 vs. 填了又清空）。"""
        assert sanitize_material_html(None) is None

    def test_空字串視同未填(self) -> None:
        assert sanitize_material_html("") is None

    def test_全空白視同未填(self) -> None:
        assert sanitize_material_html("   \n  ") is None

    def test_消毒後只剩空白視同未填(self) -> None:
        """整段只有腳本時，消毒後應為未填而非留下空殼。"""
        assert sanitize_material_html("<script>alert(1)</script>") is None

    def test_未閉合標籤被修正而非拋錯(self) -> None:
        got = sanitize_material_html("<p>沒關</p><p>另一段")
        assert "沒關" in got and "另一段" in got

    def test_消毒具冪等性(self) -> None:
        """消毒過的內容再消毒一次結果須相同——否則反覆存檔會讓內容逐次變形。"""
        once = sanitize_material_html('<p onclick="x">文字</p><a href="https://e.com">連結</a>')
        assert sanitize_material_html(once) == once
