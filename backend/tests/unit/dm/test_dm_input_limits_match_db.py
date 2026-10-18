"""輸入上限與 DB 欄位長度的對齊守門（#697）。

`dm/editor/router.py` 的 `_DOC_NAME_MAX` 等常數目前以**註解**宣稱「對齊 DB 的 `String(N)`」。
註解不會變紅：日後有人用 migration 改了欄位長度、或改了 router 其中一邊，都沒有任何測試會擋。

而這兩者不一致的後果是不對稱的：

| 方向 | 後果 |
|---|---|
| 常數 > 欄位 | 界內的輸入通過驗證 → INSERT 撞 `StringDataRightTruncation` → **500**，正是 #697 要消滅的 |
| 常數 < 欄位 | 誤擋合法輸入，使用者被莫名其妙地限制 |

本檔直接從 SQLAlchemy model 讀欄位長度來比對，不複述數字。

⚠️ 不驗的東西：`_CHANGE_SUMMARY_MAX`（1000）與廢止 `_REASON_MAX`（500）**不對應任何欄位長度**
——兩者的 DB 型別都是無界 `Text`，數值是產品裁示（摘要會進發布信內文；廢止原因超過部分改放
附件）。把它們也寫進本檔會製造「這些數字來自 DB」的錯誤印象。
"""

import pytest

from app.dm.document.file_store import MAX_FILE_NAME_LEN
from app.dm.document.models import DmDocument, DmDocVersion
from app.dm.editor.router import _DOC_NAME_MAX, _REVIEWER_ID_MAX, _VERSION_NO_MAX
from app.dm.review.models import DmReview

pytestmark = pytest.mark.unit


def _col_len(model, column_name: str) -> int:
    """取 model 上某欄位的 `String(N)` 長度。"""
    return model.__table__.c[column_name].type.length


@pytest.mark.parametrize(
    ("const", "model", "column", "label"),
    [
        (_DOC_NAME_MAX, DmDocument, "DOC_NAME", "文件名稱"),
        (_VERSION_NO_MAX, DmDocVersion, "VERSION_NO", "版號"),
        (_REVIEWER_ID_MAX, DmDocVersion, "ASSIGNED_REVIEWER", "草稿記住的指定審核者"),
    ],
)
def test_router_上限等於_DB_欄位長度(const, model, column, label):
    assert const == _col_len(model, column), (
        f"{label}：router 的上限 {const} 與 {model.__tablename__}.{column} 的 String({_col_len(model, column)}) 不一致"
    )


def test_檔名上限同時容得下兩條上傳路徑的欄位():
    """`validate_upload` 是文件上傳與廢止附件**共用**的檢核點，一個常數要對上兩個欄位。

    兩欄若不同長，較寬的那邊就會變成漏網的「越界回 500」——而因為檢核是共用的，
    看程式不會察覺只有一邊被保護到。
    """
    doc_len = _col_len(DmDocVersion, "FILE_NAME")
    obs_len = _col_len(DmReview, "OBSOLETE_FILE_NAME")
    assert doc_len == obs_len, f"兩條上傳路徑的檔名欄位不同長（{doc_len} vs {obs_len}），共用上限已不成立"
    assert MAX_FILE_NAME_LEN == doc_len


def test_送審與草稿的審核者欄位長度一致():
    """兩個 `ASSIGNED_REVIEWER` 欄位必須同長。

    ⚠️ **不要把這條讀成「送簽路徑已受保護」**。寫進 `DM_REVIEW.ASSIGNED_REVIEWER` 的值
    並非來自被 `_REVIEWER_ID_MAX` 界住的草稿欄位，而是來自 `editor/schemas.SubmitReq`
    與 `obsolete/router.py` 的 `reviewer_id`——**那兩處目前沒有套用本常數**。它們之所以
    沒出事，是因為 `ReviewService._ensure_assignable_reviewer` 會先查 `DM_USER_ROLE`、
    查不到就 422；那是**巧合的守門、不是設計的守門**（NUL 就穿得過去，見 #697 的 PR 說明）。

    本條只守一件事：兩欄同長，所以 `_REVIEWER_ID_MAX` 這一個常數涵蓋得了兩邊。
    """
    assert _col_len(DmDocVersion, "ASSIGNED_REVIEWER") == _col_len(DmReview, "ASSIGNED_REVIEWER")
