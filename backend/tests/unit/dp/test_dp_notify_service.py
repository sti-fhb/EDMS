"""通知發送服務 SRVDP002（T018）純函式單元測試：渲染 / CHANNEL 判定（不連 DB）。"""

import pytest

from app.dp.notify.service import _channel_allows_email, _render

pytestmark = pytest.mark.unit


def test_render_substitutes_params():
    """範本佔位以 params 代入。"""
    assert _render("Hi {name}, code={code}", {"name": "小明", "code": "123"}) == "Hi 小明, code=123"


def test_render_no_placeholder_returns_as_is():
    """無佔位的範本原樣回傳。"""
    assert _render("純文字內容", {"unused": "x"}) == "純文字內容"


def test_render_missing_var_raises_keyerror():
    """範本需要的變數 params 未提供 → 拋 KeyError（呼叫端據以標該列 FAILED）。"""
    with pytest.raises(KeyError):
        _render("Hi {name}", {"other": "x"})


def test_render_unbalanced_brace_raises_valueerror():
    """範本含未閉合大括號 → 拋 ValueError（呼叫端據以標該列 FAILED，不外拋）。"""
    with pytest.raises(ValueError, match="."):
        _render("hello {name", {"name": "x"})


def test_render_blocks_attribute_access():
    """封鎖屬性存取（防 {x.__class__...__globals__} 讀機密）→ ValueError。"""
    with pytest.raises(ValueError, match="具名變數"):
        _render("{x.__class__}", {"x": "y"})


def test_render_blocks_index_and_positional():
    """封鎖索引 / 位置佔位 → ValueError。"""
    with pytest.raises(ValueError, match="具名變數"):
        _render("{0}", {"0": "y"})


def test_render_blocks_format_spec():
    """封鎖格式規格（防 {v:>200000000} OOM）→ ValueError。"""
    with pytest.raises(ValueError, match="格式規格"):
        _render("{name:>100}", {"name": "x"})


def test_render_coerces_non_str_value():
    """值非 str 亦安全 str() 代入（無屬性存取路徑）。"""
    assert _render("n={n}", {"n": 123}) == "n=123"


def test_render_strips_cr_and_c0_from_param_values():
    """參數值中的 CR 與 C0 控制字元於代入時剝除（縱深防禦，#225）。

    主旨（SUBJECT）是 US9 後台**可編輯**的。目前 seed 的主旨無 {user_name} 佔位、所以沒有
    header injection 路徑；但一旦有人在主旨加入佔位，CR/LF 會讓 stdlib 設定 header 時拋錯、
    整批信變 FAILED。在唯一的代入收斂點處理，不必依賴每個呼叫端都記得驗輸入。
    """
    assert _render("n={n}", {"n": "王\r小明"}) == "n=王小明"
    assert _render("n={n}", {"n": "王\x00小明"}) == "n=王小明"
    assert _render("n={n}", {"n": "王\x1b[31m小明"}) == "n=王[31m小明"
    assert _render("n={n}", {"n": "王\x7f小明"}) == "n=王小明"
    # review 抓到的缺口：C1 全段與 U+2028 / U+2029 也是斷行邊界（UAX #14 class BK）
    assert _render("n={n}", {"n": "王\x85小明"}) == "n=王小明"
    assert _render("n={n}", {"n": "王\x9b小明"}) == "n=王小明"
    assert _render("n={n}", {"n": "王\u2028小明"}) == "n=王小明"
    assert _render("n={n}", {"n": "王\u2029小明"}) == "n=王小明"


def test_render_preserves_newline_and_tab_in_param_values():
    """**不得**剝除 LF / TAB——DM 的退回 / 廢止理由是真的多行使用者輸入。

    `dm/review/center_service.py` 與 `dm/obsolete/service.py` 把理由當範本參數傳入，而前端
    `DmReviewPage` / `DmObsoleteDialog` 的輸入框是 multiline。若在此處全域剝換行，DM 通知信
    裡的理由會被壓平——那是弄壞別的模組的功能。

    「內文被插入假訊息」那條由輸入端的姓名型別擋（見 test_dp_schema_safe_name.py），因為姓名
    本質單行、理由本質多行，只有輸入端分得清這個差別。
    """
    assert _render("r={r}", {"r": "第一行\n第二行"}) == "r=第一行\n第二行"
    assert _render("r={r}", {"r": "欄一\t欄二"}) == "r=欄一\t欄二"
    # CRLF 正規化為 LF（丟 CR、留 LF），多行結構保留
    assert _render("r={r}", {"r": "第一行\r\n第二行"}) == "r=第一行\n第二行"


@pytest.mark.parametrize(
    ("channel", "expected"),
    [("EMAIL", True), ("BOTH", True), ("MSG", False)],
)
def test_channel_allows_email(channel, expected):
    """僅 EMAIL / BOTH 寄 Email；MSG（純站內）不寄。"""
    assert _channel_allows_email(channel) is expected


def test_render_subject_mode_strips_newline_too():
    """主旨模式（single_line=True）**連 LF 一併剝**——主旨本質單行，保留會壞事。

    stdlib 的 `EmailMessage.__setitem__` 對含斷行的 header 直接拋 ValueError，該例外被 worker 吞掉、
    retry 到上限後標 FAILED → **該批通知信永久寄不出去**，錯誤只留在 DP_EMAIL_LOG.ERROR_MSG。

    這條路徑現在就可觸發：DM 的 9 支內建範本主旨含 `{doc_name}` 佔位，而 doc_name 只做 strip、
    無 pattern，任何已認證的 DM 編輯者把文件命名為含換行即可讓該文件所有通知信永久失敗。
    """
    assert _render("【簽核】{doc_name} 待審", {"doc_name": "月報\n測試"}, single_line=True) == "【簽核】月報測試 待審"
    assert _render("s={v}", {"v": "a\u2028b"}, single_line=True) == "s=ab"
    assert _render("s={v}", {"v": "a\x85b"}, single_line=True) == "s=ab"
    # TAB 是合法的 header 摺行空白，維持保留
    assert _render("s={v}", {"v": "a\tb"}, single_line=True) == "s=a\tb"


def test_render_body_mode_is_the_default():
    """內文模式為預設（不必傳參數），且維持保留 LF——DM 的多行理由不得被壓平。"""
    assert _render("r={r}", {"r": "第一行\n第二行"}) == "r=第一行\n第二行"
