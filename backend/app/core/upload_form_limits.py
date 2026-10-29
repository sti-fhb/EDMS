"""上傳端點的表單解析上限（#833 A2）。

## 為什麼需要

FastAPI 解析 multipart 時呼叫的是不帶參數的 `request.form()`，用 Starlette 的預設上限：
欄位 1000 個、每個**非檔案欄位** 1 MB、檔案 1000 個（每個檔案前 1 MB 也在記憶體）。任何有效帳號
（含學員：角色閘是 dependency，在解析 body **之後**才跑）單一請求能留在記憶體的量，實際由 nginx
的 body 上限封頂：ET 影片路徑約 500 MB。後端容器上限 2 GB（#830），每 IP 同時 4 個上傳就砍掉重啟。

## 怎麼做

`LimitedFormRoute` 在 FastAPI 解析之前，先以較嚴的上限呼叫一次 `request.form(...)`。
Starlette 把解析結果快取在 request 上（`Request._form`），FastAPI 接著呼叫的 `request.form()`
直接拿到快取——所以限制生效、而路由的參數宣告與驗證完全不變。

上限取自合法表單的實際形狀，`tests/unit/test_core_upload_form_limits.py` 以 OpenAPI 推算每支
上傳端點的合法最大欄位數與最長欄位，守住「合法的表單不會被擋」。

## 拒絕前先讀完 body

解析到一半拒絕時 body 還沒讀完；直接回應的話，uvicorn 送完回應就關連線，nginx（上傳 location
串流不緩衝）還在轉送 body。2026-10-29 以官方 nginx ＋ uvicorn 實測：客戶端收到 422 的狀態行，
回應內容卻斷在半途（curl error 18），瀏覽器當成連線錯誤、前端只顯示「系統連線異常」；nginx 記
「WSARecv() failed (10054) while reading upstream」。完全沒讀 body 就回應時則是 502（#817，見
`upload_auth_precheck`）。兩者都讓使用者看不到原因，所以拒絕前把剩下的 body 讀完丟棄。
⚠️ 只有**還沒讀完**才讀：body 已讀到結尾時再 `receive()`，會一直等到客戶端斷線。

## 編碼只接受 utf-8（2026-10-29 security review H-1）

Starlette 拿 Content-Type 的 `charset` 參數對每個欄位名稱與值呼叫 `bytes.decode(charset)`，
同步執行、佔住事件迴圈。編碼名稱沒有白名單，而 CPython 的 `punycode` 解碼是 O(n²)：實測 200 個
64 KB 欄位要 53.7 秒（utf-8 0.01 秒）——後端只有一個 worker，任何有效帳號送一個 13 MB 的請求
就讓全站卡住近一分鐘。nginx 的 415 閘門只比對 `multipart/form-data` 開頭，擋不到參數。
瀏覽器組的 `FormData` 不帶 charset，所以只放行「不帶」與 utf-8。

## 解析錯誤一律回 422

FastAPI 原本以 `except Exception` 把 body 解析的任何錯誤轉成 400；本層的解析跑在那個 `try` 之外，
只攔 Starlette 的 `HTTPException` 的話，格式損毀（python-multipart 拋 `ValueError` 子類）與客戶端
中途斷線（`ClientDisconnect`）會落到 catch-all、變成 500 並記 ERROR log——取消上傳、網路中斷都會
留一筆，攻擊者也能隨意灌（security review M-1）。所以任何解析錯誤都先讀完 body（斷線時已算讀完，
不會再讀）再回 422「上傳表單格式不符」，原本格式損毀是 400。不細分是因為分辨要比對英文訊息字串。
"""

from typing import Final

from fastapi import Request, Response
from fastapi.params import Form
from fastapi.routing import APIRoute
from starlette.formparsers import parse_options_header
from starlette.types import Message

from app.core.exceptions import AppError

#: 合法表單最多的是 DM 新增文件：6 個單值欄位，加上 3 個多值標籤欄各最多 50 個（`_TAG_IDS_MAX`），
#: 共 156 個。留些餘裕；最壞情況的記憶體約 `MAX_FIELDS × MAX_PART_SIZE` ≈ 12.5 MB（解碼與
#: 驗證時的暫時複本，保守估兩倍）。
UPLOAD_MAX_FIELDS: Final = 200

#: 單一非檔案欄位的位元組上限。合法最長的是 DM 變更摘要 1000 字（UTF-8 最多 4 KB）。
UPLOAD_MAX_PART_SIZE: Final = 64 * 1024

#: 每支上傳端點都只收單一檔案。
UPLOAD_MAX_FILES: Final = 1


def _rejected() -> AppError:
    """每次拒絕都建新的例外。

    ⛔ 不可改成模組層級的單一實例：重複 raise 同一個例外物件，`__traceback__` 會一路累積，連帶
    保住每次請求的 frame 與區域變數（request、scope）——持續送超量表單就能讓記憶體緩慢成長，
    正是本模組要防的事（code review 實測連 raise 5 次，traceback 長度 2、4、6、8、10）。
    """
    return AppError(status_code=422, detail="上傳表單格式不符", error_code="COMMON_422")


#: 放行的 `charset`（理由見模組說明）；不帶時 Starlette 預設 utf-8。
_ALLOWED_CHARSETS: Final = frozenset({b"utf-8", b"utf8"})


def _charset_allowed(request: Request) -> bool:
    """⛔ 必須用 **Starlette 解析時用的同一個** `parse_options_header`，不可換成標準函式庫的
    `email.message`：兩者對重複參數的取捨相反——`charset=utf-8; charset=punycode` 標準函式庫讀到
    utf-8、Starlette 讀到 punycode，換掉就能繞過本檢查（2026-10-29 實測）。
    """
    _, params = parse_options_header(request.headers.get("content-type", ""))
    charset = params.get(b"charset")
    return charset is None or charset.lower() in _ALLOWED_CHARSETS


def _is_form_body(route: APIRoute) -> bool:
    """與 FastAPI `get_request_handler` 判定 `is_body_form` 的方式相同（`File` 是 `Form` 的子類）。"""
    return route.body_field is not None and isinstance(route.body_field.field_info, Form)


class _TrackedReceive:
    """包住 `receive`，記錄 body 是否已讀到結尾——決定拒絕時還要不要繼續讀。"""

    def __init__(self, receive) -> None:
        self._receive = receive
        self.body_done = False

    async def __call__(self) -> Message:
        message = await self._receive()
        if message["type"] == "http.disconnect" or not message.get("more_body", False):
            self.body_done = True
        return message

    async def discard_rest(self) -> None:
        while not self.body_done:
            await self()


class LimitedFormRoute(APIRoute):
    """收表單的路由先以 `UPLOAD_MAX_*` 解析一次 body；JSON 等其他路由原樣處理。

    以 `APIRouter(route_class=LimitedFormRoute)` 套用。新增上傳端點時，所在的 router 要設這個
    route class——`test_core_upload_form_limits.py` 的守門會對每支收檔案的端點實際送超量欄位。
    """

    def get_route_handler(self):
        handler = super().get_route_handler()
        if not _is_form_body(self):
            return handler

        async def limited_handler(request: Request) -> Response:
            receive = _TrackedReceive(request.receive)
            # 換一個 receive 被包住的 Request：解析結果快取在**這個**物件上，故後面也要交給它
            limited = Request(request.scope, receive)
            if not _charset_allowed(limited):
                await receive.discard_rest()
                raise _rejected()
            try:
                await limited.form(
                    max_files=UPLOAD_MAX_FILES, max_fields=UPLOAD_MAX_FIELDS, max_part_size=UPLOAD_MAX_PART_SIZE
                )
            except Exception as exc:  # 比照 FastAPI：body 解析的任何錯誤都是請求的錯（理由見模組說明）
                await receive.discard_rest()
                raise _rejected() from exc
            return await handler(limited)

        return limited_handler
