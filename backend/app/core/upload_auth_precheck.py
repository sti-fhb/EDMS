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
`get_jwt_payload` 擋下——本層只擋「未登入」。這個殘餘風險以下面兩道收斂：
- 每位使用者同時上傳數上限（本層，#833 A3）
- 表單解析上限，非檔案欄位不再能撐爆記憶體（`upload_form_limits`，#833 A2）

## 每位使用者同時上傳數上限（#833 A3）

以 token 的 `sub` 計數，同一人同時進行中的上傳超過 `UPLOAD_MAX_CONCURRENT_PER_USER` 就丟棄 body、
回 429。nginx 的 `upload_conn` 是**每 IP** 4 個，擋不住「一個帳號從多個 IP 送」；反過來院內多人共用
同一個出口 IP 時，每 IP 上限也會讓不相干的人互卡，所以兩道各管一邊。

- **行程內計數即可**：後端固定單一 worker（`backend/entrypoint.sh` 的 `--workers 1`）。改成多 worker 時
  每個行程各算各的，上限會變成 N 倍——要改用共享的計數
- **上限 2**：前端每個分頁一次只送一支（`CourseEditorPage.handleUploadVideo` 送完才解除 uploading），
  留一個給「另一個分頁」或「DM 與 ET 同時上傳」
- **名額持有到回應結束**，不是 body 傳完：ET 影片在 body 收完後還要寫檔、跑 `ffprobe`。客戶端中途
  斷線時，要等路由讀到 `http.disconnect` 結束才歸還；例外與取消都由 `finally` 歸還

## 清單的單一事實來源

`UPLOAD_PATH_PATTERN` 必須與 `nginx/nginx.conf` 的上傳 location 一致，
`tests/unit/test_core_upload_auth_precheck.py` 以 OpenAPI 的路由為準對兩邊做守門。
"""

import json
import re
from collections import Counter
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

#: 每位使用者同時進行中的上傳數上限（理由見模組說明）。
UPLOAD_MAX_CONCURRENT_PER_USER: Final = 2

_UNAUTHORIZED: Final = AppError(status_code=401, detail="登入憑證無效或已逾時，請重新登入", error_code="DP_AUTH_002")
_TOO_MANY_UPLOADS: Final = AppError(
    status_code=429, detail="同時上傳的檔案過多，請待目前的上傳完成後再試", error_code="COMMON_429"
)


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


def _subject(token: str | None) -> str | None:
    """有效 token 的 `sub`；沒有或無效回 `None`。"""
    if token is None:
        return None
    try:
        return decode_access_token(token).sub
    except AppError:
        return None


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


async def _send_error(send: Send, error: AppError) -> None:
    """回應格式與 `main.app_error_handler` 相同，前端照一般錯誤處理（401 即重新登入）。"""
    body = json.dumps({"error_code": error.error_code, "error_message": error.detail}, ensure_ascii=False).encode()
    await send(
        {
            "type": "http.response.start",
            "status": error.status_code,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


class UploadAuthPrecheckMiddleware:
    """上傳端點的寫入請求：未帶有效 token 回 401、同一人同時上傳過多回 429，兩者都丟棄 body、不交給路由解析。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        #: 進行中的上傳數，以 `sub` 為鍵；歸零即移除，不會隨使用者數累積
        self._in_flight: Counter[str] = Counter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not _needs_precheck(scope):
            await self.app(scope, receive, send)
            return
        sub = _subject(_bearer_token(scope))
        if sub is None or self._in_flight[sub] >= UPLOAD_MAX_CONCURRENT_PER_USER:
            await _discard_body(receive)
            await _send_error(send, _UNAUTHORIZED if sub is None else _TOO_MANY_UPLOADS)
            return
        self._in_flight[sub] += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self._in_flight[sub] -= 1
            if self._in_flight[sub] <= 0:
                del self._in_flight[sub]
