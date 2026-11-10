"""DP04 範本網址僅允許本系統網域（#940）。

系統信以正式寄件人寄出，收件人會信任信中連結。範本主旨與內文中的網址，主機與連接埠須等於
`FRONTEND_BASE_URL`；由系統代入的連結變數（`{reset_link}`、`{COURSE_URL}` 等）寄送時才產生，
不受影響。檢核比照 `ensure_renderable`：變數代入空字串、實跑 `_render` 後再找網址。
"""

import pytest

from app.core.config import settings
from app.core.exceptions import AppError
from app.dp.notify.service import ensure_links_same_site

pytestmark = pytest.mark.unit

_BASE = "https://edms.example.org/edms"
_HOST = "edms.example.org"

#: 對齊 DP 種子 VARIABLES 的真實格式（識別字 + 全形括號說明）
_PWD_RESET_VARS = "user_name（使用者姓名）, reset_link（密碼重設連結）, expiry_minutes（連結有效分鐘數）"


@pytest.fixture(autouse=True)
def _base_url(monkeypatch):
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", _BASE)


def _check(*, subject: str = "主旨", body: str = "內文", variables: str | None = _PWD_RESET_VARS) -> None:
    ensure_links_same_site(subject=subject, body=body, variables=variables)


@pytest.mark.parametrize(
    "body",
    [
        "請點 https://evil.example.com/login 重新登入",
        "請點 http://evil.example.com",
        "HTTPS://EVIL.EXAMPLE.COM/x",  # 協定與主機大寫
        f"https://{_HOST}:8443/edms",  # 同主機、不同連接埠
        f"http://{_HOST}:80.evil.example.com/",  # 主機字串被接長
        f"https://evil.{_HOST}/x",  # 子網域
        f"https://{_HOST}.evil.example.com/x",  # 以本站主機為前綴
        f"https://{_HOST}@evil.example.com/x",  # 帳密前綴，實際主機在 @ 之後
        f"https://user:pw@{_HOST}/x",  # 本站主機也不允許帳密前綴
        f"https://evil.example.com\\@{_HOST}/x",  # 瀏覽器把 \ 當 /，實際主機是 evil
        "//evil.example.com/x",  # 無協定
        "前往 www.evil.example.com 查看",  # www. 開頭
        "ftp://evil.example.com/file",  # 非 http(s) 協定
        f"ftp://{_HOST}/file",  # 本站主機但非 http(s)
        "https://evil.example.com/?r={reset_link}",  # 把連結變數接在外部網址後
        "https://ev{user_name}il.example.com/",  # 網址拆在變數兩側，渲染後才成形
        "https:{user_name}//evil.example.com/",
        "請點https://evil.example.com請",  # 前後緊貼中文
        # --- review 補充（#940）---
        "WWW.EVIL.EXAMPLE.COM",  # www. 大小寫不拘
        "Www.evil.example.com/x",
        ".https://evil.example.com/x",  # 協定前緊貼標點或數字，郵件軟體仍從 https:// 轉連結
        "-https://evil.example.com/x",
        "+https://evil.example.com/x",
        "1https://evil.example.com/x",
        "-www.evil.example.com/x",
        ".www.evil.example.com/x",
        "-//evil.example.com/x",
        "ｈｔｔｐｓ://evil.example.com/x",  # 全形協定
        f"https://{_HOST}。evil.example.com/x",  # 瀏覽器把 U+3002 當成 .，主機被接長
        f"https://{_HOST}．evil．example．com/x",  # 全形句點
        f"https://{_HOST}­evil.example.com/x",  # 軟連字號會被瀏覽器刪掉
        f"https://{_HOST}​.evil.example.com/x",  # 零寬空白
        f"https://{_HOST}{{user_name}}/x",  # 變數緊貼主機：寄送時代入值可把主機接長
        f"//{_HOST}{{user_name}}/x",
        f"[https://{_HOST}](https://evil.example.com)",  # 解析器會拋錯的寫法：應 422，不是 500
        "https://[",
        "只有協定 https:// 沒有主機",  # 主機為空：應 422，不是 500
    ],
)
def test_body_with_external_url_rejected(body):
    with pytest.raises(AppError) as exc:
        _check(body=body)
    assert exc.value.status_code == 422
    assert exc.value.error_code == "DP_MAIL_014"
    # 訊息不嵌入動態值（sti-error-codes）：不得回顯網址或主機
    assert "evil" not in exc.value.detail
    assert _HOST not in exc.value.detail


def test_subject_with_external_url_rejected():
    """主旨與內文分別驗——只驗一邊會漏。"""
    with pytest.raises(AppError) as exc:
        _check(subject="通知 https://evil.example.com", body="內文")
    assert exc.value.error_code == "DP_MAIL_014"


@pytest.mark.parametrize(
    "body",
    [
        f"請點 {_BASE}/reset-password 重設",
        f"https://{_HOST}",
        f"https://{_HOST}/",
        f"https://{_HOST}/edms/et/courses?tab=mine#top",
        f"HTTPS://{_HOST.upper()}/edms",  # 協定與主機大小寫不拘
        f"https://{_HOST}:443/edms",  # 明確寫出預設連接埠
        f"http://{_HOST}/edms",  # http 指向本站主機（不是外洩路徑）
        f"//{_HOST}/edms",
        f"請點 {_BASE}/x，謝謝。",  # 網址後緊接全形標點
        f"（{_BASE}/x）",  # 被全形括號包住
        f"請見 https://{_HOST}.",  # 主機後緊接英文句點（不剝掉會被當成主機的一部分）
        f"(https://{_HOST})",  # 被半形括號包住
        f"[https://{_HOST}]",  # 被方括號包住
        f"請見 {_BASE}/x?name={{user_name}}",  # 變數在查詢字串裡，主機不受影響
        f"ｈｔｔｐｓ://{_HOST}/edms",  # 全形協定、本站主機
    ],
)
def test_body_with_own_url_passes(body):
    _check(body=body)


@pytest.mark.parametrize(
    "body",
    [
        "{user_name} 您好：請點 {reset_link} 重設密碼，連結 {expiry_minutes} 分鐘內有效。",  # 種子形式
        "請點 {reset_link}",
        "沒有任何連結的內文",
        "版本 v1.2 已發布，詳見 3.5 節",  # 含點號但不是網址
        "時間 08:30，路徑 a/b//c",  # 含冒號與斜線但不是網址
        "{{reset_link}}",  # 跳脫後是字面文字
    ],
)
def test_body_without_literal_url_passes(body):
    _check(body=body)


def test_non_one_time_link_variables_pass():
    """一般頁面連結變數（ET COURSE_URL / DM dashboard_link）寄送時才代入本站網址，不受影響。"""
    _check(subject="課程更新", body="請前往 {COURSE_URL}", variables="USER_NAME,COURSE_URL")
    _check(subject="待簽核", body="{dashboard_link}", variables="reviewer_name,dashboard_link")


def test_no_declared_variables():
    _check(subject="主旨", body=f"{_BASE}/x", variables=None)


def test_base_url_port_is_respected(monkeypatch):
    """`FRONTEND_BASE_URL` 帶非預設連接埠時（本機開發），只放行同一連接埠。"""
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "http://localhost:5174")
    _check(body="http://localhost:5174/reset-password")
    with pytest.raises(AppError):
        _check(body="http://localhost:5175/reset-password")
    with pytest.raises(AppError):
        _check(body="http://localhost/reset-password")
