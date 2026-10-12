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

## 實測（2026-10-12，部署環境）

同一位使用者、同一個 URL、同一版本：瀏覽器下載不計入、API 下載計入；DevTools 顯示
`200 OK (from disk cache)`。

## 歷史

#441（`index.html` 缺 `Cache-Control`，使用者跑到快取的舊版前端）是同一類缺陷的第一次，
當時只修了 `index.html`、沒有盤點其他回應，於是 #587 在送檔端點重演。本模組的存在是為了
讓判準有單一出處；覆蓋範圍由 `tests/unit/test_file_response_cache_coverage.py` 釘住。
"""

from typing import Final

#: 權限相依回應的快取指示。`private` 擋中介快取、`no-store` 擋瀏覽器自身儲存。
#:
#: ⚠️ 套用前先問：**這個 URL 對不同使用者是不是同一個？** 是 → 需要本標頭。
#: 唯一的例外形狀是「URL 本身即憑證」（如 ET 影片票 `?t=`），此時不同人就是不同 URL；
#: 但那一支仍設本標頭，因為中介 proxy 會認為它可快取。
NO_STORE_HEADERS: Final[dict[str, str]] = {"Cache-Control": "private, no-store"}
