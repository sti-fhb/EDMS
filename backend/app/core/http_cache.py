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

判準的覆蓋範圍由 `tests/unit/test_file_response_cache_coverage.py` 掃 AST 釘住：
`app/` 下每個 `FileResponse(...)` / `StreamingResponse(...)` 呼叫都必須帶本常數。

> 實測經過、DevTools 證據與 #441（同類缺陷的第一次）的關聯見 issue #587——那些是**當時的
> 狀態**，寫進程式碼會過期。
"""

from types import MappingProxyType
from typing import Final, Mapping

#: 權限相依回應的快取指示。`private` 擋中介快取、`no-store` 擋瀏覽器自身儲存。
#:
#: ⚠️ 套用前先問：**這個 URL 對不同使用者是不是同一個？** 是 → 需要本標頭。
#: 唯一的例外形狀是「URL 本身即憑證」（如 ET 影片票 `?t=`），此時不同人就是不同 URL；
#: 但那一支仍設本標頭，因為中介 proxy 會認為它可快取。
#: ⚠️ 以 `MappingProxyType` 包裝：`Final` 只鎖綁定、不鎖內容，而這是全站共用的單一物件——
#: 任何一處 `NO_STORE_HEADERS["x"] = ...` 都會改到所有端點。
NO_STORE_HEADERS: Final[Mapping[str, str]] = MappingProxyType({"Cache-Control": "private, no-store"})
