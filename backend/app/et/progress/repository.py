"""ET05 學習進度之查詢與寫入（US5 / #274）。

## 三張表的分工

| 表 | 粒度 | 內容 |
|---|---|---|
| `ET_PROGRESS_INTERVAL` | 每段播放一列 | **權威來源**——覆蓋率由它算 |
| `ET_PROGRESS_VIDEO` | 一人一影片 | 覆蓋率**快取** + 上次播放秒數 |
| `ET_PROGRESS` | 一人一項目 | 項目層 `IS_COMPLETED` |

`COVERAGE_PCT` 是快取（`data-model` 明訂），供側欄與統計快速讀取；權威始終是區段表。
"""

from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.course.models import EtChapter, EtItem
from app.et.material.models import EtMaterialVideo
from app.et.progress.models import EtEnrollment, EtProgress, EtProgressInterval, EtProgressVideo
from app.et.progress.rules import Segment


class EtProgressRepository:
    """`ET_PROGRESS` / `_VIDEO` / `_INTERVAL` 之讀寫。"""

    # ── 區段 ────────────────────────────────────────────────────────────────

    async def add_intervals(
        self, db: AsyncSession, *, user_id: str, video_id: int, segments: list[Segment], operator: OperatorInfo
    ) -> int:
        """追加播放區段。**不合併、不去重**——那是 `normalize` 與覆蓋率計算的事。

        每段一列是 `data-model` 的設計：以獨立資料列儲存而非 JSON 字串，避免
        read-modify-write race，也便於 SQL 直接聚合。
        """
        if not segments:
            return 0
        now = utcnow()
        db.add_all(
            [
                EtProgressInterval(
                    user_id=user_id,
                    video_id=video_id,
                    start_sec=seg.start,
                    end_sec=seg.end,
                    created_user=operator.user_id,
                    created_date=now,
                )
                for seg in segments
            ]
        )
        await db.flush()
        return len(segments)

    async def list_intervals(self, db: AsyncSession, *, user_id: str, video_id: int) -> list[Segment]:
        rows = await db.execute(
            select(EtProgressInterval.start_sec, EtProgressInterval.end_sec).where(
                EtProgressInterval.user_id == user_id,
                EtProgressInterval.video_id == video_id,
                EtProgressInterval.deleted == 0,
            )
        )
        return [Segment(start, end) for start, end in rows.all()]

    async def replace_intervals(
        self, db: AsyncSession, *, user_id: str, video_id: int, segments: list[Segment], operator: OperatorInfo
    ) -> None:
        """normalize 的寫入端：DELETE 全部 → INSERT 合併後結果。

        **硬刪除而非軟刪除**——這裡刪掉的是「同一批資料的未壓縮表述」，不是使用者
        資料的作廢。留著軟刪除列會讓 `list_intervals` 每次都要過濾一堆歷史雜訊，
        而它們不帶任何 `DELETED=1` 才有的資訊（`sti-backend-modules` 之刪除策略例外）。
        """
        await db.execute(
            delete(EtProgressInterval).where(
                EtProgressInterval.user_id == user_id,
                EtProgressInterval.video_id == video_id,
            )
        )
        await self.add_intervals(db, user_id=user_id, video_id=video_id, segments=segments, operator=operator)

    # ── 影片進度 ────────────────────────────────────────────────────────────

    async def get_video_progress(self, db: AsyncSession, *, user_id: str, video_id: int) -> EtProgressVideo | None:
        return await db.scalar(
            select(EtProgressVideo).where(
                EtProgressVideo.user_id == user_id,
                EtProgressVideo.video_id == video_id,
                EtProgressVideo.deleted == 0,
            )
        )

    async def upsert_video_progress(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        video_id: int,
        coverage: int,
        last_position_sec: int | None,
        operator: OperatorInfo,
    ) -> EtProgressVideo:
        """寫入覆蓋率快取與上次播放位置。

        `last_position_sec` 為 `None` 時**保留原值**——normalize 不帶位置，不該把
        學員的續看點清掉。
        """
        now = utcnow()
        row = await self.get_video_progress(db, user_id=user_id, video_id=video_id)
        if row is None:
            row = EtProgressVideo(
                user_id=user_id,
                video_id=video_id,
                coverage_pct=Decimal(coverage),
                last_position_sec=last_position_sec,
                created_user=operator.user_id,
                created_date=now,
            )
            db.add(row)
        else:
            row.coverage_pct = Decimal(coverage)
            if last_position_sec is not None:
                row.last_position_sec = last_position_sec
            row.updated_user = operator.user_id
            row.updated_date = now
        await db.flush()
        return row

    async def video_progress_of_material(
        self, db: AsyncSession, *, user_id: str, material_id: int
    ) -> dict[int, tuple[int, int | None]]:
        """該教材下**每支未刪除影片**的 `(覆蓋率, 上次播放秒數)`；沒有進度紀錄者為 `(0, None)`。

        `data-model` §ET_PROGRESS 明訂「缺任一支影片之進度紀錄**視為 0%**」——故此處
        以影片清單為基準 LEFT JOIN 進度，**不能**只回有紀錄的那些。否則一支都沒看過
        的教材會因為「所有（零支）影片都達標」而被判定完成。
        """
        rows = await db.execute(
            select(EtMaterialVideo.video_id, EtProgressVideo.coverage_pct, EtProgressVideo.last_position_sec)
            .select_from(EtMaterialVideo)
            .outerjoin(
                EtProgressVideo,
                (EtProgressVideo.video_id == EtMaterialVideo.video_id)
                & (EtProgressVideo.user_id == user_id)
                & (EtProgressVideo.deleted == 0),
            )
            .where(EtMaterialVideo.material_id == material_id, EtMaterialVideo.deleted == 0)
        )
        return {
            video_id: (int(coverage) if coverage is not None else 0, last_position)
            for video_id, coverage, last_position in rows.all()
        }

    async def coverages_of_material(self, db: AsyncSession, *, user_id: str, material_id: int) -> list[int]:
        """該教材下每支未刪除影片的覆蓋率（缺紀錄者為 0）——完成判定用。"""
        progress = await self.video_progress_of_material(db, user_id=user_id, material_id=material_id)
        return [coverage for coverage, _ in progress.values()]

    # ── 項目進度 ────────────────────────────────────────────────────────────

    async def set_item_completed(
        self, db: AsyncSession, *, user_id: str, course_id: int, item_id: int, completed: bool, operator: OperatorInfo
    ) -> None:
        now = utcnow()
        row = await db.scalar(
            select(EtProgress).where(
                EtProgress.user_id == user_id, EtProgress.item_id == item_id, EtProgress.deleted == 0
            )
        )
        if row is None:
            db.add(
                EtProgress(
                    user_id=user_id,
                    course_id=course_id,
                    item_id=item_id,
                    is_completed=completed,
                    created_user=operator.user_id,
                    created_date=now,
                )
            )
        else:
            row.is_completed = completed
            row.updated_user = operator.user_id
            row.updated_date = now
        await db.flush()

    async def completed_item_ids(self, db: AsyncSession, *, user_id: str, course_id: int) -> set[int]:
        rows = await db.scalars(
            select(EtProgress.item_id).where(
                EtProgress.user_id == user_id,
                EtProgress.course_id == course_id,
                EtProgress.is_completed.is_(True),
                EtProgress.deleted == 0,
            )
        )
        return set(rows)

    # ── 上次檢視項目（#274 SA Q1 裁示 B）────────────────────────────────────

    async def set_last_item(
        self, db: AsyncSession, *, user_id: str, course_id: int, item_id: int, operator: OperatorInfo
    ) -> None:
        """更新「上次看到哪一項」與最後活動時間。

        兩欄一起更新——`LAST_ACTIVITY_AT` 原本就是「最後活動時間」，而這正是一次活動。
        """
        row = await db.scalar(
            select(EtEnrollment).where(
                EtEnrollment.user_id == user_id,
                EtEnrollment.course_id == course_id,
                EtEnrollment.is_removed.is_(False),
                EtEnrollment.deleted == 0,
            )
        )
        if row is None:
            # 擁有者預覽時沒有選課列——不記錄，也不該報錯（裁示：預覽不累積進度）。
            return
        now = utcnow()
        row.last_item_id = item_id
        row.last_activity_at = now
        row.updated_user = operator.user_id
        row.updated_date = now
        await db.flush()

    async def get_last_item_id(self, db: AsyncSession, *, user_id: str, course_id: int) -> int | None:
        return await db.scalar(
            select(EtEnrollment.last_item_id).where(
                EtEnrollment.user_id == user_id,
                EtEnrollment.course_id == course_id,
                EtEnrollment.is_removed.is_(False),
                EtEnrollment.deleted == 0,
            )
        )

    # ── 授權反查（比照 learning 之鏈）────────────────────────────────────────

    async def course_id_of_video(self, db: AsyncSession, video_id: int) -> int | None:
        return await db.scalar(
            select(EtChapter.course_id)
            .select_from(EtMaterialVideo)
            .join(EtItem, EtItem.material_id == EtMaterialVideo.material_id)
            .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
            .where(
                EtMaterialVideo.video_id == video_id,
                EtMaterialVideo.deleted == 0,
                EtItem.deleted == 0,
                EtChapter.deleted == 0,
            )
        )

    async def get_video(self, db: AsyncSession, video_id: int) -> EtMaterialVideo | None:
        return await db.scalar(
            select(EtMaterialVideo).where(EtMaterialVideo.video_id == video_id, EtMaterialVideo.deleted == 0)
        )

    async def get_item(self, db: AsyncSession, item_id: int) -> EtItem | None:
        return await db.scalar(select(EtItem).where(EtItem.item_id == item_id, EtItem.deleted == 0))

    async def item_id_of_material(self, db: AsyncSession, material_id: int) -> int | None:
        """教材 → 引用它的項目。影片的覆蓋率要回寫到**項目層**的 `IS_COMPLETED`。

        今日一份教材只會被一個項目引用（建項目一律產生新教材），故取一筆即可；
        `course/repository.py` 已預告日後可能支援重用，屆時本函式要一併調整。
        """
        return await db.scalar(select(EtItem.item_id).where(EtItem.material_id == material_id, EtItem.deleted == 0))

    async def course_id_of_item(self, db: AsyncSession, item_id: int) -> int | None:
        return await db.scalar(
            select(EtChapter.course_id)
            .select_from(EtItem)
            .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
            .where(EtItem.item_id == item_id, EtItem.deleted == 0, EtChapter.deleted == 0)
        )
