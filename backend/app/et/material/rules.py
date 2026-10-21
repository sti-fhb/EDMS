"""ET 教材之純業務規則（#203）。

集中於此而非散在 service：不需 DB、可獨立以 unit test 驗證。Service 負責取資料與
寫入，判斷交給本模組（比照 `app/et/course/rules.py`）。

錯誤訊息一律不嵌入動態值（文件編號、教材名稱等），對齊 `sti-error-codes`。
"""

import re
from collections.abc import Callable, Iterable
from typing import Final

from app.core.exceptions import AppError


def ensure_video_name_unused(*, existing_names: set[str], file_name: str) -> None:
    """同一教材不可上傳**同名**影片。

    ## 為何以檔名而非內容雜湊判定

    雜湊比較準（改名也擋得住），但要在 `ET_MATERIAL_VIDEO` 加欄位並同步 data-model。
    以檔名判定則不動 schema，且**對使用者好解釋**——教材裡的影片清單顯示的就是檔名，
    「已經有一支叫這個名字的影片了」看一眼就懂。

    代價是把同一支影片改名後仍可重複上傳。那是使用者的明確動作，不是誤觸。

    ## 為何在檔案落地之前檢核

    影片單檔上限 500 MB。等寫完再發現重複，等於白做一次 500 MB 的 I/O，而使用者
    也白等。檔名在請求一進來就拿得到，沒有理由拖到後面。

    Args:
        existing_names: 該教材現有（未刪除）影片之原始檔名。
        file_name: 本次上傳之原始檔名。

    Raises:
        AppError: 409 `ET_MATERIAL_005`，該教材已有同名影片。
    """
    if file_name in existing_names:
        raise AppError(
            status_code=409,
            detail="此教材已有同名影片，請先移除原有影片或改用其他檔名",
            error_code="ET_MATERIAL_005",
        )


def ensure_material_has_media(*, has_video: bool, has_doc: bool, has_description: bool) -> None:
    """教材三類媒材**至少擇一有值**方可存檔（`data-model.md` §ET_MATERIAL 業務規則）。

    ## 檢核時點是「儲存」，不是「建立」

    新增項目時會先建立空殼教材（三者皆空）——使用者剛開視窗、還沒填任何東西。若在
    建立時就檢核，視窗根本開不起來。故空殼合法，**存檔時**才要求有實質內容。

    ## 為何空教材不能放行

    空教材在學員端是一個點進去什麼都沒有的項目，且它仍會計入章節的完成條件——
    學員無從「完成」一個沒有內容的教材，章節因此永遠解不了鎖。

    Raises:
        AppError: 422 `ET_MATERIAL_002`，三類媒材皆空。
    """
    if not (has_video or has_doc or has_description):
        raise AppError(
            status_code=422,
            detail="教材須至少提供影片、文件或說明文字其中一項",
            error_code="ET_MATERIAL_002",
        )


#: 孤兒影片檔的寬限期（#775）：最後修改超過這麼久、又沒有任何資料列指向，才視為孤兒。
#:
#: 上傳流程是「先落檔、後寫列」（見 `storage.promote` 的不對稱說明），而那一列要等請求結束
#: 才 commit——一支 500 MB 的影片從落檔到 commit 之間可能隔好幾分鐘。寬限期擋的是這段
#: 空窗：掃描當下剛落地、列還沒提交的檔，不可被當成孤兒。取一天：遠大於任何上傳的耗時，
#: 且排程每日跑一次，孤兒最多多留一天。
ORPHAN_GRACE_SECONDS: Final = 24 * 60 * 60

#: 單次清理最多刪幾支（#775 code review MEDIUM「斷路器」）。
#:
#: 白名單查詢有 bug、連到錯的 DB、DB 還原成舊備份時，大部分檔案會同時變成「沒有列指向」。
#: 上限讓那種情況一天只損失有限的檔，而 log 的筆數會先讓人發現不對勁；正常的孤兒量
#: （教師放棄的上傳）一天遠低於此，積壓的舊孤兒則分幾天清完。
MAX_ORPHAN_DELETES_PER_RUN: Final = 200

#: 系統自己產生的檔名（`storage.promote` 與 `save_video_stream`）：`{數字目錄}/{uuid hex}.{副檔名}`
#: 與 `.tmp/{uuid hex}.{副檔名}`。**只有這兩種會被清**——根目錄是 bind mount，裡面若有人手放
#: 的檔、`lost+found`，或根目錄被誤設到別的資料夾，那些都不是本作業該碰的東西。
_MANAGED_PATH = re.compile(r"^(?:\d+|\.tmp)/[0-9a-f]{32}\.[A-Za-z0-9]{1,10}$")


def is_managed_video_path(rel_path: str) -> bool:
    """`rel_path`（`/` 分隔）是否為系統產生的影片檔或上傳暫存檔。"""
    return bool(_MANAGED_PATH.match(rel_path))


def select_orphans(
    files: Iterable[tuple[str, float]],
    *,
    referenced: set[str],
    now: float,
    key: Callable[[str], str] = lambda p: p,
) -> list[str]:
    """從儲存目錄的檔案清單挑出孤兒（#775），**最舊的在前**、至多 `MAX_ORPHAN_DELETES_PER_RUN` 支。

    Args:
        files: `(相對於儲存根目錄的路徑, 最後修改時間 epoch 秒)`。
        referenced: 所有資料列指向的路徑，**已用 `key` 正規化**。
        now: 現在時刻（epoch 秒）。
        key: 把列舉到的路徑正規化成與 `referenced` 同一格式的函式。呼叫端以「解析成根目錄下的
            實際路徑」比對（`storage.path_key`），絕對路徑的歷史資料、反斜線分隔、Windows 大小寫
            才比得起來；只比字串的話，那些列指向的檔會被當成孤兒刪掉。

    Returns:
        應刪除的相對路徑（`/` 分隔）。非系統產生的檔名一律不在內。
    """
    candidates: list[tuple[float, str]] = []
    for path, mtime in files:
        normalized = path.replace("\\", "/")
        if not is_managed_video_path(normalized):
            continue
        if key(normalized) in referenced:
            continue
        if now - mtime <= ORPHAN_GRACE_SECONDS:
            continue
        candidates.append((mtime, normalized))
    candidates.sort()
    return [path for _, path in candidates[:MAX_ORPHAN_DELETES_PER_RUN]]
