"""ET06 學習進度之查詢與寫入（US5 / #274）。

## 三張表的分工

| 表 | 粒度 | 內容 |
|---|---|---|
| `ET_PROGRESS_INTERVAL` | 每段播放一列 | **權威來源**——覆蓋率由它算 |
| `ET_PROGRESS_VIDEO` | 一人一影片 | 覆蓋率**快取** + 上次播放秒數 |
| `ET_PROGRESS` | 一人一項目 | 項目層 `IS_COMPLETED` |

`COVERAGE_PCT` 是快取（`data-model` 明訂），供側欄與統計快速讀取；權威始終是區段表。
"""

from decimal import Decimal

from sqlalchemy import Integer, delete, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.course.models import EtChapter, EtItem
from app.et.material.models import EtMaterialVideo
from app.et.progress.completion_sql import completed_pairs
from app.et.progress.models import EtEnrollment, EtProgress, EtProgressInterval, EtProgressVideo
from app.et.progress.rules import Segment


def completion_pct(done: int, total: int) -> int:
    """完成項目數 ÷ 總項目數，四捨五入為整數百分比（**僅供顯示**）。

    沒有任何項目的課程回 `0` 而非除零——教師剛建好還沒放內容時很常見。

    ⚠️ 回 100 **不代表全部完成**（201 項完成 200 項即 `round(99.5) = 100`）。純函式
    置於此處而非 `rules`：`progress/rules.py` 由另一個 issue 進行中，且本式與
    `completion_counts_by_course` 是同一件事的兩半，放在一起才看得出來。
    """
    return 0 if total == 0 else min(100, round(done * 100 / total))


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
        if completed:
            await self.stamp_completed_at(db, course_id=course_id, user_ids=[user_id], operator=operator)

    async def set_item_completed_bulk(
        self,
        db: AsyncSession,
        *,
        user_ids: list[str],
        course_id: int,
        item_id: int,
        completed: bool,
        operator: OperatorInfo,
    ) -> None:
        """批次設定**同一個項目**對多位學員的完成旗標——語意同 `set_item_completed`。

        供 #361 使用：該批次的人數由系統決定、沒有上限，逐筆呼叫等於 N 次往返。
        ⚠️ 只批次化往返次數，`ON CONFLICT` 的行為與單筆版完全一致。

        Args:
            user_ids: 受影響的學員；空陣列為 no-op。
        """
        if not user_ids:
            return
        now = utcnow()
        await db.execute(
            pg_insert(EtProgress)
            .values(
                [
                    {
                        "USER_ID": user_id,
                        "COURSE_ID": course_id,
                        "ITEM_ID": item_id,
                        "IS_COMPLETED": completed,
                        "CREATED_USER": operator.user_id,
                        "CREATED_DATE": now,
                        "DELETED": 0,
                    }
                    for user_id in user_ids
                ]
            )
            .on_conflict_do_update(
                constraint="UQ_ET_PROGRESS_USER_ITEM",
                set_={"IS_COMPLETED": completed, "UPDATED_USER": operator.user_id, "UPDATED_DATE": now},
            )
        )
        await db.flush()
        if completed:
            await self.stamp_completed_at(db, course_id=course_id, user_ids=user_ids, operator=operator)

    async def stamp_completed_at(
        self, db: AsyncSession, *, course_id: int, user_ids: list[str] | None = None, operator: OperatorInfo
    ) -> None:
        """若學員此刻剛好完課、且 `COMPLETED_AT` 仍為空，寫入當下時間（#464）。

        Args:
            course_id: 受影響的課程。
            user_ids: 受影響的學員；`None` 表該課程全體（項目刪除時用）。
            operator: 觸發者（寫入 `UPDATED_USER`）。

        ## 🔴 掛在 repository 層是刻意的

        三個進度寫入點中，`quiz/service.py` 直接持有本 repository、**繞過 progress
        service**——掛在 service 層要三處各叫一次，第四個寫入點出現時就會漏。本方法由
        `set_item_completed` / `set_item_completed_bulk` 自己呼叫，寫入路徑經過這裡就一定
        會被處理。

        ⚠️ 完課**不只**由進度寫入觸發（學員 2/3、教師刪掉剩下那一項 → 2/2）。那條路由
        `course/repository.EtItemRepository.soft_delete_with_cascade` 另行呼叫本方法。

        ## 只寫一次、回退不清除

        `WHERE COMPLETED_AT IS NULL` 讓本方法冪等——同一學員重複完成同一項（每次開教材、
        每個影片進度 ping）只會在第一次寫入。語意是「**第一次**達成完課的時間」，完課回退
        時不清除：查詢端以即時判定決定列要不要出現，殘留的值不會被讀到。

        ⛔ **不要改成取 `MAX(ET_PROGRESS.UPDATED_DATE)` 推導**：上方兩支 upsert 的
        `on_conflict_do_update` **無條件**寫 `UPDATED_DATE = now`，那個時間會往後漂。

        ⚠️ 判定**不看在籍**（`IS_REMOVED`）：ET04 查詢對已移除學員照列（完課是歷史事實，
        與核可紀錄一致），寫入端跟著一致，否則同一位已移除學員在畫面上會沒有時間。
        """
        # ── 第一步：鎖住「尚未有完課時間」的選課列；查無即返回 ──────────────────────
        #
        # 🔴 這一步同時擋兩件事（#464 code review MEDIUM 1 / 2）：
        #
        # 1. **並發完成最後兩項會兩邊都不寫入。** 預設 READ COMMITTED 下，同一學員在兩個
        #    分頁同時完成最後兩項，兩個 transaction 各自 upsert 自己那一列再算完課——都
        #    看不到對方尚未 commit 的列，各自算出 `N-1`，於是**誰都不寫**。`FOR UPDATE`
        #    讓後到者等前者 commit；READ COMMITTED 的下一個語句拿到新快照，重算就看得到
        #    前者那一列，得到 `N`。
        # 2. **已完課者每次影片 ping 都在白算子查詢。** 覆蓋率達標後，`progress/service`
        #    的影片進度每一次 ping 都以 `completed=True` 呼叫進來。已有完課時間的列在這裡
        #    就被濾掉、不加鎖、直接返回——成本降為一次走唯一鍵的單列查詢。
        #
        # ⚠️ `ORDER BY ENROLLMENT_ID`：批次寫入一次鎖多列，若兩個批次以不同順序取鎖會互相
        # 死鎖。固定順序即可避免。
        #
        # ⚠️ 本鎖**沒有並發測試覆蓋**——integration fixture 是單一 session + rollback，造不出
        # 兩個同時 commit 的 transaction。序列路徑的行為由 `test_et_completed_at.py` 驗證。
        pending = select(EtEnrollment.enrollment_id).where(
            EtEnrollment.course_id == course_id,
            EtEnrollment.deleted == 0,
            EtEnrollment.completed_at.is_(None),
        )
        if user_ids is not None:
            pending = pending.where(EtEnrollment.user_id.in_(user_ids))
        locked = list(await db.scalars(pending.order_by(EtEnrollment.enrollment_id).with_for_update()))
        if not locked:
            return

        # ── 第二步：只對鎖住的列判定並寫入 ────────────────────────────────────────
        pairs = completed_pairs(course_id=course_id, user_ids=user_ids)
        now = utcnow()
        await db.execute(
            update(EtEnrollment)
            .where(
                EtEnrollment.enrollment_id.in_(locked),
                EtEnrollment.user_id.in_(select(pairs.c.user_id)),
            )
            .values(completed_at=now, updated_user=operator.user_id, updated_date=now)
        )
        await db.flush()

    async def completed_item_ids(self, db: AsyncSession, *, user_id: str, course_id: int) -> set[int]:
        """該學員在此課程已完成的項目 id。

        ⚠️ 課程歸屬以 `ET_PROGRESS.COURSE_ID`（寫入當下存下的冗餘欄位）判定，而
        `completion_counts_by_course` 是以 `ET_CHAPTER.COURSE_ID`（當前的結構事實）推導。
        目前沒有「把項目搬到另一門課」的功能，兩者不可能分歧；已刪除項目的列亦由呼叫端
        取交集排除（見 `learning/service.structure` 的完課判定），與那支用 SQL JOIN 排除
        的效果相同。**若日後支援項目搬移，這兩處必須一起改**——不然完課會依呼叫路徑
        給出不同答案。
        """
        rows = await db.scalars(
            select(EtProgress.item_id).where(
                EtProgress.user_id == user_id,
                EtProgress.course_id == course_id,
                EtProgress.is_completed.is_(True),
                EtProgress.deleted == 0,
            )
        )
        return set(rows)

    # ⚠️ 這裡曾有一支 `completion_pct_by_course`（#274），直接回四捨五入後的百分比。
    # #284 起移除：所有呼叫端都改用下方的 `completion_counts_by_course` + 純函式
    # `completion_pct`（顯示）/ `enrollment.rules.is_course_completed`（閘門）。
    #
    # **刻意不留著那支**——留一個「回 100 卻不代表全部完成」的公開方法，正是下一個人
    # 拿它當完課閘門的入口，而那個偏差不會有任何地方察覺（見 `completion_pct` 的說明）。

    async def completion_counts_by_course(
        self, db: AsyncSession, *, user_id: str, course_ids: list[int]
    ) -> dict[int, tuple[int, int]]:
        """各課程之 `(完成項目數, 總項目數)`——進度百分比與完課判定的共同來源。

        以兩支 `GROUP BY` 聚合查詢取得，**不逐課程查**——「我的課程」一次可能列出數十
        門課，N+1 會讓那一頁隨選課數線性變慢。

        ⚠️ **完成數必須 JOIN 回 `ET_ITEM` / `ET_CHAPTER` 過濾軟刪除**。`ET_PROGRESS` 的
        列在項目被刪除後若仍留著，直接 `count(*)` 會拿分母已縮小、分子沒縮小的兩個數字
        相除——教師刪掉一章就會讓學員看到 150%。
        ⚠️ 2026-09-30 #464 更正：**進度列其實會被連帶軟刪除**——
        `course/repository.EtItemRepository.soft_delete_with_cascade` 以 `.values(**audit)`
        一併設 `DELETED=1`（`data-model.md:192` 亦記載 2026-08-24 已改為連帶軟刪）。本防禦
        仍然正確，但承重的理由是「cascade 若被改壞時結果是少算而非多算」，不是「進度列會
        殘留」。⚠️ 該 cascade 用 dict 展開，grep `EtProgress` 附近的 `deleted` 找不到它。

        課程層以 `ET_CHAPTER.COURSE_ID` 推導而非 `ET_PROGRESS.COURSE_ID`：後者是寫入當下
        存下的冗餘欄位，前者才是當前的結構事實。

        Returns:
            `{course_id: (done, total)}`，`course_ids` 中每一個都有值（沒有項目的課程
            回 `(0, 0)`）。
        """
        if not course_ids:
            return {}
        totals = await db.execute(
            select(EtChapter.course_id, func.count(EtItem.item_id))
            .select_from(EtItem)
            .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
            .where(EtChapter.course_id.in_(course_ids), EtItem.deleted == 0, EtChapter.deleted == 0)
            .group_by(EtChapter.course_id)
        )
        total_by_course = dict(totals.all())
        done = await db.execute(
            select(EtChapter.course_id, func.count(EtProgress.progress_id))
            .select_from(EtProgress)
            .join(EtItem, EtItem.item_id == EtProgress.item_id)
            .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
            .where(
                EtProgress.user_id == user_id,
                EtChapter.course_id.in_(course_ids),
                EtProgress.is_completed.is_(True),
                EtProgress.deleted == 0,
                EtItem.deleted == 0,
                EtChapter.deleted == 0,
            )
            .group_by(EtChapter.course_id)
        )
        done_by_course = dict(done.all())

        return {
            course_id: (done_by_course.get(course_id, 0), total_by_course.get(course_id, 0)) for course_id in course_ids
        }

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

    async def touch_activity(self, db: AsyncSession, *, user_id: str, course_id: int, operator: OperatorInfo) -> None:
        """只更新 `LAST_ACTIVITY_AT`，**不碰 `LAST_ITEM_ID`**（#334 / SA 裁示 2026-09-15）。

        ## 什麼算一次「學習活動」

        `data-model` §ET_ENROLLMENT 定義本欄為「最近一次學習動作 / 測驗提交時間」。
        目前的完整清單是：

        | 活動 | 寫入點 |
        |---|---|
        | 檢視項目 | `set_last_item()`（連帶寫 `LAST_ITEM_ID`）|
        | 提交測驗 | `attempt/service.submit()` → 本函式 |
        | 填答問卷 | `survey_fill/service.submit()` → 本函式 |

        **加入課程不算**——見 `test_et_enrollment.py`「加入不是學習動作」。新增活動種類
        時請一併更新本表，否則下一個人得把三個模組都讀過才知道漏了哪個。

        ## 為何不共用 `set_last_item()`

        那支會**連帶**寫 `LAST_ITEM_ID`。提交測驗與填問卷都不該改變「上次讀到哪」——
        否則學員下次回到課程會被帶到測驗而不是他真正讀到的地方，症狀是「續讀位置莫名
        其妙跳掉」，且不會有任何錯誤。

        查無選課列時**靜默返回**：擁有者預覽沒有選課列，比照 `set_last_item()` 的處理。

        ## ⚠️ 本支繞過 `EtProgressService._guard_write`（課程視同關閉時一律 409）

        呼叫端是 `attempt` / `survey_fill` 的 service，直接進 repository。這是**刻意**的：
        `spec_us6` 場景 27 允許「關閉當下已在作答者完成並計分」，那條窄縫裡的提交本來就
        該記為一次活動；擋掉會讓活動時間與實際發生的事對不上。`_mark_item_completed`
        對同一個繞道有更完整的說明。

        但這件事不會自己顯現——日後若把關閉守門移到這一層，請先確認場景 27 仍成立。
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
            return
        now = utcnow()
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
