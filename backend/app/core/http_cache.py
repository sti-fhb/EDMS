"""回應快取指示（#587）。

## 判準

**回應內容取決於「誰在問」，而 URL 對所有人相同者，一律 `NO_STORE_HEADERS`。**

理由是 **HTTP 快取的鍵是 URL，不是使用者**。本專案的送檔端點靠 `Authorization` header
區分身分，URL 卻對所有人完全相同，於是共用電腦上 A 取過的檔會被快取，B 的請求根本
不送達伺服器——他拿到 A 的內容，而伺服器不知道他來過。

後果有兩層，第二層比第一層嚴重：

1. 授權過的內容留在共用快取裡
2. **請求沒送達，等於端點的副作用沒有發生**——`dm/detail` 的下載會寫 `DM_DOC_READ`，
   被快取攔下就不會寫，DM06 閱讀率因此系統性低報。文件管制的用途正是證明「誰讀過
   現行 SOP」，而低報會讓稽核得到「大家都沒讀」的錯誤結論，反而掩蓋真正沒讀的人

## 為什麼是 `no-store` 而不是 `no-cache`

`no-cache` 仍允許**儲存**，只要求使用前重新驗證；而重新驗證可能回 `304` 且不帶 body。
要確保每次都真的執行 handler（寫閱讀紀錄），必須 `no-store`。

## 我們依賴的是什麼

- **共享 / 中介快取**：RFC 9111 §3.5 本來就擋——帶 `Authorization` 的請求，回應沒有
  `public` / `s-maxage` / `must-revalidate` 時**不得儲存**。
- **瀏覽器私有快取**：§3.5 管不到。現行瀏覽器在沒有 validator 時實務上會重抓，但那是
  **實作行為，不是規範保證**；`FileResponse` 又自動帶 `Last-Modified` / `ETag`，等於
  親手把 validator 交出去。所以**不能賭**，一律 `no-store`。

⚠️ 不要用「這個回應沒有 `Last-Modified`，所以不會被啟發式快取」當豁免理由。RFC 9111
§4.2.2 把 `Last-Modified` 寫成 example（"such as"）而非 precondition——真正的門檻只有
「無明確新鮮度」+「status code 可啟發式快取」，而 200 就在那份清單裡。

## 範圍

`tests/unit/test_file_response_cache_coverage.py` 掃 AST 釘住：`app/` 下每個
`FileResponse` / `StreamingResponse`，**以及帶 `Content-Disposition` 或 CSV media_type
的 `Response`**（七支匯出端點）都必須帶本常數。共 12 處。

⛔ **本常數擋的是「請求不送達伺服器」這條路徑，不是「共用電腦上看不到別人的檔案」。**
`Content-Disposition: attachment` 的終點是磁碟——下載資料夾裡的實體檔與瀏覽器下載歷程
（含 URL）都不在 HTTP 快取的管轄內，後端無法處理。⚠️ 另：Service Worker 的
`cache.put()` **完全不理會** `no-store`，日後若引入 PWA，這道防線會被整個繞過。

> 實測經過、DevTools 證據與 #441（同類缺陷的第一次）的關聯見 issue #587——那些是**當時的
> 狀態**，寫進程式碼會過期。

## 其餘回應的預設：`DefaultNoStoreMiddleware`（#959）

未自行設定 `Cache-Control` 的回應一律補 `no-store`；已設者（含本常數）原樣保留。
送檔端點仍須自帶本常數，**不得因有預設就拿掉**：本常數多了 `private`，且上面的 AST 守門
以本常數為準。

⚠️ 未涵蓋：未預期例外的 500 / 503（`main.py` 的 `unhandled_exception_handler`）由 Starlette
最外層的 `ServerErrorMiddleware` 直接送出，不經使用者 middleware，因此不帶本預設。內容為
通用錯誤訊息，且 500 / 503 不在啟發式快取的 status code 清單內。nginx 自產、不經後端的
413 / 415 / 502 / 503 / 504（body 超限、格式不符、限流、上游不通）同理不帶本預設。
"""

from types import MappingProxyType
from typing import Final, Mapping

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: 權限相依回應的快取指示。`private` 擋中介快取、`no-store` 擋瀏覽器自身儲存。
#:
#: ⚠️ 套用前先問：**這個 URL 對不同使用者是不是同一個？** 是 → 需要本標頭。
#: 唯一的例外形狀是「URL 本身即憑證」（如 ET 影片票 `?t=`），此時不同人就是不同 URL；
#: 但那一支仍設本標頭，因為中介 proxy 會認為它可快取。
#: ⚠️ 以 `MappingProxyType` 包裝：`Final` 只鎖綁定、不鎖內容，而這是全站共用的單一物件——
#: 任何一處 `NO_STORE_HEADERS["x"] = ...` 都會改到所有端點。
NO_STORE_HEADERS: Final[Mapping[str, str]] = MappingProxyType({"Cache-Control": "private, no-store"})


class DefaultNoStoreMiddleware:
    """回應未自行設定 `Cache-Control` 時補上 `no-store`（#959）。

    以 pure ASGI 實作、只改 `http.response.start` 的標頭，不緩衝 body——送檔端點的
    `FileResponse` / `StreamingResponse` 照常串流。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_default(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if "cache-control" not in headers:
                    headers.append("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_with_default)
