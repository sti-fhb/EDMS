"""全站送檔端點的快取指示覆蓋掃描（#587）。

## 為什麼需要這支測試

檔案回應若不帶 `Cache-Control`，瀏覽器會套用**啟發式快取**（RFC 9111 §4.2.2）並自行
推測新鮮期。而 **HTTP 快取的鍵是 URL、不是使用者**——本專案的送檔端點除影片外都靠
`Authorization` header 區分身分，URL 對所有人完全相同，於是：

- 共用電腦上 A 下載過之後，B 按下載會**直接拿到 A 的快取**，請求不送達伺服器
- `dm/detail` 那支因此**不寫 `DM_DOC_READ`** → DM06 閱讀率系統性低報

2026-10-12 於部署環境實測：同一位使用者、同一個 URL、同一版本，瀏覽器下載不計入、
API 下載計入；DevTools 顯示 `200 OK (from disk cache)`。

這是 #441（`index.html` 缺 `Cache-Control`）**同一類缺陷的第二次**——那次只修了
`index.html`，沒有盤點其他回應。本檔的目的是讓第三次不會發生：**新增送檔端點時，
若沒在下方登記，CI 會紅**。

⚠️ 本檔只保證「送檔端點的集合沒有在無人察覺下長大」。**實際標頭由 integration
測試驗**（`tests/integration/dm/test_dm_detail.py`、`test_dm_obsolete_flow.py`、
`tests/integration/et/test_et_learning.py`），兩者缺一不可：少了這支，新端點會悄悄
漏掉；少了那些，標頭寫錯也不會有人發現。
"""

import pytest
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute

from main import app

pytestmark = pytest.mark.unit

#: 回傳檔案實體的端點，與其快取指示之判定理由。**新增前請確認真的處理了快取。**
#:
#: 判準：**回應內容取決於「誰在問」，而 URL 對所有人相同者，一律 `private, no-store`。**
#: 例外只有一種——URL 本身即憑證（如影片票 `?t=`），此時不同人就是不同 URL，
#: URL 鍵的快取不會跨人洩漏；但那一支基於另一個理由（中介 proxy 會認為可快取）
#: 同樣設了 `no-store`。
_FILE_ENDPOINTS: dict[tuple[str, str], str] = {
    ("GET", "/api/dm/documents/{doc_id}/versions/{version_id}/file"): (
        "DM07 文件檔案：URL 全使用者相同、靠 Bearer 區分；且 download 會寫 DM_DOC_READ，"
        "被快取攔下會讓閱讀率低報（#587 本體）"
    ),
    ("GET", "/api/dm/reviews/{review_id}/versions/{version_id}/file"): (
        "簽核待審檔：僅該送審之指定審核者可取，URL 全使用者相同"
    ),
    ("GET", "/api/dm/reviews/{review_id}/obsolete-file"): (
        "廢止附件：僅 DM_ADMIN 或該送審之指定審核者可取，URL 全使用者相同"
    ),
    ("GET", "/api/et/materials/{material_id}/docs/{doc_id}/file"): (
        "ET 教材引用之 DM 文件：授權由 material_id 那側判定，URL 全使用者相同"
    ),
    ("GET", "/api/et/videos/{video_id}/file"): (
        "ET06 影片串流：票在 query string，URL 因人而異；仍設 no-store 以免中介 proxy "
        "把授權過的內容留在共用快取（#255 既有決定）"
    ),
}


def _iter_api_routes() -> list[APIRoute]:
    """展開巢狀路由樹。

    ⚠️ 本專案的 FastAPI 版本**不攤平路由**：`app.routes` 裡是 `_IncludedRouter` 包裝物件，
    子路由在 `original_router.routes`（同 `test_route_auth_coverage.py`）。
    """
    found: list[APIRoute] = []

    def walk(route) -> None:
        if isinstance(route, APIRoute):
            found.append(route)
            return
        sub = getattr(route, "original_router", None)
        if sub is None:
            return
        for child in sub.routes:
            walk(child)

    for route in app.routes:
        walk(route)
    return found


def _serves_file(route: APIRoute) -> bool:
    """以回傳型別標註判定是否送檔。

    本專案所有送檔端點皆標註 `-> FileResponse`；漏標的話本檔抓不到，故
    `sti-backend-modules.md` 要求送檔端點必須標註回傳型別。
    """
    return route.endpoint.__annotations__.get("return") is FileResponse


def test_送檔端點的集合必須與登記表一致():
    """新增送檔端點而未登記 → 紅。這是本檔存在的唯一理由。

    ⚠️ `actual` 只由 `_serves_file` 產生，**刻意不混入登記表自身**：混入的話
    「偵測不到任何端點」也會讓本條通過（missing 恆空），守門就成了恆真。
    """
    actual = {
        (method, r.path) for r in _iter_api_routes() if _serves_file(r) for method in r.methods if method != "HEAD"
    }
    expected = set(_FILE_ENDPOINTS)

    # 偵測機制自身的健康檢查：一個都抓不到 ⇒ 回傳型別標註或路由走訪壞了，而非真的沒有端點
    assert actual, "未偵測到任何送檔端點——`_serves_file` 或 `_iter_api_routes` 可能已失效"

    missing = expected - actual
    extra = actual - expected
    assert not missing, f"登記表有，實際卻偵測不到（路徑改了？或漏標 `-> FileResponse`）：{sorted(missing)}"
    assert not extra, (
        f"發現未登記的送檔端點：{sorted(extra)}。\n"
        "請確認它是否需要 Cache-Control（判準見本檔 _FILE_ENDPOINTS 的註解），"
        "處理後再登記於該表並寫明理由。"
    )


def test_每個登記項都要寫理由():
    """理由欄留空等於沒登記——這張表是權威清單，不是待辦事項。"""
    for key, reason in _FILE_ENDPOINTS.items():
        assert reason.strip(), f"{key} 缺少登記理由"
