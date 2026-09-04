"""ET05 學習進度 Service（US5 / #274）。

## 寫入的四道守門，順序不可調換

```
1. 授權：在籍 OR 擁有者          → 兩者皆非 → 404
2. 擁有者預覽（是擁有者且不在籍）→ 靜默忽略，不寫入、不報錯
3. 課程已關閉 / 尚未發布          → 409 ET_PROGRESS_001 / 404
4. 該項目尚未解鎖                → 404（視同不存在）
```

**2 必須在 3 之前**：教師預覽一門已關閉的課程時，該給他「什麼都沒發生」而不是
「此課程已關閉」——後者暗示他做錯了什麼，但他只是在看自己的課。

**「擁有者且不在籍」才是預覽**：教師若真的用邀請碼加入自己的課，他就是學員，
進度照常累積、關閉照常擋。

## 第 4 道：解鎖判定**必須在後端執行**

`spec_us5` AC 9 寫的是「系統阻擋」，不是「畫面不給點」。只靠前端 `handleSelect` 判
`locked`，任何人都能直接 `POST /items/{第 5 章的文件項目}/viewed` 拿到
`completed=true`——而 `locked_item_ids` 的「已完成永不鎖定」會讓那一項自我解鎖，
`previous_chapter_done` 又只看緊鄰的前一章，於是第 6 章跟著開，第 1～4 章一項都不必碰。
對教育訓練系統而言那等於可以偽造依序完訓的紀錄。

`normalize` **不掛這道**：它只是把既有區段合併壓縮，聯集不變、覆蓋率不變，加不出任何
進度。反而掛上去會讓「教師事後調整章節順序、把學員正在看的項目鎖回去」時，前端
`pagehide` 的收尾補送整批失敗。

## ⚠️ 覆蓋率是**自陳資料**

區段完全來自前端上報，後端只做裁切與聯集。一個 `[0, duration]` 的請求即可得到 100%
——這是 `currentTime` 上報模型的固有性質（FR-ET-US5-07 明訂倍速依影片時間軸計算，
而牆鐘時間後端看不到），Canvas / Moodle 的影片進度亦同。

故**覆蓋率不得作為稽核證據**。US9 完課率與日後的完訓證明若需要更強的保證，要另行設計
（如隨機插入的注意力檢查），不能改由本模組「算得更嚴」來達成。已列為 SA 待裁示項。

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
from app.et.constants import COURSE_CLOSED, COURSE_DRAFT, ITEM_MATERIAL
from app.et.learning.repository import EtLearningRepository
from app.et.learning.rules import ensure_can_access
from app.et.progress.repository import EtProgressRepository
from app.et.progress.rules import (
    Segment,
    build_item_state,
    clamp_segment,
    coverage_pct,
    is_material_completed,
    is_video_completed,
    locked_item_ids,
    merge_segments,
)
from app.et.progress.schemas import IntervalReportReq, ItemViewedResult, VideoProgress

_NOT_FOUND = AppError(status_code=404, detail="查無此課程內容", error_code="ET_LEARN_001")
_CLOSED = AppError(status_code=409, detail="此課程目前關閉中，無法累積學習進度", error_code="ET_PROGRESS_001")
_BAD_SEGMENTS = AppError(status_code=422, detail="播放區段資料無效", error_code="ET_PROGRESS_002")

#: 單一 `(USER_ID, VIDEO_ID)` 的區段列數上界；超過即**就地合併**，不等前端呼叫 normalize。
#:
#: `MAX_SEGMENTS_PER_REQUEST` 只管單一請求，沒有累計上界——不設這道，重複呼叫上報即可
#: 無限堆疊，而 `_recompute` 每次都要把該影片的**全部**區段載入 Python 排序，成本是
#: 二次成長的。合併後的互斥區段之間必有 ≥ 1 秒間隙，故實際列數天然被 `duration_sec / 2`
#: 界定，本上界只是在到達之前先收斂。
#:
#: 副作用是正向的：前端沒跑到 normalize 的長尾（異常離開）也會自動被壓縮。
_MAX_INTERVAL_ROWS = 500


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
        context = await self._repo.video_context(db, video_id)
        if context is None:
            raise _NOT_FOUND
        video, item_id, course_id = context
        try:
            await self._guard_write(db, course_id=course_id, user_id=operator.user_id, item_id=item_id)
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
            item_id=item_id,
            duration_sec=video.duration_sec,
            material_id=video.material_id,
            # ⚠️ **必須裁切**：`LAST_POSITION_SEC` 是 INT4，而本欄位沒有經過
            # `clamp_segment`。上報一個 999 億的值會讓 asyncpg 在寫入時炸成未處理
            # 例外（500），連同該次的區段一起回滾——任何在籍學員都能重複觸發。
            last_position_sec=(
                None if req.last_position_sec is None else min(req.last_position_sec, video.duration_sec)
            ),
            operator=operator,
        )

    async def normalize(self, db: AsyncSession, video_id: int, *, operator: OperatorInfo) -> VideoProgress:
        """合併重疊 / 相接區段並回寫覆蓋率（離開頁面時觸發）。

        ⚠️ **normalize 是儲存壓縮，不是正確性前提**——覆蓋率一律先聯集再算，所以
        沒跑成功只是列數變多。AC 7（異常離開後下次仍正確）因此自然成立。

        **不檢查解鎖狀態**（見模組 docstring 第 4 道守門）：本方法加不出任何進度，
        而掛上去會讓「教師把學員正在看的項目鎖回去」時，前端 `pagehide` 的收尾整批失敗。
        """
        context = await self._repo.video_context(db, video_id)
        if context is None:
            raise _NOT_FOUND
        video, item_id, course_id = context
        try:
            await self._guard_write(db, course_id=course_id, user_id=operator.user_id)
        except _PreviewOnly:
            return await self._preview_result(db, video_id=video_id, user_id=operator.user_id)

        snapshot = await self._repo.list_intervals_with_ids(db, user_id=operator.user_id, video_id=video_id)
        merged = list(merge_segments([seg for _, seg in snapshot]))
        if len(merged) != len(snapshot):
            # 只在真的能壓縮時才寫——沒有重疊時 DELETE + INSERT 是白費。
            # 刪除限定在快照讀到的 id 內，併發寫入的區段不會被掃掉（見 repository docstring）。
            await self._repo.replace_intervals(
                db,
                user_id=operator.user_id,
                video_id=video_id,
                replaced_ids=[interval_id for interval_id, _ in snapshot],
                segments=merged,
                operator=operator,
            )
        return await self._recompute(
            db,
            video_id=video_id,
            course_id=course_id,
            item_id=item_id,
            duration_sec=video.duration_sec,
            material_id=video.material_id,
            last_position_sec=None,  # normalize 不帶位置——不可把續看點清掉
            operator=operator,
        )

    async def mark_item_viewed(self, db: AsyncSession, item_id: int, *, operator: OperatorInfo) -> ItemViewedResult:
        """文件 / 說明文字項目「開啟即完成」（AC 13 / FR-08）。

        **含影片的教材不走這裡**——那類的完成由覆蓋率決定。若對含影片的教材呼叫本
        端點，只更新「上次檢視項目」而不標記完成，否則學員點一下就跳過了 80% 的要求。

        ⚠️ 本端點是**唯一能無條件產生 `IS_COMPLETED=true` 的路徑**，故解鎖判定
        （守門 4）在此最為關鍵。
        """
        context = await self._repo.item_context(db, item_id)
        if context is None:
            raise _NOT_FOUND
        item, course_id = context
        try:
            await self._guard_write(db, course_id=course_id, user_id=operator.user_id, item_id=item_id)
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

    async def _guard_write(self, db: AsyncSession, *, course_id: int, user_id: str, item_id: int | None = None) -> None:
        """四道守門（順序見模組 docstring）。

        Args:
            item_id: 給定時一併檢查解鎖狀態（守門 4）。`normalize` 傳 `None`——它加不出
                進度，掛上去只會讓收尾補送在項目被鎖回去後整批失敗。

        Raises:
            AppError: 404 兩者皆非 / 課程未發布 / 項目尚未解鎖；409 `ET_PROGRESS_001`
                課程已關閉。
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
        if course.status == COURSE_DRAFT:
            # 目前不可達（已發布課程無退回草稿之路徑，且草稿沒有邀請碼可加入），
            # 但與 `learning/service.structure` 的草稿保密處理對齊——日後新增下架功能時
            # 這裡不必再想一次。
            raise _NOT_FOUND
        if course.status == COURSE_CLOSED:
            raise _CLOSED
        if item_id is not None and await self._is_locked(db, course_id=course_id, user_id=user_id, item_id=item_id):
            # **鎖定中的項目視同不存在**——回 404 而非 403，與其餘以 id 定址的端點一致，
            # 不讓回應差異變成「這個 item_id 存在」的 oracle。
            raise _NOT_FOUND

    async def _is_locked(self, db: AsyncSession, *, course_id: int, user_id: str, item_id: int) -> bool:
        """單一項目是否鎖定。

        **已完成者永不鎖定**（`is_item_unlocked` 的同一條規則）——先問這一題可讓「回頭
        複習已學過的項目」只花一次查詢，而不必為了得到同一個答案重算整門課的解鎖狀態。
        本方法在最高頻的 `report_intervals` 路徑上，那條捷徑正好覆蓋重看的情形。
        """
        if item_id in await self._repo.completed_item_ids(db, user_id=user_id, course_id=course_id):
            return False
        return item_id in await self._locked_ids(db, course_id=course_id, user_id=user_id)

    async def _locked_ids(self, db: AsyncSession, *, course_id: int, user_id: str) -> frozenset[int]:
        """該學員在此課程中**目前鎖定**的項目。

        與側欄旗標（`learning/service._item_nodes`）共用 `build_item_state` 與
        `locked_item_ids`——兩邊各算一份的話，分岔的表現會是「側欄顯示解鎖但後端擋下」，
        一個學員完全無法理解、也不會有測試自然抓到的狀態。
        """
        completed_ids = await self._repo.completed_item_ids(db, user_id=user_id, course_id=course_id)
        chapters = await self._learning.chapters(db, course_id)
        rows = await self._learning.items_with_titles(db, [c.chapter_id for c in chapters])
        by_chapter: dict[int, list[tuple[int, str]]] = {}
        for item, _, _ in rows:
            by_chapter.setdefault(item.chapter_id, []).append((item.item_id, item.item_type))
        return locked_item_ids(
            [
                [
                    build_item_state(item_id, item_type, completed_ids=completed_ids)
                    for item_id, item_type in by_chapter.get(c.chapter_id, [])
                ]
                for c in chapters
            ]
        )

    async def _recompute(
        self,
        db: AsyncSession,
        *,
        video_id: int,
        course_id: int,
        item_id: int,
        duration_sec: int,
        material_id: int,
        last_position_sec: int | None,
        operator: OperatorInfo,
    ) -> VideoProgress:
        """由區段重算覆蓋率 → 回寫快取 → 更新該影片所屬項目的完成狀態。

        `item_id` 由呼叫端沿**同一條反查鏈**取得（見 `repository.video_context`），
        不在此處另外由 `material_id` 反查——那會讓「影片的課程」與「項目的課程」有機會
        來自兩門不同的課。
        """
        snapshot = await self._repo.list_intervals_with_ids(db, user_id=operator.user_id, video_id=video_id)
        segments = [seg for _, seg in snapshot]
        if len(segments) > _MAX_INTERVAL_ROWS:
            # 就地壓縮，不等前端呼叫 normalize——聯集不變，故覆蓋率不受影響
            segments = list(merge_segments(segments))
            await self._repo.replace_intervals(
                db,
                user_id=operator.user_id,
                video_id=video_id,
                replaced_ids=[interval_id for interval_id, _ in snapshot],
                segments=segments,
                operator=operator,
            )
        coverage = coverage_pct(segments, duration_sec=duration_sec)
        row = await self._repo.upsert_video_progress(
            db,
            user_id=operator.user_id,
            video_id=video_id,
            coverage=coverage,
            last_position_sec=last_position_sec,
            operator=operator,
        )

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
