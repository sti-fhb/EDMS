"""已發布課程的編輯寫入暫存區（#631 PR 2）。

## 這支的介面**刻意**與既有 repository 不同

| | 既有 repository（如 `EtChapterRepository`）| 本 writer |
|---|---|---|
| 寬度 | 8 支，**型別專屬** | 4 支，**泛型於實體型別** |
| `soft_delete_with_cascade` | 連帶刪學員進度、作答明細、完課戳記 | **沒有對應物**——cascade 是
  「更新」套用時才做（`stage_apply._DELETERS`）|
| `resequence_remaining` | 刪除後補順序 | 同上，套用時由 `_park_sort_orders` 處理 |
| `bump_version` | 活表列的樂觀鎖 | 暫存列**自己的** `VERSION`，兩者計數獨立 |

⛔ **不要為了「統一介面」把兩者塞進同一個抽象。** 兩種模式做的事本來就不同，逼它們
一樣只會製造一個名字底下兩種語意——而那正是日後有人改錯邊的地方。

service 的結構因此是「決策點共用、分支不共用」：

```python
course = await self._require_owned(db, course_id, operator.user_id)   # 既有，不動
if is_staged(course):
    await self._stage_writer.append(...)
    return
# 以下草稿路徑：既有 repository，一行不動
```

🔴 **「漏改一支」這個風險本模組擋不住**——它只能靠
`tests/integration/et/test_et_staged_write_paths.py` 的逐端點列舉。新增內容編輯端點時
必須同時補那張清單。
"""

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.constants import COURSE_DRAFT
from app.et.course.models import EtCourseContentStage
from app.et.course.stage_entities import SPEC_BY_TYPE, dumps_payload, parse_payload, payload_fields
from app.et.course.stage_repository import EtCourseStageRepository
from app.et.course.stage_rules import ENTITY_COURSE

logger = logging.getLogger(__name__)


def is_staged(course: Any) -> bool:
    """這門課的內容編輯要不要走暫存區。

    **草稿以外都要**（已發布、已關閉）。判準是「有沒有學員看得到的版本」：

    - 草稿沒有學員、沒有人開得了章節 ⇒ 不需版本化，編輯直接生效
    - 已關閉的課程學員仍可唯讀回看（`is_effectively_closed` 對 `CLOSED` 回 `True`，
      但學員端照樣讀得到內容）⇒ **也有「學員看得到的版本」**，故同樣走暫存

    ⚠️ 用 `!= COURSE_DRAFT` 而非列舉 `{PUBLISHED, CLOSED}`：日後若新增狀態，預設落在
    「要暫存」這一邊——那是 fail-safe 的方向（內容不會意外立即生效）。
    """
    return course.status != COURSE_DRAFT


@dataclass(frozen=True)
class StageRef:
    """一個暫存節點的位置。"""

    stage_id: int
    course_id: int


@dataclass(frozen=True)
class StageNodeView:
    """一個暫存節點的完整內容（`payload` 已解析成 dict）。

    供各模組的**讀取路徑**組出「教師編輯中的樣子」。與 `stage_rules.StageNode` 的差別
    只有多一個 `course_id`——後者是整棵樹一起載入時用的，樹的擁有者已知，單獨取一個
    節點時則需要它來做授權。
    """

    stage_id: int
    course_id: int
    entity_type: str
    source_id: int | None
    parent_stage_id: int | None
    sort_order: int
    version: int
    payload: dict[str, Any]


def _view(row: EtCourseContentStage) -> StageNodeView:
    """ORM 列 → `StageNodeView`。`PAYLOAD` 不是 JSON object 時明確報錯。

    ⚠️ 與 `stage_repository.load_tree` 的 `_payload` 同一道守門：非 dict 時下游
    `payload.get(...)` 會拋難讀的 `AttributeError`，而那是 500。
    """
    parsed = json.loads(row.payload)
    if not isinstance(parsed, dict):
        logger.error("ET 暫存列的 PAYLOAD 不是 JSON object：stage_id=%s type=%s", row.stage_id, type(parsed).__name__)
        raise AppError(
            status_code=500,
            detail="課程內容暫存資料異常，請重新載入後再試",
            error_code="ET_STAGE_001",
        )
    return StageNodeView(
        stage_id=row.stage_id,
        course_id=row.course_id,
        entity_type=row.entity_type,
        source_id=row.source_id,
        parent_stage_id=row.parent_stage_id,
        sort_order=row.sort_order,
        version=row.version,
        # ⚠️ ISO 8601 還原成 `datetime`（#720），同 `stage_repository._payload`。
        payload=parse_payload(row.entity_type, parsed),
    )


def exposed_id(*, source_id: int | None, stage_id: int) -> int:
    """暫存節點對外（前端 / API）呈現的 id。

    🔴 **正負號把兩個號碼空間徹底隔開。**

    `ET_CHAPTER` 等活表與 `ET_COURSE_CONTENT_STAGE` 是各自獨立的 identity 序列，**號碼
    重疊是必然**。若兩種 id 都用正數，`PUT /chapters/{id}` 這種沒有課程上下文的端點就
    分不出收到的是哪一種——而「先查暫存、查不到再查活表」會在同一位教師同時有草稿課與
    已發布課時解析到**錯的那一筆**，且不會報錯，只會改錯東西。

    | 節點 | 對外 id | 為何 |
    |---|---|---|
    | 既有內容（有 `SOURCE_ID`）| **活表 id**（正數）| 與今天完全相同，前端無感 |
    | 本次編輯新增的（無 `SOURCE_ID`）| **`-STAGE_ID`**（負數）| 它還不存在於活表，負號正好表達這件事 |

    ⚠️ 連帶代價：編輯端點的 `Path(ge=1)` 要放寬為允許負數。漏改一處的症狀是 422
    ——**看得見**，不是靜默走錯路。
    """
    return source_id if source_id is not None else -stage_id


class EtCourseStageWriter:
    """暫存區的編輯操作。

    ⚠️ 每一支都會先 `ensure_seeded`——教師的第一次編輯必須先把活表的內容樹整棵複製
    進來，否則暫存區只有那一筆新編輯，「更新」時會把其餘內容全部當成「教師刪了它」。

    🔴 **呼叫端必須先 `lock_course`**（見該方法）。本類別不自己取鎖：鎖必須涵蓋
    「解析 id → 寫入」整段，而解析發生在呼叫端。
    """

    def __init__(self, stage: EtCourseStageRepository | None = None) -> None:
        self._stage = stage or EtCourseStageRepository()

    async def lock_course(self, db: AsyncSession, course_id: int) -> None:
        """取課程行鎖——**任何暫存寫入的第一步**，與「更新」互斥。

        ## 不取會怎樣（2026-10-16 security review H-1 / code review HIGH 1）

        編輯與「更新」是兩個獨立的交易，而 `update_published` 的流程是
        `load_tree` → `apply_stage` → `clear(stage_ids=那一批)`。`clear` **刻意只清
        載入的那一批**（見 `stage_repository.clear`），於是：

        | | R1＝按「更新」 | R2＝新增章節 |
        |---|---|---|
        | T0 | `lock_course` → `load_tree` 取得 N 列 | |
        | T1 | 檢核、寫活表 | `has_stage` 在自己的快照仍看得到那 N 列 ⇒ **不 reseed** ⇒ 插入 1 列 |
        | T2 | `clear(那 N 列)` → COMMIT | COMMIT |

        結果暫存區只剩 R2 那一列。教師看到「課程章節全不見了」，照缺漏提示補一個項目
        再按一次更新 ⇒ `_delete_removed` 把**整棵活表內容樹**判為「教師刪了」⇒ 連帶
        軟刪**全班學員的進度、作答明細與完課戳記**。

        ⛔ 不可改成只在 `ensure_seeded` 內取鎖：那太晚了。父節點的 id 在呼叫端就解析
        完了，鎖必須蓋住「解析 → 寫入」整段，否則仍可插出指向已被 `clear` 掉的父節點的
        節點，而那種樹會讓此後**每一次**「更新」都 500，且 UI 看不到它、無法刪除。

        ⚠️ 同課程的編輯請求因此互相排隊。可接受——只有擁有者能編輯，競爭者是「同一個人
        的兩個分頁」。
        """
        await self._stage.lock_course(db, course_id)

    async def ensure_seeded(self, db: AsyncSession, course_id: int, operator: OperatorInfo) -> None:
        """暫存區是空的就先從活表種一棵樹；**結構過期的樹整棵換掉**。

        ⚠️ 呼叫端須已持有 `lock_course`——否則兩個分頁的「第一次編輯」會雙雙看到
        `has_stage` 為假、各自 seed 一次，第二個撞唯一索引
        `UX_ET_COURSE_CONTENT_STAGE_SOURCE` 而回 500。

        ## 🔴 #720 之前種下的樹沒有 `COURSE` 節點

        那種樹會讓 `course_node()` 回 `None`、`to_course_snapshot` 拋 `ValueError`——
        也就是部署當下正開著編輯頁的教師，下一個動作直接 500。

        ⇒ 偵測到就**整棵丟掉重種**，而不是寫進部署步驟要人手動 `DELETE`。理由是後者
        靠的是「下一個人記得」，而漏做的後果是正式環境的 500；自己修好則漏做的後果是
        沒有後果。代價是那位教師這一輪未生效的編輯會消失——而他本來就會在 #720 的
        「離開即放棄」下失去它（`discard_unkept` 同樣丟棄無課程節點的樹）。

        ⚠️ 判準是「有沒有課程節點」而非版本號：暫存表沒有結構版本欄位，而這個判準
        **直接對應那個會爆的前提**，不需要第二個要維護的事實。

        🔴 **問的時候刻意不帶 `DELETED = 0`**，與 `has_stage` 同一個理由。帶了的話，
        「這棵樹從來沒有課程節點」（舊結構，該重種）會與「課程節點被軟刪了」（不該
        重種——重種會把教師刪掉的內容整批復活，正是
        `test_教師刪光章節後不得重新_seed` 要防的事）**無法區分**。
        正式環境到不了後者（教師沒有刪課程節點的路徑，`_NEVER_DELETED` 亦擋著），
        但分不出來的判準遲早會在別的地方分錯邊。
        """
        if not await self._stage.has_stage(db, course_id):
            await self._stage.seed_from_live(db, course_id, operator)
            return
        ever_had_course_node = await db.scalar(
            select(EtCourseContentStage.stage_id).where(
                EtCourseContentStage.course_id == course_id,
                EtCourseContentStage.entity_type == ENTITY_COURSE,
            )
        )
        if ever_had_course_node is None:
            logger.warning("ET 暫存樹缺少課程節點（#720 之前的結構），整棵重種 course_id=%s", course_id)
            await self._stage.discard(db, course_id)
            await self._stage.seed_from_live(db, course_id, operator)

    async def append(
        self,
        db: AsyncSession,
        course_id: int,
        entity_type: str,
        *,
        parent_stage_id: int | None,
        payload: Mapping[str, Any],
        operator: OperatorInfo,
    ) -> int:
        """在同層末尾新增一個節點，回傳其 `STAGE_ID`。

        `SOURCE_ID` 為 `None`——活表還沒有這一列，要到「更新」套用時才建立。
        """
        await self.ensure_seeded(db, course_id, operator)
        now = utcnow()
        last = await db.scalar(
            select(func.max(EtCourseContentStage.sort_order)).where(
                EtCourseContentStage.course_id == course_id,
                EtCourseContentStage.entity_type == entity_type,
                EtCourseContentStage.parent_stage_id.is_(parent_stage_id)
                if parent_stage_id is None
                else EtCourseContentStage.parent_stage_id == parent_stage_id,
                EtCourseContentStage.deleted == 0,
            )
        )
        row = EtCourseContentStage(
            course_id=course_id,
            entity_type=entity_type,
            source_id=None,
            parent_stage_id=parent_stage_id,
            sort_order=(last or 0) + 1,
            payload=dumps_payload(entity_type, payload),
            version=0,
            created_user=operator.user_id,
            created_date=now,
        )
        db.add(row)
        await db.flush()
        return row.stage_id

    async def update_payload(
        self,
        db: AsyncSession,
        stage_id: int,
        *,
        version: int,
        payload: Mapping[str, Any],
        operator: OperatorInfo,
    ) -> int:
        """改一個節點的欄位值，**帶暫存列自己的樂觀鎖**。

        🔴 **`payload` 是整份取代，不是合併。** 沒帶到的 key 會消失——而 `_upsert` 的
        規則是「payload 裡沒有的欄位就不碰活表」，所以消失的欄位會**靜默保留活表舊值**，
        看起來像「我改了沒生效」。章節只有 `chapter_name` 一個欄位所以目前無感，但
        教材、測驗有多個欄位，呼叫端必須送完整的一份。

        ⚠️ 型別也必須相符：拿項目節點的 id 來送章節 payload，`item_type` 會整個不見
        （見 `resolve_new` 的 `entity_type` 守門）。

        Returns:
            命中列數——呼叫端以 `ensure_version_matched` 判定衝突，與草稿路徑同一形狀。
        """
        # 🔴 **保留非欄位的旗標**（2026-10-18 code review HIGH 1）。
        #
        # 「整份取代」只該作用在**內容欄位**。payload 裡還寄著非欄位的工作階段旗標
        # （目前是 #361 的 `__require_retest`），整份覆寫會把它洗掉：
        #
        #   教師在某題勾「要求重測」存檔 → 旗標寫進 QUIZ 節點
        #   → 他接著改測驗名稱存檔（沒勾）→ `update_payload` 五個欄位整份覆寫
        #   → **旗標消失** → 按「更新」時作答過的學員不會被退回，也不會收到信
        #
        # 全程沒有任何錯誤訊息。原本的測試只覆蓋「單次請求內勾選」，跨請求那條沒有。
        #
        # ⚠️ 判準是「不在 `payload_fields` 裡」而非「以 `__` 開頭」——前者由 model 推導、
        # 不會因為命名慣例改變而失效。
        existing = await self.node_by_stage_id(db, stage_id)
        if existing is None:
            # 這列已不在（另一個分頁按了「取消」或「更新」）。下面的 UPDATE 與本次回讀
            # 的 where 條件相同（`DELETED = 0`），命中列數必為 0，故直接回 0 等價；
            # ⚠️ 但少了這道短路，`dumps_payload` 會因為拿不到 `entity_type` 而對課程的
            # `datetime` 爆 `TypeError`——把一個乾淨的 409 變成 500。
            return 0
        merged = dict(payload)
        spec = SPEC_BY_TYPE.get(existing.entity_type)
        if spec is not None:
            fields = payload_fields(spec)
            merged = {k: v for k, v in existing.payload.items() if k not in fields} | merged

        result = await db.execute(
            update(EtCourseContentStage)
            .where(
                EtCourseContentStage.stage_id == stage_id,
                EtCourseContentStage.version == version,
                EtCourseContentStage.deleted == 0,
            )
            .values(
                payload=dumps_payload(existing.entity_type, merged),
                version=EtCourseContentStage.version + 1,
                updated_user=operator.user_id,
                updated_date=utcnow(),
            )
        )
        await db.flush()
        return result.rowcount

    async def bump_version(self, db: AsyncSession, stage_id: int, version: int, operator: OperatorInfo) -> int:
        """只遞增暫存列的 `VERSION`，不動 payload——供「重排」這種改動下層順序的操作。

        與草稿路徑同一形狀：重排改的是**下一層**的順序，所以用上一層的版本當併發令牌，
        而不遞增下層各列的版本（否則正在編輯該教材的另一裝置會無故衝突，
        違反 `FR-ET-US3-15`）。

        Returns:
            命中列數——呼叫端以 `ensure_version_matched` 判定衝突。
        """
        result = await db.execute(
            update(EtCourseContentStage)
            .where(
                EtCourseContentStage.stage_id == stage_id,
                EtCourseContentStage.version == version,
                EtCourseContentStage.deleted == 0,
            )
            .values(
                version=EtCourseContentStage.version + 1,
                updated_user=operator.user_id,
                updated_date=utcnow(),
            )
        )
        await db.flush()
        return result.rowcount

    async def children_of(
        self, db: AsyncSession, course_id: int, entity_type: str, parent_stage_id: int | None
    ) -> list[StageNodeView]:
        """某節點底下指定型別的子節點，依 `SORT_ORDER` 排序。"""
        stmt = select(EtCourseContentStage).where(
            EtCourseContentStage.course_id == course_id,
            EtCourseContentStage.entity_type == entity_type,
            EtCourseContentStage.deleted == 0,
        )
        stmt = stmt.where(
            EtCourseContentStage.parent_stage_id.is_(None)
            if parent_stage_id is None
            else EtCourseContentStage.parent_stage_id == parent_stage_id
        )
        rows = await db.scalars(stmt.order_by(EtCourseContentStage.sort_order, EtCourseContentStage.stage_id))
        return [_view(r) for r in rows.all()]

    async def course_node(self, db: AsyncSession, course_id: int) -> StageNodeView | None:
        """課程本體的暫存節點（#720）。

        課程是暫存森林的樹根之一（`PARENT_STAGE_ID` 為 `NULL`），所以就是
        `children_of(..., ENTITY_COURSE, None)` 的唯一一列。

        它同時是**課程層的併發令牌**：基本資料與章節重排都打在這一列的 `VERSION` 上，
        與 #720 之前兩者都打在 `ET_COURSE.VERSION` 上是同一個語意，只是換了記錄的位置。

        Returns:
            `None` 代表**暫存區還沒 seed**。此時令牌仍在活表的 `ET_COURSE.VERSION`，
            而 `seed_from_live` 會原值帶進暫存列，所以前端跨越「第一次編輯」那條界線時
            手上的版本不會失效。
        """
        nodes = await self.children_of(db, course_id, ENTITY_COURSE, None)
        return nodes[0] if nodes else None

    async def has_stage(self, db: AsyncSession, course_id: int) -> bool:
        """該課程是否有編輯工作階段開著。語意見 `stage_repository.has_stage`。"""
        return await self._stage.has_stage(db, course_id)

    async def node_by_stage_id(
        self, db: AsyncSession, stage_id: int, entity_type: str | None = None
    ) -> StageNodeView | None:
        """以 `STAGE_ID` 直接取節點（已解析 payload）。供已經握有 ref 的呼叫端回讀。

        Args:
            entity_type: 帶了就**核對型別**，不符視同查無（並留 log）。
                ⚠️ `STAGE_ID` 是整張表共用的 identity，11 種實體同一個號碼空間；少了這道
                核對，把測驗的 stage_id 誤傳進教材的回讀會拿到一份**型別不符的 payload**
                而完全不報錯（2026-10-18 security review L-2）。今天五個呼叫端的 ref 都
                來自型別化的解析器，所以是縱深防禦；⛔ 新呼叫端一律要帶。

                `None` 只保留給 `update_payload`——它正是要問「這列是什麼型別」，
                先知道型別才能查的話就成了循環。
        """
        row = await db.scalar(
            select(EtCourseContentStage).where(
                EtCourseContentStage.stage_id == stage_id, EtCourseContentStage.deleted == 0
            )
        )
        if row is None:
            return None
        if entity_type is not None and row.entity_type != entity_type:
            logger.error(
                "暫存節點型別不符：stage_id=%s 實際=%s 預期=%s",
                stage_id,
                row.entity_type,
                entity_type,
            )
            return None
        return _view(row)

    async def set_payload_flag(
        self, db: AsyncSession, stage_id: int, key: str, value: Any, operator: OperatorInfo
    ) -> None:
        """在 payload 裡設一個**非內容欄位**的旗標，**刻意不遞增 `VERSION`**。

        🔴 不遞增是重點。`VERSION` 是教師那一端的樂觀鎖令牌，前端拿著載入當下的值。
        旗標是「這次編輯工作階段的意圖」（例如 #361 的要求重測）、不是教師改的內容，
        為它推進版本會讓他**下一次存檔無故 409**，而畫面上看不出為什麼。

        ⚠️ 旗標的 key 必須**不是**該實體的欄位名——`stage_apply._upsert` 只寫
        `payload_fields(spec)` 列出的 key，所以非欄位的旗標會被自動忽略、不會進活表。
        ⛔ 不要用與欄位同名的 key。

        ⚠️ 寫回一律經 `dumps_payload`：這裡是**讀出整份 payload、改一個 key、再寫回去**，
        而讀出來的 `node.payload` 已由 `parse_payload` 把 ISO 字串還原成 `datetime`。
        裸 `json.dumps` 會對那些值爆掉——今天只有 QUIZ 用得到旗標所以碰不到，但
        「讀回來還原、寫回去要編碼」是這張表的通則，不是哪個型別的特例。

        Args:
            value: 傳 `None` 代表**清除**該旗標（而非寫入 null）。旗標必須可以取消——
                #361 的重測後果是「全班作答過的人被退回並收到信」，教師誤勾卻只能放棄
                整個工作階段的話，代價不成比例。
        """
        node = await self.node_by_stage_id(db, stage_id)
        if node is None:
            return
        payload = {k: v for k, v in node.payload.items() if k != key}
        if value is not None:
            payload[key] = value
        await db.execute(
            update(EtCourseContentStage)
            .where(EtCourseContentStage.stage_id == stage_id, EtCourseContentStage.deleted == 0)
            .values(
                payload=dumps_payload(node.entity_type, payload),
                updated_user=operator.user_id,
                updated_date=utcnow(),
            )
        )
        await db.flush()

    async def node_of(self, db: AsyncSession, exposed: int, entity_type: str) -> StageNodeView | None:
        """對外 id（正負皆可）→ 暫存節點；**查不到就回 `None`**（代表沒有暫存區）。

        供**讀取路徑**使用：讀取不該因為「這門課還沒開始編輯」而報錯，回 `None` 讓
        呼叫端退回去讀活表。寫入路徑要的是 `resolve_new` + `ref_for_source` 那一組
        ——它們會在該有而沒有時拋錯，因為寫入靜默落空才是真正的問題。

        ⚠️ 正數要先知道是哪門課才查得到（`SOURCE_ID` 只在同一課程內唯一），所以這裡
        用 `(entity_type, source_id)` 全域查再回報 `course_id`——`SOURCE_ID` 指向的是
        活表的代理鍵，同一型別的活表 id 本來就全域唯一，不會撞。
        """
        stmt = select(EtCourseContentStage).where(
            EtCourseContentStage.entity_type == entity_type,
            EtCourseContentStage.deleted == 0,
        )
        stmt = stmt.where(
            EtCourseContentStage.stage_id == -exposed if exposed < 0 else EtCourseContentStage.source_id == exposed
        )
        row = await db.scalar(stmt)
        return None if row is None else _view(row)

    async def apply_order(self, db: AsyncSession, stage_ids: Sequence[int], operator: OperatorInfo) -> None:
        """依給定順序重設 `SORT_ORDER`（1 起算）。

        ⚠️ **不需要草稿路徑那種兩階段寫入**：暫存表沒有 `(父, SORT_ORDER)` 的唯一索引
        （PR 1 只對 `(COURSE_ID, ENTITY_TYPE, SOURCE_ID)` 設唯一），所以中途重複不會撞鍵。
        撞鍵的風險在「更新」套用時才出現，由 `stage_apply._park_sort_orders` 處理。
        """
        now = utcnow()
        for order, stage_id in enumerate(stage_ids, start=1):
            await db.execute(
                update(EtCourseContentStage)
                .where(EtCourseContentStage.stage_id == stage_id, EtCourseContentStage.deleted == 0)
                .values(sort_order=order, updated_user=operator.user_id, updated_date=now)
            )
        await db.flush()

    async def delete_subtree(self, db: AsyncSession, stage_id: int, operator: OperatorInfo) -> None:
        """移除一個節點與其整棵子樹。

        🔴 **必須連子樹一起移除**：只刪中間一層會讓子節點的 `PARENT_STAGE_ID` 落空，
        而那種樹會被 `stage_apply._validate_tree` 當場擋下（500 `ET_STAGE_001`）——
        教師看到的是「按更新就壞掉」，而壞的其實是刪除那一步。

        ⛔ 軟刪除（`DELETED = 1`），遵專案禁硬刪規範。

        ⚠️ **每次呼叫重載整棵樹**（2026-10-18 security review L-4，已知、刻意不修）。
        連續刪 N 個節點就是 N 次全樹查詢。母體是一門課的內容樹（章節→項目→教材／測驗
        →題目→選項，實務上數百列），而刪除是教師的逐次互動、不是批次作業，所以今天
        量不出來。改成遞迴 CTE 一次收完才是正解；⛔ 但不要順手改成「只刪這一層」——
        子節點的 `PARENT_STAGE_ID` 落空會讓此後**每次**更新都 500。
        """
        nodes = await self._stage.load_tree(db, await self._course_of(db, stage_id))
        subtree = {stage_id}
        # 巢狀最深 5 層（章節→項目→測驗→題目→選項），逐層往下收。
        for _ in range(5):
            subtree |= {n.stage_id for n in nodes if n.parent_stage_id in subtree}
        await db.execute(
            update(EtCourseContentStage)
            .where(EtCourseContentStage.stage_id.in_(subtree), EtCourseContentStage.deleted == 0)
            .values(deleted=1, updated_user=operator.user_id, updated_date=utcnow())
        )
        await db.flush()

    async def resolve_new(self, db: AsyncSession, exposed: int, entity_type: str) -> StageRef | None:
        """負數 id ⇒ 本次編輯新增的暫存節點。正數回 `None`（呼叫端走活表解析）。

        🔴 **`entity_type` 必須比對**（2026-10-16 security review M-1 / code review MEDIUM）。
        只用 `STAGE_ID` 撈會讓型別混淆成立——所有實體共用同一個 identity 序列，把某個
        選項節點的 `-STAGE_ID` 當成 `chapter_id` 送進 `PUT /chapters/{id}` 一樣撈得到：

        | 誤用 | 後果 |
        |---|---|
        | `POST /chapters/{-選項}/items` | ITEM 掛 OPTION 的樹 ⇒ 此後**每次**「更新」都 500 |
        | `PUT /chapters/{-項目}` | payload 被整份覆寫成 `{"chapter_name": …}`，
          `item_type` 消失 ⇒ 套用時 NOT NULL IntegrityError |
        | `DELETE /items/{-章節}` | 刪掉一整棵章節子樹 |

        ⚠️ 這些壞掉的節點**在編輯頁上看不到**（`_staged_chapter_items` 只走
        CHAPTER → ITEM 這條路），而本 PR 沒有「放棄暫存」的入口 ⇒ 教師自己救不回來。
        只有擁有者打得到，所以是自傷而非越權——但擋下來的成本只是多一個 WHERE 條件。

        ⚠️ 正數那條由 `ref_for_source` 負責，它本來就帶 `entity_type` 查。
        """
        if exposed >= 0:
            return None
        row = await db.scalar(
            select(EtCourseContentStage).where(
                EtCourseContentStage.stage_id == -exposed,
                EtCourseContentStage.entity_type == entity_type,
                EtCourseContentStage.deleted == 0,
            )
        )
        return None if row is None else StageRef(stage_id=row.stage_id, course_id=row.course_id)

    async def ref_for_source(
        self,
        db: AsyncSession,
        course_id: int,
        entity_type: str,
        source_id: int,
        operator: OperatorInfo,
        *,
        gone_error: AppError,
    ) -> StageRef:
        """既有內容（活表 id）在暫存區的對應節點；暫存區還沒種就先種。

        ## 「查不到」有兩種，後果完全不同

        | 情況 | 回什麼 | 為何 |
        |---|---|---|
        | 暫存區有這一列、但已被本次編輯軟刪 | `gone_error`（404）| 教師自己剛刪掉它，
          再對它操作就是「查無此物」。**正常操作可達**：雙擊刪除、另一個分頁、
          樂觀 UI 還沒失效 |
        | 真的沒有這一列 | 500 `ET_STAGE_001` | seed 漏搬了那一種實體，是程式缺陷 |

        🔴 原本兩者都回 500，訊息還寫「seed 漏搬」——而最常見的成因是上面第一種、
        教師沒做錯任何事（2026-10-16 security review M-3 / code review HIGH 2）。
        草稿路徑對同一個操作回 404，兩條路徑的行為必須一致。

        Args:
            gone_error: 已被刪除時要拋的 404（由呼叫端給，才能指出是章節還是項目）。
        """
        await self.ensure_seeded(db, course_id, operator)
        stage_id = await db.scalar(
            select(EtCourseContentStage.stage_id).where(
                EtCourseContentStage.course_id == course_id,
                EtCourseContentStage.entity_type == entity_type,
                EtCourseContentStage.source_id == source_id,
                EtCourseContentStage.deleted == 0,
            )
        )
        if stage_id is None:
            deleted_here = await db.scalar(
                select(EtCourseContentStage.stage_id).where(
                    EtCourseContentStage.course_id == course_id,
                    EtCourseContentStage.entity_type == entity_type,
                    EtCourseContentStage.source_id == source_id,
                    EtCourseContentStage.deleted == 1,
                )
            )
            if deleted_here is not None:
                raise gone_error
            # 真的沒有 ⇒ seed 漏搬了那一種實體。靜默略過會讓教師「編了沒生效」，故當場
            # 拋錯；`test_種出的樹涵蓋十一種實體` 是它的上游守門。
            #
            # ⚠️ 訊息是**固定文案**：`AppError.detail` 會原樣成為回應的 `error_message`
            # （`main.py` 的 `app_error_handler`，**含 500**），而 `source_id` 正是使用者
            # 送進來的 path 參數——原樣回吐違反 `sti-error-codes`。細節只進 log。
            logger.error(
                "ET 暫存區缺少對應節點（seed 漏搬？）：course_id=%s entity_type=%s source_id=%s",
                course_id,
                entity_type,
                source_id,
            )
            raise AppError(
                status_code=500,
                detail="課程內容暫存資料異常，請重新載入後再試",
                error_code="ET_STAGE_001",
            )
        return StageRef(stage_id=stage_id, course_id=course_id)

    @staticmethod
    async def _course_of(db: AsyncSession, stage_id: int) -> int:
        return await db.scalar(select(EtCourseContentStage.course_id).where(EtCourseContentStage.stage_id == stage_id))
