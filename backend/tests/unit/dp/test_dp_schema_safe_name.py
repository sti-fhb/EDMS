"""#225 姓名欄位控制字元收斂 unit 測試（schema 層，不連 DB）。

`user_name` 會直接進通知信**內文**（`ACCOUNT_VERIFY` / `ACCOUNT_INVITE` 範本的 `{user_name}`），
而自助註冊端點是**匿名**的：任何人可用他人 Email 送出、並自填姓名。姓名若可含 `\\r\\n`，攻擊者
就能在一封 SPF/DKIM 全正常、來自本組織網域的信裡插入自選文字（例如「【重要】帳號異常，請至
http://evil.tw 處理」），而受害者不需做任何事就會收到。

姓名本質為單行，故在**輸入端**擋控制字元；多行本來就合法的參數（DM 的退回 / 廢止理由）不受影響
——那條由 `_SafeFormatter` 分層處理，見 `test_dp_notify_service.py`。

四個進入點都套同一型別：匿名註冊、US8 本人改姓名、US4 管理者代建 / 維護。管理者輸入的姓名同樣
會進邀請信內文，故一併收斂（不因「已認證」而放寬）。
"""

import pytest
from pydantic import ValidationError

from app.dp.user.schemas import NameUpdate, RegisterRequest
from app.dp.users.schemas import UserCreate, UserUpdate

pytestmark = pytest.mark.unit

# issue #225 的實際 payload：約 40 字元，塞得進 50 的長度上限
_INJECTION = "X\n\n【重要】帳號異常，請至 http://evil.tw 處理\n"

_BUILDERS = [
    pytest.param(lambda n: RegisterRequest(email="a@b.co", user_name=n), id="RegisterRequest"),
    pytest.param(lambda n: NameUpdate(user_name=n), id="NameUpdate"),
    pytest.param(lambda n: UserCreate(email="a@b.co", user_name=n), id="UserCreate"),
    pytest.param(lambda n: UserUpdate(user_name=n), id="UserUpdate"),
]


@pytest.mark.parametrize("build", _BUILDERS)
@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(_INJECTION, id="信件內文注入"),
        pytest.param("王\n小明", id="LF"),
        pytest.param("王\r小明", id="CR"),
        pytest.param("王\r\n小明", id="CRLF"),
        pytest.param("王\t小明", id="TAB"),
        pytest.param("王\x00小明", id="NUL"),
        pytest.param("王\x1b[31m小明", id="ANSI-escape"),
        pytest.param("王\x7f小明", id="DEL"),
        # 以下四個是 review 抓到的缺口：只擋 C0 + DEL 會讓它們過關，而 str.splitlines() 與
        # Python 的 email 模組都把 U+0085 / U+2028 / U+2029 當斷行邊界（UAX #14 class BK）
        pytest.param("王\x85小明", id="NEL-U+0085"),
        pytest.param("王\u2028小明", id="LINE-SEPARATOR-U+2028"),
        pytest.param("王\u2029小明", id="PARAGRAPH-SEPARATOR-U+2029"),
        pytest.param("王\x9b小明", id="C1-CSI"),
    ],
)
def test_control_chars_rejected(build, bad):
    """姓名內含控制字元 → 422（ValidationError）。四個進入點行為一致。"""
    with pytest.raises(ValidationError):
        build(bad)


@pytest.mark.parametrize("build", _BUILDERS)
@pytest.mark.parametrize(
    "good",
    [
        pytest.param("王小明", id="中文"),
        pytest.param("王 小明", id="半形空格"),
        pytest.param("山田　太郎", id="全形空格"),
        pytest.param("Ｗａｎｇ", id="全形英文"),
        pytest.param("O'Brien", id="單引號"),
        pytest.param("Mary-Jane", id="連字號"),
        pytest.param("Anne-Marie O'Neill Jr.", id="複合姓名"),
        pytest.param("陳（代理）", id="全形括號"),
    ],
)
def test_legitimate_names_accepted(build, good):
    """真人姓名常見寫法不得被誤擋——收斂過頭比不收斂更糟（使用者無法註冊且訊息不指向原因）。"""
    assert build(good).user_name == good


@pytest.mark.parametrize("build", _BUILDERS)
def test_surrounding_whitespace_still_stripped(build):
    """前後空白（含換行）維持既有的 strip 行為：strip 後不含控制字元即放行。"""
    assert build("\n  王小明  \n").user_name == "王小明"


@pytest.mark.parametrize("build", _BUILDERS)
def test_empty_after_strip_rejected(build):
    """全為空白 → strip 後為空 → 仍受 min_length=1 約束（既有行為不變）。"""
    with pytest.raises(ValidationError):
        build("   ")


@pytest.mark.parametrize("build", _BUILDERS)
def test_bidi_override_deliberately_allowed(build):
    """雙向覆寫（U+202E）**刻意放行**：那屬顯示欺騙（同形字）議題、與信件結構無關，
    且部分書寫系統的正常姓名會用到格式字元，一併擋會誤傷真人姓名。

    本條存在的目的是把「刻意」寫成可執行的紀錄——否則日後有人看到它能通過，會誤判為漏洞而收緊，
    連帶擋掉合法姓名。
    """
    assert build("王\u202e小明").user_name == "王\u202e小明"


@pytest.mark.parametrize("build", _BUILDERS)
def test_same_line_injection_still_possible_by_design(build):
    """⚠️ 本型別**不**消除信件內文注入，只降低保真度——這條測試把該限制釘成紀錄。

    姓名上限 50 字元，攻擊者仍可放入同一行的完整句子；範本內文首行為 `{user_name} 您好：`，
    故下面這個 payload 會渲染成一句看似系統訊息的文字。要真正消除須改範本設計或不回顯使用者
    自填姓名（產品決策），不是輸入驗證能解的。

    #225 的收尾摘要因此應寫「降低可信度」而非「關閉內文注入」。
    """
    payload = "帳號異常請立即至 http://evil.tw 重設密碼"
    assert len(payload) <= 50
    assert build(payload).user_name == payload
