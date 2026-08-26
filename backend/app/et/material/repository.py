"""ET 教材 Repository（ET_MATERIAL / ET_MATERIAL_VIDEO / ET_MATERIAL_DOC；US3 / #203）。

依 `sti-backend-modules`：Repository 只 `flush()`、不 `commit()`；查詢一律帶
`DELETED = 0`；時間一律 `utcnow()`。更新型方法回傳受影響列數供 service 交給
`ensure_version_matched()` 判定樂觀鎖。
"""

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.material.models import EtMaterial, EtMaterialDoc, EtMaterialVideo
from app.et.progress.models import EtProgressInterval, EtProgressVideo


class EtMaterialRepository:
    """`ET_MATERIAL` 及其兩張子表之存取。"""

    async def create_shell(self, db: AsyncSession, name: str, operator: OperatorInfo) -> EtMaterial:
        """建立空殼教材（三類媒材皆空）。

        空殼於「新增項目 → 教材」時與 `ET_ITEM` 於**同一交易**建立——使用者剛開視窗、
        還沒填任何內容。`ET_MATERIAL_002`（至少擇一媒材）之檢核在**儲存教材**時才套用，
        不在建立時；否則使用者連視窗都開不起來。
        """
        material = EtMaterial(
            material_name=name,
            version=0,
            created_user=operator.user_id,
            created_date=utcnow(),
        )
        db.add(material)
        await db.flush()
        return material

    async def get(self, db: AsyncSession, material_id: int) -> EtMaterial | None:
        return await db.scalar(select(EtMaterial).where(EtMaterial.material_id == material_id, EtMaterial.deleted == 0))

    async def list_videos(self, db: AsyncSession, material_id: int) -> list[EtMaterialVideo]:
        """依 `SORT_ORDER` 列出教材之影片。"""
        rows = await db.scalars(
            select(EtMaterialVideo)
            .where(EtMaterialVideo.material_id == material_id, EtMaterialVideo.deleted == 0)
            .order_by(EtMaterialVideo.sort_order, EtMaterialVideo.video_id)
        )
        return list(rows)

    async def list_docs(self, db: AsyncSession, material_id: int) -> list[EtMaterialDoc]:
        """依 `SORT_ORDER` 列出教材引用之 DM 文件。"""
        rows = await db.scalars(
            select(EtMaterialDoc)
            .where(EtMaterialDoc.material_id == material_id, EtMaterialDoc.deleted == 0)
            .order_by(EtMaterialDoc.sort_order, EtMaterialDoc.mat_doc_id)
        )
        return list(rows)

    async def next_video_order(self, db: AsyncSession, material_id: int) -> int:
        max_order = await db.scalar(
            select(func.max(EtMaterialVideo.sort_order)).where(
                EtMaterialVideo.material_id == material_id, EtMaterialVideo.deleted == 0
            )
        )
        return (max_order or 0) + 1

    async def next_doc_order(self, db: AsyncSession, material_id: int) -> int:
        max_order = await db.scalar(
            select(func.max(EtMaterialDoc.sort_order)).where(
                EtMaterialDoc.material_id == material_id, EtMaterialDoc.deleted == 0
            )
        )
        return (max_order or 0) + 1

    async def update_basic(
        self,
        db: AsyncSession,
        material_id: int,
        version: int,
        *,
        name: str,
        description_html: str | None,
        operator: OperatorInfo,
    ) -> int:
        """更新名稱與說明文字並遞增 `VERSION`；回傳受影響列數供樂觀鎖判定。

        `description_html` 須為**已消毒**之內容——消毒在 service 層完成，Repository
        不做內容轉換（否則「有沒有消毒」會散落在兩處，難以確認每條寫入路徑都經過）。
        """
        result = await db.execute(
            update(EtMaterial)
            .where(
                EtMaterial.material_id == material_id,
                EtMaterial.deleted == 0,
                EtMaterial.version == version,
            )
            .values(
                material_name=name,
                description_html=description_html,
                version=EtMaterial.version + 1,
                updated_user=operator.user_id,
                updated_date=utcnow(),
            )
        )
        await db.flush()
        return result.rowcount

    async def has_video(self, db: AsyncSession, material_id: int) -> bool:
        return bool(
            await db.scalar(
                select(func.count())
                .select_from(EtMaterialVideo)
                .where(EtMaterialVideo.material_id == material_id, EtMaterialVideo.deleted == 0)
            )
        )

    async def has_doc(self, db: AsyncSession, material_id: int) -> bool:
        return bool(
            await db.scalar(
                select(func.count())
                .select_from(EtMaterialDoc)
                .where(EtMaterialDoc.material_id == material_id, EtMaterialDoc.deleted == 0)
            )
        )

    async def add_video(
        self,
        db: AsyncSession,
        material_id: int,
        *,
        file_path: str,
        file_name: str,
        duration_sec: int,
        file_size_bytes: int,
        operator: OperatorInfo,
    ) -> EtMaterialVideo:
        """新增一支影片，追加至最末。

        `duration_sec` 由 service 以 `ffprobe` 取得後傳入——**取不到就不會走到這裡**
        （data-model：取得失敗不得存檔）。Repository 不自行探測：那會讓「有沒有驗過
        長度」散在兩層，且 Repository 不該碰子行程。
        """
        video = EtMaterialVideo(
            material_id=material_id,
            file_path=file_path,
            file_name=file_name,
            duration_sec=duration_sec,
            file_size_bytes=file_size_bytes,
            sort_order=await self.next_video_order(db, material_id),
            created_user=operator.user_id,
            created_date=utcnow(),
        )
        db.add(video)
        await db.flush()
        return video

    async def get_video(self, db: AsyncSession, video_id: int) -> EtMaterialVideo | None:
        return await db.scalar(
            select(EtMaterialVideo).where(EtMaterialVideo.video_id == video_id, EtMaterialVideo.deleted == 0)
        )

    async def soft_delete_video(self, db: AsyncSession, video_id: int, operator: OperatorInfo) -> None:
        """軟刪除單支影片，並連帶軟刪學員於該影片之觀看紀錄。

        **磁碟上的檔案不刪**：軟刪除的語意是「可回復」，把檔案砍掉就回復不了了。
        代價是磁碟空間——需要真正回收時應由清理作業處理已軟刪超過保留期的檔案，
        那是獨立的維運議題，不該混進使用者操作路徑。
        """
        audit = {"deleted": 1, "updated_user": operator.user_id, "updated_date": utcnow()}
        for model in (EtProgressVideo, EtProgressInterval):
            await db.execute(update(model).where(model.video_id == video_id, model.deleted == 0).values(**audit))
        await db.execute(
            update(EtMaterialVideo)
            .where(EtMaterialVideo.video_id == video_id, EtMaterialVideo.deleted == 0)
            .values(**audit)
        )
        await db.flush()

    async def resequence_videos(self, db: AsyncSession, material_id: int, operator: OperatorInfo) -> None:
        """刪除後把剩餘影片之 `SORT_ORDER` 重編為 1..N（**兩階段寫入**）。

        兩階段的理由同章節 / 項目重排：`UX_ET_MATERIAL_VIDEO_ORDER` 為非 deferrable
        之部分唯一索引，逐列即時檢核，直接遞補會在中途撞鍵。
        """
        remaining = await self.list_videos(db, material_id)
        order_map = {v.video_id: i for i, v in enumerate(remaining, start=1)}
        if not order_map:
            return
        now = utcnow()
        for phase_value in (lambda target: -target, lambda target: target):
            for video_id, sort_order in order_map.items():
                await db.execute(
                    update(EtMaterialVideo)
                    .where(EtMaterialVideo.video_id == video_id, EtMaterialVideo.deleted == 0)
                    .values(
                        sort_order=phase_value(sort_order),
                        updated_user=operator.user_id,
                        updated_date=now,
                    )
                )
        await db.flush()

    async def add_doc(self, db: AsyncSession, material_id: int, doc_id: str, operator: OperatorInfo) -> EtMaterialDoc:
        """新增一筆 DM 文件引用，追加至最末。"""
        doc = EtMaterialDoc(
            material_id=material_id,
            doc_id=doc_id,
            sort_order=await self.next_doc_order(db, material_id),
            created_user=operator.user_id,
            created_date=utcnow(),
        )
        db.add(doc)
        await db.flush()
        return doc

    async def get_doc(self, db: AsyncSession, mat_doc_id: int) -> EtMaterialDoc | None:
        return await db.scalar(
            select(EtMaterialDoc).where(EtMaterialDoc.mat_doc_id == mat_doc_id, EtMaterialDoc.deleted == 0)
        )

    async def soft_delete_doc(self, db: AsyncSession, mat_doc_id: int, operator: OperatorInfo) -> None:
        """軟刪除單筆文件引用（AC 4：廢止文件僅可逐筆刪除、不提供批次移除）。

        刪除後**可再次引用同一份文件**——`UX_ET_MATERIAL_DOC_MATERIAL_DOC` 已改為部分
        唯一索引，已刪除的列不再佔住 `(MATERIAL_ID, DOC_ID)`。
        """
        await db.execute(
            update(EtMaterialDoc)
            .where(EtMaterialDoc.mat_doc_id == mat_doc_id, EtMaterialDoc.deleted == 0)
            .values(deleted=1, updated_user=operator.user_id, updated_date=utcnow())
        )
        await db.flush()

    async def soft_delete_cascade(self, db: AsyncSession, material_ids: list[int], operator: OperatorInfo) -> None:
        """軟刪除教材本體與其下影片、文件引用，及學員之觀看紀錄。

        連帶範圍（**全部軟刪除**）：

        1. `ET_MATERIAL_VIDEO` / `ET_MATERIAL_DOC` — 教材之媒材
        2. `ET_PROGRESS_VIDEO` / `ET_PROGRESS_INTERVAL` — 學員於該等影片之觀看覆蓋率與區段

        > 學員紀錄採軟刪除而非 hard delete（2026-08-24 #202 裁示）：刪除是編輯**已發布**
        > 課程的常規操作，而觀看紀錄不可重建。代價是統計端務必排除 `DELETED = 1`。

        影片之學員紀錄以 `VIDEO_ID` 關聯（非 `MATERIAL_ID`），故須先查出影片 ID 再刪——
        直接以 `MATERIAL_ID` 刪 `ET_PROGRESS_VIDEO` 會因該表無此欄位而漏掉。
        """
        if not material_ids:
            return
        now = utcnow()
        audit = {"deleted": 1, "updated_user": operator.user_id, "updated_date": now}

        video_ids = list(
            await db.scalars(
                select(EtMaterialVideo.video_id).where(
                    EtMaterialVideo.material_id.in_(material_ids), EtMaterialVideo.deleted == 0
                )
            )
        )
        if video_ids:
            for model in (EtProgressVideo, EtProgressInterval):
                await db.execute(update(model).where(model.video_id.in_(video_ids), model.deleted == 0).values(**audit))
            await db.execute(update(EtMaterialVideo).where(EtMaterialVideo.video_id.in_(video_ids)).values(**audit))

        await db.execute(
            update(EtMaterialDoc)
            .where(EtMaterialDoc.material_id.in_(material_ids), EtMaterialDoc.deleted == 0)
            .values(**audit)
        )
        await db.execute(
            update(EtMaterial).where(EtMaterial.material_id.in_(material_ids), EtMaterial.deleted == 0).values(**audit)
        )
        await db.flush()
