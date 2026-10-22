"""上傳端點在解析 body 之前先驗登入憑證（#810 第 1 項）。

## 為什麼不能只靠身分驗證的 dependency

FastAPI 處理請求時**先解析 body**（multipart 為 `await request.form()`），之後才跑
`solve_dependencies`——`get_jwt_payload`、router 層的角色閘都在那一步。未登入者因此能讓後端
先收下整份上傳（DM 最多 51MB、ET 影片最多 501MB，見 `nginx/nginx.conf`）才被 401 擋下；
multipart 的檔案部分超過 1MB 會寫進容器的 `/tmp`，非檔案欄位則留在記憶體，同時 4 個
（nginx `upload_conn`）就是 2GB。

本 middleware 在進路由之前，先驗 token 的**簽章與效期**；沒有或無效就**丟棄 body**、回 401。

## 為什麼丟棄 body 而不是立刻回 401

🔴 2026-10-22 以官方 nginx（上傳 location 串流不緩衝）＋ uvicorn 實測：不讀 body 直接回 401 時，
uvicorn 送完回應就關連線，而 nginx 還在轉送 body，於是判定上游出錯、**對客戶端回 502**——
前端看到「伺服器處理失敗（HTTP 502）」而不是「請重新登入」。直連 uvicorn 才是乾淨的 401。

改為逐塊讀完、不保留任何內容再回 401：不解析、不落地、記憶體只佔一塊的大小，擋掉「撐爆記憶體
與磁碟」的目的照樣達成；代價是對方的資料仍要傳完（頻寬），由 nginx 的上傳併發上限與 body 上限封頂。
⛔ 不要為了「省頻寬」改回不讀 body 就回應——那會讓所有過期 token 的上傳都變成 502。

## 只驗 token、不查 DB

帳號停用、鎖定、已刪除等檢查仍由原本的 `get_jwt_payload` 負責，本層不重做：
- 這裡的目的是擋「未登入」，不是取代授權；擋得到未登入者已達成目的
- 查 DB 要借連線，連線池耗盡時反而會讓上傳排隊

所以**任何角色**的有效登入憑證（學員、停用中的帳號亦然）仍能讓後端解析完 body，才由角色閘或
`get_jwt_payload` 擋下——本層只擋「未登入」。這是已知的殘餘風險（#810 的 security review
建議以「每位使用者同時上傳數」上限收斂，尚未實作）。

## 清單的單一事實來源

`UPLOAD_PATH_PATTERN` 必須與 `nginx/nginx.conf` 的上傳 location 一致，
`tests/unit/test_core_upload_auth_precheck.py` 以 OpenAPI 的路由為準對兩邊做守門。
"""

import json
import re
from typing import Final

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.auth import decode_access_token
from app.core.exceptions import AppError

#: 收檔案的 5 支端點（multipart）。新增上傳端點時，這裡與 nginx 的上傳 location 都要加。
UPLOAD_PATH_PATTERN: Final = re.compile(
    r"^/api/(dm/documents(/[^/]+/(versions(/[^/]+)?|obsolete))?|et/materials/[^/]+/videos)$"
)

#: 只攔有 body 的寫入方法；同路徑的 GET（文件清單、版本清單）照常走原本的身分驗證。
UPLOAD_METHODS: Final = frozenset({"POST", "PUT"})

_UNAUTHORIZED: Final = AppError(status_code=401, detail="登入憑證無效或已逾時，請重新登入", error_code="DP_AUTH_002")


def _bearer_token(scope: Scope) -> str | None:
    """取 `Authorization: Bearer <token>`，解析方式與 FastAPI 的 `HTTPBearer` 相同。

    比照 `fastapi.security.utils.get_authorization_scheme_param`：取第一個 Authorization 標頭、
    以第一個空白切開、token 去頭尾空白、scheme 不分大小寫。兩邊不一致的話，會出現「這裡放行、
    dependency 擋下」的情形——結果雖然一樣是 401，但前者已讓後端解析完 body，正是本層要避免的事。
    """
    for name, value in scope.get("headers", ()):
        if name == b"authorization":
            scheme, _, token = value.decode("latin-1").partition(" ")
            token = token.strip()
            if scheme.lower() != "bearer" or not token:
                return None
            return token
    return None


def _is_authenticated(token: str | None) -> bool:
    if token is None:
        return False
    try:
        decode_access_token(token)
    except AppError:
        return False
    return True


def _route_path(scope: Scope) -> str:
    """路由比對用的路徑：扣掉 `root_path`，與 Starlette 比對路由的方式相同。

    ⚠️ 不扣的話，以子路徑部署（uvicorn `--root-path /edms`）時 `scope["path"]` 帶著前綴，
    本層的 regex 對不上而**整個失效**，路由卻照樣接受請求——測試與 CI 全綠、沒有任何訊號。
    目前 `backend/entrypoint.sh` 沒有設 `--root-path`，這裡是防日後改部署方式。
    """
    path = scope.get("path", "")
    root = scope.get("root_path", "")
    if root and path.startswith(root + "/"):
        return path[len(root) :]
    return path


def _needs_precheck(scope: Scope) -> bool:
    return (
        scope["type"] == "http"
        and scope.get("method", "").upper() in UPLOAD_METHODS
        and UPLOAD_PATH_PATTERN.match(_route_path(scope)) is not None
    )


async def _discard_body(receive: Receive) -> None:
    """逐塊讀完 body 並丟棄（理由見模組說明）；客戶端中途斷線即停止。"""
    more_body = True
    while more_body:
        message = await receive()
        if message["type"] == "http.disconnect":
            return
        more_body = message.get("more_body", False)


async def _send_unauthorized(send: Send) -> None:
    """回應格式與 `main.app_error_handler` 相同，前端照一般 401 處理（重新登入）。"""
    body = json.dumps(
        {"error_code": _UNAUTHORIZED.error_code, "error_message": _UNAUTHORIZED.detail}, ensure_ascii=False
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": _UNAUTHORIZED.status_code,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


class UploadAuthPrecheckMiddleware:
    """上傳端點的寫入請求，未帶有效 token 者丟棄 body 並回 401，不交給路由解析。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not _needs_precheck(scope) or _is_authenticated(_bearer_token(scope)):
            await self.app(scope, receive, send)
            return
        await _discard_body(receive)
        await _send_unauthorized(send)
