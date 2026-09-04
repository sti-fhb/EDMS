"""ET05 學習進度 Service（US5 / #274）。

## 寫入的三道守門，順序不可調換

```
1. 授權：在籍 OR 擁有者          → 兩者皆非 → 404
2. 擁有者預覽（是擁有者且不在籍）→ 靜默忽略，不寫入、不報錯
3. 課程已關閉                    → 409 ET_PROGRESS_001
```

**2 必須在 3 之前**：教師預覽一門已關閉的課程時，該給他「什麼都沒發生」而不是
「此課程已關閉」——後者暗示他做錯了什麼，但他只是在看自己的課。

**「擁有者且不在籍」才是預覽**：教師若真的用邀請碼加入自己的課，他就是學員，
進度照常累積、關閉照常擋。

## 兩條 #255 裁示在此第一次真正被執行

ET-5a（#255）完全沒有寫入，所以那兩條裁示當時是**自然成立、從未被驗證**的：

| 裁示 | 執行點 |
|---|---|
| #255 Q1：教師預覽不累積進度 | 守門 2 |
| #255 Q2：課程關閉＝讀照舊、寫全停 | 守門 3 |
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.et.constants import COURSE_CLOSED, ITEM_MATERIAL
from app.et.learning.repository import EtLearningRepository
from app.et.learning.rules import ensure_can_access
from app.et.progress.repository import EtProgressRepository
from app.et.progress.rules import (
    Segment,
    clamp_segment,
    coverage_pct,
    is_material_completed,
    is_video_completed,
    merge_segments,
)
from app.et.progress.schemas import IntervalReportReq, ItemViewedResult, VideoProgress

_NOT_FOUND = AppError(status_code=404, detail="查無此課程內容", error_code="ET_LEARN_001")
_CLOSED = AppError(status_code=409, detail="此課程目前關閉中，無法累積學習進度", error_code="ET_PROGRESS_001")
_BAD_SEGMENTS = AppError(status_code=422, detail="播放區段資料無效", error_code="ET_PROGRESS_002")


class _PreviewOnly(Exception):
    """內部訊號：擁有者預覽，不寫入。**不外流到 HTTP 層**。"""


class EtProgressService:
    """播放區段上報、normalize、項目完成判定。"""

    def __init__(
        self,
        repository: EtProgressRepository | None = None,
        learning: EtLearningRepository | None = None,
    ) -> None:
        self._repo = repository or EtProgressRepository()
        # 授權判定沿用 `learning` 的既有查詢（`get_course` / `is_enrolled`）——同一模組
        # 內共用 repository 不違反邊界規則（那條規則管的是**跨模組**直接 import）。
        # 複製一份等於讓「在籍」的定義有兩個版本，遲早只改到其中一個。
        self._learning = learning or EtLearningRepository()

    async def report_intervals(
        self, db: AsyncSession, video_id: int, req: IntervalReportReq, *, operator: OperatorInfo
    ) -> VideoProgress:
        """上報播放區段並重算覆蓋率。"""
        video = await self._repo.get_video(db, video_id)
        course_id = await self._repo.course_id_of_video(db, video_id)
        if video is None or course_id is None:
            raise _NOT_FOUND
        try:
            await self._guard_write(db, course_id=course_id, user_id=operator.user_id)
        except _PreviewOnly:
            return await self._preview_result(db, video_id=video_id, user_id=operator.user_id)

        # 裁切到影片長度：`data-model` 明訂，避免覆蓋率 > 100%（`DECIMAL(5,2)` 會爆）
        segments = [
            s
            for s in (
                clamp_segment(Segment(seg.start_sec, seg.end_sec), duration_sec=video.duration_sec)
                for seg in req.segments
            )
            if s is not None
        ]
        if not segments:
            # **全部**區段都被裁掉 = 這批資料根本描述不了這支影片（起點就超過片長）。
            # 靜默接受會讓「前端上報到錯的 video_id」表現成「怎麼看都沒有進度」——
            # 一個沒有任何訊號、只能靠使用者抱怨才會發現的 bug。
            #
            # 只在**全部**被裁掉時才報錯：單段落在邊界外屬正常誤差（`currentTime` 可能
            # 略微超過 ffprobe 取得的 `DURATION_SEC`），照常裁切吸收。
            raise _BAD_SEGMENTS
        await self._repo.add_intervals(
            db, user_id=operator.user_id, video_id=video_id, segments=segments, operator=operator
        )
        return await self._recompute(
            db,
            video_id=video_id,
            course_id=course_id,
            duration_sec=video.duration_sec,
            material_id=video.material_id,
            last_position_sec=req.last_position_sec,
            operator=operator,
        )

    async def normalize(self, db: AsyncSession, video_id: int, *, operator: OperatorInfo) -> VideoProgress:
        """合併重疊 / 相接區段並回寫覆蓋率（離開頁面時觸發）。

        ⚠️ **normalize 是儲存壓縮，不是正確性前提**——覆蓋率一律先聯集再算，所以
        沒跑成功只是列數變多。AC 7（異常離開後下次仍正確）因此自然成立。
        """
        video = await self._repo.get_video(db, video_id)
        course_id = await self._repo.course_id_of_video(db, video_id)
        if video is None or course_id is None:
            raise _NOT_FOUND
        try:
            await self._guard_write(db, course_id=course_id, user_id=operator.user_id)
        except _PreviewOnly:
            return await self._preview_result(db, video_id=video_id, user_id=operator.user_id)

        raw = await self._repo.list_intervals(db, user_id=operator.user_id, video_id=video_id)
        merged = list(merge_segments(raw))
        if len(merged) != len(raw):
            # 只在真的能壓縮時才寫——沒有重疊時 DELETE + INSERT 全表是白費
            await self._repo.replace_intervals(
                db, user_id=operator.user_id, video_id=video_id, segments=merged, operator=operator
            )
        return await self._recompute(
            db,
            video_id=video_id,
            course_id=course_id,
            duration_sec=video.duration_sec,
            material_id=video.material_id,
            last_position_sec=None,  # normalize 不帶位置——不可把續看點清掉
            operator=operator,
        )

    async def mark_item_viewed(self, db: AsyncSession, item_id: int, *, operator: OperatorInfo) -> ItemViewedResult:
        """文件 / 說明文字項目「開啟即完成」（AC 13 / FR-08）。

        **含影片的教材不走這裡**——那類的完成由覆蓋率決定。若對含影片的教材呼叫本
        端點，只更新「上次檢視項目」而不標記完成，否則學員點一下就跳過了 80% 的要求。
        """
        item = await self._repo.get_item(db, item_id)
        course_id = await self._repo.course_id_of_item(db, item_id)
        if item is None or course_id is None:
            raise _NOT_FOUND
        try:
            await self._guard_write(db, course_id=course_id, user_id=operator.user_id)
        except _PreviewOnly:
            return ItemViewedResult(item_id=item_id, completed=False)

        await self._repo.set_last_item(
            db, user_id=operator.user_id, course_id=course_id, item_id=item_id, operator=operator
        )

        completed = False
        if item.item_type == ITEM_MATERIAL and item.material_id is not None:
            coverages = await self._repo.coverages_of_material(
                db, user_id=operator.user_id, material_id=item.material_id
            )
            # 沒有影片的教材 → 開啟即完成；有影片 → 由覆蓋率決定
            completed = True if not coverages else is_material_completed(coverages)
            await self._repo.set_item_completed(
                db,
                user_id=operator.user_id,
                course_id=course_id,
                item_id=item_id,
                completed=completed,
                operator=operator,
            )
        return ItemViewedResult(item_id=item_id, completed=completed)

    # ── 內部 ────────────────────────────────────────────────────────────────

    async def _guard_write(self, db: AsyncSession, *, course_id: int, user_id: str) -> None:
        """三道守門（順序見模組 docstring）。

        Raises:
            AppError: 404 兩者皆非；409 `ET_PROGRESS_001` 課程已關閉。
            _PreviewOnly: 擁有者預覽——呼叫端據此回「什麼都沒發生」。
        """
        course = await self._learning.get_course(db, course_id)
        if course is None:
            raise _NOT_FOUND
        enrolled = await self._learning.is_enrolled(db, user_id=user_id, course_id=course_id)
        is_owner = course.owner_id == user_id
        try:
            ensure_can_access(enrolled=enrolled, is_owner=is_owner)
        except AppError:
            raise _NOT_FOUND from None

        if is_owner and not enrolled:
            # 擁有者預覽（#255 裁示 Q1）——**在關閉判定之前**：教師預覽已關閉的課程，
            # 該給他「什麼都沒發生」而不是「此課程已關閉」。
            raise _PreviewOnly
        if course.status == COURSE_CLOSED:
            raise _CLOSED

    async def _recompute(
        self,
        db: AsyncSession,
        *,
        video_id: int,
        course_id: int,
        duration_sec: int,
        material_id: int,
        last_position_sec: int | None,
        operator: OperatorInfo,
    ) -> VideoProgress:
        """由區段重算覆蓋率 → 回寫快取 → 更新該教材所屬項目的完成狀態。"""
        segments = await self._repo.list_intervals(db, user_id=operator.user_id, video_id=video_id)
        coverage = coverage_pct(segments, duration_sec=duration_sec)
        row = await self._repo.upsert_video_progress(
            db,
            user_id=operator.user_id,
            video_id=video_id,
            coverage=coverage,
            last_position_sec=last_position_sec,
            operator=operator,
        )

        item_id = await self._repo.item_id_of_material(db, material_id)
        if item_id is not None:
            coverages = await self._repo.coverages_of_material(db, user_id=operator.user_id, material_id=material_id)
            await self._repo.set_item_completed(
                db,
                user_id=operator.user_id,
                course_id=course_id,
                item_id=item_id,
                completed=is_material_completed(coverages),
                operator=operator,
            )
        return VideoProgress(
            video_id=video_id,
            coverage_pct=coverage,
            last_position_sec=row.last_position_sec,
            completed=is_video_completed(coverage),
        )

    async def _preview_result(self, db: AsyncSession, *, video_id: int, user_id: str) -> VideoProgress:
        """擁有者預覽的回應：**回目前狀態、不寫入**。

        回 200 而非錯誤——他沒做錯事，跳錯誤只會讓他以為預覽壞了（#255 裁示 Q1）。
        """
        row = await self._repo.get_video_progress(db, user_id=user_id, video_id=video_id)
        coverage = int(row.coverage_pct) if row else 0
        return VideoProgress(
            video_id=video_id,
            coverage_pct=coverage,
            last_position_sec=row.last_position_sec if row else None,
            completed=is_video_completed(coverage),
        )
