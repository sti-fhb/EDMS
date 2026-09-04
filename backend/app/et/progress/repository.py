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

from sqlalchemy import Integer, delete, func, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
        return [seg for _, seg in await self.list_intervals_with_ids(db, user_id=user_id, video_id=video_id)]

    async def list_intervals_with_ids(
        self, db: AsyncSession, *, user_id: str, video_id: int
    ) -> list[tuple[int, Segment]]:
        """區段連同 `INTERVAL_ID`——`replace_intervals` 需要它來限定刪除範圍。"""
        rows = await db.execute(
            select(EtProgressInterval.interval_id, EtProgressInterval.start_sec, EtProgressInterval.end_sec).where(
                EtProgressInterval.user_id == user_id,
                EtProgressInterval.video_id == video_id,
                EtProgressInterval.deleted == 0,
            )
        )
        return [(interval_id, Segment(start, end)) for interval_id, start, end in rows.all()]

    async def replace_intervals(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        video_id: int,
        replaced_ids: list[int],
        segments: list[Segment],
        operator: OperatorInfo,
    ) -> None:
        """壓縮的寫入端：刪掉**快照中讀到的那些列**，換成合併後的結果。

        ## ⚠️ 只刪 `replaced_ids`，不可用 `(USER_ID, VIDEO_ID)` 全量刪

        「SELECT → 記憶體合併 → 覆寫」之間沒有鎖，而同一支影片可能同時有另一個請求
        在寫入（`pause` 觸發的上報還在飛，`pagehide` 的 normalize 已經進來；或學員開了
        兩個分頁）。全量刪除會讓 A 的 DELETE 掃掉 B 剛寫入、A 卻沒讀到的區段，A 再把
        舊快照寫回去——**該段觀看紀錄永久遺失**。

        表現會是「覆蓋率倒退」，甚至讓已判定完成的項目變回未完成、後續章節重新上鎖，
        而學員什麼都沒做錯。限定在快照 id 內刪除即可讓併發寫入自然共存：沒被讀到的列
        原地保留，下次計算時一併聯集。

        **硬刪除而非軟刪除**——這裡刪掉的是「同一批資料的未壓縮表述」，不是使用者資料
        的作廢。留著軟刪除列會讓每次讀取都要過濾一堆歷史雜訊，而它們不帶任何
        `DELETED=1` 才有的資訊（已登記於 `docs/ref/sti-backend-ref.md` 刪除策略例外表）。
        """
        if replaced_ids:
            await db.execute(delete(EtProgressInterval).where(EtProgressInterval.interval_id.in_(replaced_ids)))
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

        ## 為何是 `ON CONFLICT` 而不是「查了再決定 INSERT / UPDATE」

        **關閉分頁會同時觸發兩次收尾**：前端對 `visibilitychange`(hidden) 與 `pagehide`
        各註冊一次，兩者都會送出上報。首次觀看某支影片時（本表尚無該列）兩個請求會
        同時走到這裡，read-then-write 之間沒有鎖，第二個 INSERT 會撞
        `UQ_ET_PROGRESS_VIDEO_USER_VIDEO` 變成未處理例外 500，並讓該次的區段一起回滾。
        這不是理論競態，是關分頁的預設路徑。

        `last_position_sec` 為 `None` 時**保留原值**——normalize 不帶位置，不該把學員的
        續看點清掉。故 `set_` 用 `COALESCE(EXCLUDED, 既有值)` 表達，而非無條件覆寫。
        """
        now = utcnow()
        stmt = (
            pg_insert(EtProgressVideo)
            .values(
                USER_ID=user_id,
                VIDEO_ID=video_id,
                COVERAGE_PCT=Decimal(coverage),
                LAST_POSITION_SEC=last_position_sec,
                CREATED_USER=operator.user_id,
                CREATED_DATE=now,
                DELETED=0,
            )
            .on_conflict_do_update(
                constraint="UQ_ET_PROGRESS_VIDEO_USER_VIDEO",
                set_={
                    "COVERAGE_PCT": Decimal(coverage),
                    "LAST_POSITION_SEC": func.coalesce(
                        literal(last_position_sec, Integer), EtProgressVideo.__table__.c.LAST_POSITION_SEC
                    ),
                    "UPDATED_USER": operator.user_id,
                    "UPDATED_DATE": now,
                },
            )
            .returning(EtProgressVideo)
        )
        row = (await db.execute(stmt)).scalar_one()
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
        """項目層完成旗標。`ON CONFLICT` 的理由同 `upsert_video_progress`。"""
        now = utcnow()
        await db.execute(
            pg_insert(EtProgress)
            .values(
                USER_ID=user_id,
                COURSE_ID=course_id,
                ITEM_ID=item_id,
                IS_COMPLETED=completed,
                CREATED_USER=operator.user_id,
                CREATED_DATE=now,
                DELETED=0,
            )
            .on_conflict_do_update(
                constraint="UQ_ET_PROGRESS_USER_ITEM",
                set_={"IS_COMPLETED": completed, "UPDATED_USER": operator.user_id, "UPDATED_DATE": now},
            )
        )
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

    # ── 授權反查：**一條鏈推導，不拼裝** ─────────────────────────────────────
    #
    # ⚠️ 影片與項目的所屬課程一律由**同一次查詢**得出。分兩支查（video → course、
    # material → item）再把結果湊起來，在「同一份教材被兩門課程引用」時會湊出
    # 「A 課的課程 + B 課的項目」——於是以 A 課的在籍資格，寫出掛在 B 課項目上的進度。
    #
    # 今日建項目一律產生新教材，故不可達；但 `course/repository.py` 已預告日後可能支援
    # 教材重用，屆時拼裝式的反查會直接變成跨課程寫入。比照 `learning/service`
    # `material_content` 的同一個判斷：**不一致即拒，不去猜哪一個才對**。

    async def video_context(self, db: AsyncSession, video_id: int) -> tuple[EtMaterialVideo, int, int] | None:
        """影片 → `(影片列, 所屬項目, 所屬課程)`；任一跳被軟刪除或**引用不唯一**時回 `None`。"""
        rows = await db.execute(
            select(EtMaterialVideo, EtItem.item_id, EtChapter.course_id)
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
        found = rows.all()
        if len(found) != 1:
            return None
        video, item_id, course_id = found[0]
        return video, item_id, course_id

    async def item_context(self, db: AsyncSession, item_id: int) -> tuple[EtItem, int] | None:
        """項目 → `(項目列, 所屬課程)`；任一跳被軟刪除時回 `None`。"""
        rows = await db.execute(
            select(EtItem, EtChapter.course_id)
            .select_from(EtItem)
            .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
            .where(EtItem.item_id == item_id, EtItem.deleted == 0, EtChapter.deleted == 0)
        )
        found = rows.first()
        if found is None:
            return None
        item, course_id = found
        return item, course_id

    async def interval_row_count(self, db: AsyncSession, *, user_id: str, video_id: int) -> int:
        return (
            await db.scalar(
                select(func.count())
                .select_from(EtProgressInterval)
                .where(EtProgressInterval.user_id == user_id, EtProgressInterval.video_id == video_id)
            )
            or 0
        )
