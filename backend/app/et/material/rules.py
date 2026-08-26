"""ET 教材之純業務規則（#203）。

集中於此而非散在 service：不需 DB、可獨立以 unit test 驗證。Service 負責取資料與
寫入，判斷交給本模組（比照 `app/et/course/rules.py`）。

錯誤訊息一律不嵌入動態值（文件編號、教材名稱等），對齊 `sti-error-codes`。
"""

from app.core.exceptions import AppError


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


def ensure_doc_not_duplicated(*, existing_doc_ids: set[str], doc_id: str) -> None:
    """同一教材不可重複引用同一份 DM 文件（`(MATERIAL_ID, DOC_ID)` 邏輯唯一）。

    在應用層先擋而非只靠 DB 索引：資料庫的唯一違規會冒成 500，且訊息對使用者無意義。

    > 註：DB 端之 `UX_ET_MATERIAL_DOC_MATERIAL_DOC` 已於本 issue 改為**部分**唯一索引
    > （`WHERE DELETED = 0`）。原本的全表唯一約束會讓「引用 → 刪除 → 再引用同一份」
    > 永久失敗，且錯誤指向一筆使用者看不見的已刪資料。此處的 `existing_doc_ids`
    > 同樣只涵蓋未刪除者，兩邊語意一致。

    Raises:
        AppError: 409 `ET_MATERIAL_005`，該文件已被本教材引用。
    """
    if doc_id in existing_doc_ids:
        raise AppError(
            status_code=409,
            detail="同一教材不可重複引用同一份文件",
            error_code="ET_MATERIAL_005",
        )
