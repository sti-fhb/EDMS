"""ET 教材 model（ET_MATERIAL / ET_MATERIAL_VIDEO / ET_MATERIAL_DOC）。

教材為獨立聚合：自有 `VERSION`（樂觀鎖）、自有 1:N 子表（影片、DM 文件引用），
且承載檔案上傳與跨模組（DM）整合。故 CRUD 生命週期歸屬本子模組，model 亦隨之
置於此（per `sti-backend-modules`「models.py 放在擁有該 Table CRUD 生命週期的
子模組下」）。

> 2026-08-25（#203）自 `app/et/course/models.py` 移入。#185 建表時三者與課程 /
> 章節 / 項目同置於 `course/`，但教材 CRUD 於本 issue 才建立——留在 `course/`
> 會使該子模組同時扛課程、標籤、章節、項目、教材五種聚合。
> `ET_ITEM` 仍留在 `course/`：它是章節的排序子項，屬課程聚合（比照 #202 對
> `ET_CHAPTER` 的處置）。其對本表之 FK 以字串宣告，不需 Python 匯入。

三類媒材於 2026-08-19（#179）自暫時欄位正式拆為 1:N 子表：原
`ET_MATERIAL.VIDEO_FILE_PATH`（單一路徑）與 `DM_DOC_IDS`（CSV 字串）存不下多支
影片，亦無法承載逐支影片之長度與順序（覆蓋率判定必需）。
"""

from typing import Optional

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class EtMaterial(BaseModel):
    """教材內容（ET_MATERIAL）——媒材容器。

    三類媒材皆可選填且可組合：影片見 `ET_MATERIAL_VIDEO`（0..N）、DM 文件見
    `ET_MATERIAL_DOC`（0..N）、說明文字為本表 `DESCRIPTION_HTML`。
    三者**至少擇一有值**方為有效教材（應用層檢核；空教材不得存檔）。
    """

    __tablename__ = "ET_MATERIAL"
    __table_args__ = (PrimaryKeyConstraint("MATERIAL_ID", name="PK_ET_MATERIAL"),)

    material_id: Mapped[int] = mapped_column("MATERIAL_ID", BigInteger, Identity(), nullable=False)
    material_name: Mapped[str] = mapped_column("MATERIAL_NAME", String(100), nullable=False)
    description_html: Mapped[Optional[str]] = mapped_column("DESCRIPTION_HTML", Text, nullable=True)
    version: Mapped[int] = mapped_column("VERSION", Integer, nullable=False, default=0)


class EtMaterialVideo(BaseModel):
    """教材影片（ET_MATERIAL_VIDEO，2026-08-19 新增）。

    `DURATION_SEC` 為**覆蓋率公式之分母**（覆蓋率 = 已觀看區段聯集秒數 ÷ DURATION_SEC），
    故 NOT NULL：上傳時由系統自檔案 metadata 取得並寫入，**取得失敗不得存檔**——
    否則該影片覆蓋率永遠算不出、章節永久無法解鎖。

    刪除採軟刪除；學員於該影片之 `ET_PROGRESS_VIDEO` / `ET_PROGRESS_INTERVAL`
    **亦連帶軟刪除**（`DELETED=1`；2026-08-24 #202 變更，原為 hard delete——
    刪除影片是編輯已發布課程的常規操作，而學員觀看紀錄不可重建）。
    """

    __tablename__ = "ET_MATERIAL_VIDEO"
    __table_args__ = (
        PrimaryKeyConstraint("VIDEO_ID", name="PK_ET_MATERIAL_VIDEO"),
        Index(
            "UX_ET_MATERIAL_VIDEO_ORDER",
            "MATERIAL_ID",
            "SORT_ORDER",
            unique=True,
            postgresql_where=text('"DELETED" = 0'),
        ),
    )

    video_id: Mapped[int] = mapped_column("VIDEO_ID", BigInteger, Identity(), nullable=False)
    material_id: Mapped[int] = mapped_column(
        "MATERIAL_ID",
        BigInteger,
        ForeignKey("ET_MATERIAL.MATERIAL_ID", name="FK_ET_MATERIAL_VIDEO_MATERIAL"),
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column("FILE_PATH", String(500), nullable=False)
    file_name: Mapped[str] = mapped_column("FILE_NAME", String(200), nullable=False)
    duration_sec: Mapped[int] = mapped_column("DURATION_SEC", Integer, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column("FILE_SIZE_BYTES", BigInteger, nullable=False)
    sort_order: Mapped[int] = mapped_column("SORT_ORDER", Integer, nullable=False)


class EtMaterialDoc(BaseModel):
    """教材引用之 DM 文件（ET_MATERIAL_DOC，2026-08-19 新增）。

    `DOC_ID` 格式 `DM-{分類碼}-{6位流水號}`（如 `DM-TRAINING-000007`）、**VARCHAR(20)
    非數值型**、且**非 DB 外鍵**——跨模組不設實體外鍵，內容經 SRVDM001 查詢
    （per sti-backend-boundaries）。

    僅存編號、不存內容與版本號：恆以 SRVDM001 取當前發布版，DM 發布新版 ET 自動
    取得最新版（無快取延遲）。
    """

    __tablename__ = "ET_MATERIAL_DOC"
    __table_args__ = (
        PrimaryKeyConstraint("MAT_DOC_ID", name="PK_ET_MATERIAL_DOC"),
        # 部分唯一索引：全表唯一會讓「引用某文件 → 刪除 → 想再引用同一份」永久失敗，
        # 因已軟刪除的列仍佔住 (MATERIAL_ID, DOC_ID)。
        Index(
            "UX_ET_MATERIAL_DOC_MATERIAL_DOC",
            "MATERIAL_ID",
            "DOC_ID",
            unique=True,
            postgresql_where=text('"DELETED" = 0'),
        ),
    )

    mat_doc_id: Mapped[int] = mapped_column("MAT_DOC_ID", BigInteger, Identity(), nullable=False)
    material_id: Mapped[int] = mapped_column(
        "MATERIAL_ID",
        BigInteger,
        ForeignKey("ET_MATERIAL.MATERIAL_ID", name="FK_ET_MATERIAL_DOC_MATERIAL"),
        nullable=False,
    )
    doc_id: Mapped[str] = mapped_column("DOC_ID", String(20), nullable=False)
    sort_order: Mapped[int] = mapped_column("SORT_ORDER", Integer, nullable=False)
