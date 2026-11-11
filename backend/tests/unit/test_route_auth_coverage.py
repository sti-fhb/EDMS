"""全站路由的認證覆蓋掃描（#255）。

## 為什麼需要這支測試

`app/et/learning/router.py` 有一個 `media_router` **刻意不掛 router-level 認證**
（`<video src>` 送不出 `Authorization` header，改以播放票認證）。它與一般 router
共用 `/api/et` 前綴，且 `main.py` 的 `include_router` 夾在二十幾行同樣的呼叫中間
——**從 URL 或 main.py 都看不出哪一支不需要認證**。

新端點若被掛進那個 router，等於預設無認證，而那種遺漏在一般測試裡看不出來：寫測試
的人會帶著憑證去打它。

本檔遍歷實際掛載的路由，斷言每個 `/api/` 端點的依賴鏈都含 `get_jwt_payload`，
**例外必須明列於 allowlist**。如此一來「掛錯 router」會讓 CI 紅，而 allowlist
每長一行都需要 reviewer 明確點頭。
"""

import pytest
from fastapi.routing import APIRoute

from app.core.auth import get_jwt_payload, get_jwt_payload_pwd_exempt
from main import app

pytestmark = pytest.mark.unit

#: 刻意不經 `get_jwt_payload` 的端點。**新增前請確認它真的不需要認證。**
#:
#: 每一條都要寫明理由——這份清單是「無認證端點」的權威清單，不是待辦事項。
_NO_AUTH_ALLOWLIST: dict[tuple[str, str], str] = {
    ("POST", "/api/login"): "登入本身",
    ("POST", "/api/register"): "自助註冊",
    ("POST", "/api/verify-email"): "以信中 token 驗證，尚未有帳號 session",
    ("POST", "/api/resend-verification"): "同上",
    ("POST", "/api/forgot-password"): "忘記密碼，未登入",
    ("POST", "/api/reset-password"): "以信中 token 重設，未登入",
    ("POST", "/api/reset-password/policy"): "重設頁依信中 token 取適用密碼門檻，未登入（#623）",
    ("GET", "/api/version"): "版本資訊，無敏感內容",
    ("GET", "/api/password-policy"): "公開密碼政策，供註冊 / 重設頁渲染提示（登入前即需要）",
    ("POST", "/api/activate-account"): "帳號啟用：匿名、持邀請信連結 token",
    ("POST", "/api/verify-email-change"): "完成 Email 變更：公開、持信中連結 token",
    (
        "GET",
        "/api/et/videos/{video_id}/file",
    ): "ET06 影片串流：`<video src>` 送不出 Authorization header，改以短效播放票（?t=）認證（#255）",
}


def _iter_api_routes() -> list[tuple[APIRoute, tuple]]:
    """展開巢狀路由樹，回 `(route, router_level_dependencies)`。

    ⚠️ 本函式與 `_requires_jwt` 也被 `test_core_upload_auth_precheck.py` 引用（匿名寫入清單的守門），
    改名或搬移時兩邊一起改。

    ⚠️ 本專案的 FastAPI 版本**不攤平路由**：`app.routes` 裡是 `_IncludedRouter`
    包裝物件，子路由在 `original_router.routes`，而 **router-level 的
    `dependencies=[...]` 不在 `route.dependant` 裡**——它在 `include_context.dependencies`。
    只看 `route.dependant` 會讓每個「靠 router-level 掛認證」的端點都被誤判為無認證
    （本專案幾乎全部如此）。
    """
    found: list[tuple[APIRoute, tuple]] = []
    for route in app.routes:
        _walk(route, (), found)
    return found


def _walk(route, inherited: tuple, out: list) -> None:
    if isinstance(route, APIRoute):
        out.append((route, inherited))
        return
    sub = getattr(route, "original_router", None)
    if sub is None:
        return
    ctx = getattr(route, "include_context", None)
    deps = tuple(getattr(ctx, "dependencies", ()) or ())
    for child in sub.routes:
        _walk(child, inherited + deps, out)


def _gated_by(route: APIRoute, inherited: tuple, targets: frozenset) -> bool:
    """依賴鏈（含 router-level dependencies）中是否出現 `targets` 內的任一閘。"""
    # router-level 依賴以 `Depends(...)` 物件形式保存，取其 `.dependency` 比對
    for dep in inherited:
        call = getattr(dep, "dependency", None)
        if call in targets:
            return True
        if call is not None and _dep_tree_contains(call, targets):
            return True
    if route.dependant.call in targets:
        return True
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        if dep.call in targets:
            return True
        stack.extend(dep.dependencies)
    return False


def _requires_jwt(route: APIRoute, inherited: tuple) -> bool:
    """是否需認證——`get_jwt_payload` 與其豁免版皆算（兩者都驗身分，差別在密碼狀態）。"""
    return _gated_by(route, inherited, _AUTH_GATES)


def _is_pwd_exempt(route: APIRoute, inherited: tuple) -> bool:
    """是否走**密碼閘豁免版**（#929）。"""
    return _gated_by(route, inherited, _PWD_EXEMPT_GATE)


def _dep_tree_contains(call, targets: frozenset) -> bool:
    """router-level 依賴多為包裝過的 dependency（如 `get_et_context`）——
    以 FastAPI 解析其子依賴後再比對。"""
    from fastapi.dependencies.utils import get_dependant

    stack = [get_dependant(path="", call=call)]
    while stack:
        dep = stack.pop()
        if dep.call in targets:
            return True
        stack.extend(dep.dependencies)
    return False


#: 兩支都是**認證**閘，差別只在是否一併檢查密碼狀態（#929）。判斷「這支端點需不需要登入」
#: 時兩者等價；判斷「有沒有經過密碼閘」要用 `_PWD_GATE` 單獨比對。
_AUTH_GATES = frozenset({get_jwt_payload, get_jwt_payload_pwd_exempt})
_PWD_EXEMPT_GATE = frozenset({get_jwt_payload_pwd_exempt})


class TestRouteAuthCoverage:
    def test_掃描到的_api_端點數量合理(self) -> None:
        """防呆：若路由展開邏輯壞掉（回 0 條），下面那條測試會**假綠**。"""
        api = [r for r, _ in _iter_api_routes() if r.path.startswith("/api/")]
        assert len(api) > 50, f"只掃到 {len(api)} 個 /api 端點，路由展開邏輯可能失效"

    def test_每個_api_端點都需認證或明列於_allowlist(self) -> None:
        unguarded: list[str] = []
        for route, inherited in _iter_api_routes():
            if not route.path.startswith("/api/"):
                continue
            if _requires_jwt(route, inherited):
                continue
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                if (method, route.path) not in _NO_AUTH_ALLOWLIST:
                    unguarded.append(f"{method} {route.path}")

        assert not unguarded, (
            "以下端點未經 `get_jwt_payload` 且不在 allowlist 內。\n"
            "若確實不需認證，請加入 `_NO_AUTH_ALLOWLIST` 並寫明理由；\n"
            "若是誤掛在無認證的 router 上（如 et/learning 的 media_router），請改掛正確的 router：\n"
            + "\n".join(f"  - {e}" for e in sorted(unguarded))
        )

    def test_allowlist_無過時項目(self) -> None:
        """allowlist 裡的端點若已改為需認證 / 已移除，該條就該刪掉。

        沒有這條檢查，allowlist 會越積越長，最後沒有人知道哪幾條還是真的。
        """
        actual = {
            (method, route.path)
            for route, inherited in _iter_api_routes()
            for method in route.methods - {"HEAD", "OPTIONS"}
            if not _requires_jwt(route, inherited)
        }
        stale = sorted(f"{m} {p}" for (m, p) in _NO_AUTH_ALLOWLIST if (m, p) not in actual)
        assert not stale, "allowlist 有過時項目（端點已需認證或已移除），請刪除：\n" + "\n".join(stale)


#: 刻意**不**經密碼閘（`get_jwt_payload`）而走豁免版的端點。**新增前請確認它真的非放行不可。**
#:
#: 密碼閘把「須變更密碼 / 密碼逾期」的帳號一律擋成 403 `DP_AUTH_009`（#929）。若連改密碼
#: 本身也被擋，使用者就再也出不來——這份清單是那組逃生門的**權威清單**，不是待辦事項。
#:
#: ⛔ 判準是「解決問題或離開所需」，不是「方便」。`PUT /api/dp/user/me`（改姓名）與
#: `PUT /api/dp/user/me/email` **刻意不在此列**：`spec_us8` FR-DP-US8-08 要求完成變更前
#: 不得離開至其他功能，而它們兩者皆非必需。
_PWD_GATE_EXEMPT_ALLOWLIST: dict[tuple[str, str], str] = {
    ("PUT", "/api/dp/user/me/password"): "改密碼本身——擋了即死鎖",
    ("GET", "/api/dp/user/me"): "頂列顯示姓名，擋了畫面壞",
    ("GET", "/api/dp/user/me/password-policy"): "變更表單要顯示「至少 N 字元」",
    ("POST", "/api/dp/user/renew"): "填表期間 token 可能到期，不能換發會打到一半被登出",
    ("POST", "/api/dp/user/logout"): "強制變更頁的「返回登入」會呼叫它",
}


class TestPasswordGateCoverage:
    """密碼閘（#929）的涵蓋面守門。

    🔴 AC 1 說的是「DP 後台、DM、ET 的 API」——逐一為 32 個 router 各寫一條測試不現實，
    而「只測一支」等於沒驗涵蓋面。改由本測試承擔。

    判準是**反過來寫**的：不去證明「每支都有閘」（那等同重寫一次 FastAPI 的依賴解析），
    而是證明「**走豁免版的，恰好就是清單上那幾支**」。密碼閘已內建於 `get_jwt_payload`，
    所以任何需認證、又不在清單上的端點必然經過它。
    """

    def test_走豁免版的端點恰好等於豁免清單(self) -> None:
        actual = {
            (method, route.path)
            for route, inherited in _iter_api_routes()
            if route.path.startswith("/api/")
            if _is_pwd_exempt(route, inherited)
            for method in route.methods - {"HEAD", "OPTIONS"}
        }
        expected = set(_PWD_GATE_EXEMPT_ALLOWLIST)
        extra = sorted(f"{m} {p}" for (m, p) in actual - expected)
        missing = sorted(f"{m} {p}" for (m, p) in expected - actual)
        assert not extra, (
            "下列端點走了密碼閘豁免版但不在清單內——若確實非放行不可，"
            "請連同理由加進 _PWD_GATE_EXEMPT_ALLOWLIST：\n" + "\n".join(extra)
        )
        assert not missing, "豁免清單有過時項目（端點已改走預設閘或已移除），請刪除：\n" + "\n".join(missing)

    def test_掃描到的需認證端點數量合理(self) -> None:
        """防呆：依賴解析若壞掉（全判成未認證），上面那條會**假綠**。"""
        authed = [
            route
            for route, inherited in _iter_api_routes()
            if route.path.startswith("/api/") and _requires_jwt(route, inherited)
        ]
        assert len(authed) > 50, f"只掃到 {len(authed)} 個需認證端點，依賴解析可能失效"
