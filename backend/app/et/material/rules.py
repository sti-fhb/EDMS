"""ET 教材之純業務規則（#203）。

集中於此而非散在 service：不需 DB、可獨立以 unit test 驗證。Service 負責取資料與
寫入，判斷交給本模組（比照 `app/et/course/rules.py`）。

錯誤訊息一律不嵌入動態值（文件編號、教材名稱等），對齊 `sti-error-codes`。
"""

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
