"""ET 線下核可紀錄 model（ET_APPROVAL / US16 / #352）。

本表為 ET Foundation（`9aa92b82d0a0`）明文排除的第 29 張表——該 migration 的檔頭寫著
「**不在本 migration**：`ET_APPROVAL`（線下核可）屬 ET Issue #18」，由本 issue 補建。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class EtApproval(BaseModel):
    """線下考核核可紀錄（ET_APPROVAL）。

    一位學員於一門課程 **0～1 筆**：首次核可 INSERT，之後的撤銷 / 重核 / 改判一律
    UPDATE 同一筆（`data-model` §ET_APPROVAL 業務規則、`FR-ET-US16-06`）。

    ## 綜合狀態不存在本表

    畫面上的「未達核可資格 / 待核可 / 已通過 / 未通過」是由**完課狀態 × 本表**即時
    導出的（`approval/rules.derive_approval_status`），`FR-ET-US16-02` 明訂
    **MUST NOT 另存狀態欄位**。本表只記「核可過什麼、被誰撤銷過」。

    ## 🔴 歷程只存在 `DP_AUDIT_LOG`，不在本表

    因 `(COURSE_ID, USER_ID)` 唯一而以 update 覆寫，**前一次的結果在本表被蓋掉之後就
    不存在了**。`data-model` 因此明訂完整歷程（含撤銷後重核所覆寫的前次結果）另寫入
    平台 `DP_AUDIT_LOG`（`FUNC_NAME=ET-APPROVAL`）。

    也就是說核可 / 撤銷的稽核寫入**不是慣例性的附加動作**——漏寫等於那段歷史永久消失，
    而本表看起來一切正常。service 層每一條寫入路徑都必須帶前值與後值。

    ## 核可獨立於完課

    `FR-ET-US16-09`：本表不影響 `ET_ENROLLMENT.COMPLETION_STATUS`、完課率、平均成績、
    課後問卷開放與週報統計。教師新增章節致完課回退時本紀錄**不失效**——所以「未完課 +
    RESULT=PASS」是合法狀態，不是資料異常。
    """

    __tablename__ = "ET_APPROVAL"
    # ⚠️ `UQ_ET_APPROVAL_COURSE_USER` 為**全表**唯一，不加 `postgresql_where`。
    #
    # 這與 `ET_ENROLLMENT.UQ_ET_ENROLLMENT_USER_COURSE` 是同一個形狀、同一個理由：
    # `IS_REVOKED` 是**狀態開關**（這筆核可目前作不作數），不是 `DELETED`（這筆資料
    # 不存在了）。`ET_CHAPTER` / `ET_ITEM` / `ET_SURVEY_QUESTION` 那幾次改成部分唯一
    # 索引，排除的都是 `DELETED`，與本表無關。
    #
    # 🚨 不要改成 `postgresql_where=text('"IS_REVOKED" = false')`。改了會讓同一人同一
    # 課出現多列，直接推翻 `data-model` 的「0～1 筆 / 學員 / 課程」，而症狀是 ET03 的
    # 核可欄開始出現重複列、且撤銷後重核會靜默新建一列（`REVOKE_*` 永遠留在舊列上）。
    #
    # 🚨 **也不要替本表加軟刪除路徑**（把 `DELETED` 設為 1），除非同時把這個唯一鍵改成
    # `postgresql_where='"DELETED" = 0'` 的部分唯一索引。本表所有讀寫都濾 `DELETED = 0`，
    # 而 `insert_approval` 的 `ON CONFLICT DO NOTHING` 認的是**全表**唯一鍵——一筆被軟刪
    # 的列會讓該學員的新核可永遠撞上衝突，畫面顯示「待核可」卻怎麼核可都回「已有核可
    # 紀錄」。目前**沒有任何程式碼**會設這個欄位（作廢走 `IS_REVOKED`），所以這是純未來
    # 風險，但它一旦發生沒有任何訊號。
    __table_args__ = (
        PrimaryKeyConstraint("APPROVAL_ID", name="PK_ET_APPROVAL"),
        UniqueConstraint("COURSE_ID", "USER_ID", name="UQ_ET_APPROVAL_COURSE_USER"),
        # 供 US17「依學員姓名查全部學員之核可課程」跨課程查詢——上方唯一鍵以 COURSE_ID
        # 為首欄，只給 USER_ID 的查詢用不到它。
        Index("IX_ET_APPROVAL_USER", "USER_ID"),
    )

    approval_id: Mapped[int] = mapped_column("APPROVAL_ID", BigInteger, Identity(), nullable=False)
    course_id: Mapped[int] = mapped_column(
        "COURSE_ID", BigInteger, ForeignKey("ET_COURSE.COURSE_ID", name="FK_ET_APPROVAL_COURSE"), nullable=False
    )
    #: 學員 `USER_ID`；**邏輯 FK** 指向平台 `DP_USER`，不設 DB 外鍵（跨模組鬆耦合，
    #: 比照 ET 其餘 28 張表）。
    user_id: Mapped[str] = mapped_column("USER_ID", String(20), nullable=False)
    #: `PASS` / `FAIL`（`ET_APPROVAL_RESULT`，值域由應用層把關——本專案無 lookup 表）。
    result: Mapped[str] = mapped_column("RESULT", String(20), nullable=False)
    #: 選填備註（如不通過原因、考核情形）。
    result_note: Mapped[Optional[str]] = mapped_column("RESULT_NOTE", Text, nullable=True)
    is_revoked: Mapped[bool] = mapped_column("IS_REVOKED", Boolean, nullable=False, default=False)
    #: `IS_REVOKED = true` 時必填（應用層檢核，見 `rules.ensure_revoke_reason`）。
    #:
    #: ⚠️ **重核時必須清空本欄與 `REVOKED_*`**：不清的話畫面會出現「已通過」卻帶著
    #: 撤銷原因的列，而那筆撤銷早已被推翻。
    revoke_reason: Mapped[Optional[str]] = mapped_column("REVOKE_REASON", Text, nullable=True)
    approved_by: Mapped[str] = mapped_column("APPROVED_BY", String(20), nullable=False)
    #: 最近一次核可（含撤銷後重核）之時間。
    approved_at: Mapped[datetime] = mapped_column("APPROVED_AT", DateTime(timezone=True), nullable=False)
    revoked_by: Mapped[Optional[str]] = mapped_column("REVOKED_BY", String(20), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column("REVOKED_AT", DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column("VERSION", Integer, nullable=False, default=0)
