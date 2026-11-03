"""受控資料維護共用服務（T020）。

分類 / func_name / 標籤之共通維護：新增 / 改名 / 啟用停用；**不開放刪除**（淘汰改停用），
停用後既有引用 100% 保留、僅影響後續新增 / 編輯與搜尋之下拉。AUDIENCE 組之停用採 **soft-retire**：
不收回既有可見性（`DM_DOC_TAG` / `DM_USER_TAG` 既有列保留），僅擋後續指派，並回傳受影響文件 / 閱覽者數。

維護 UI 於平台 DP 後台「系統參數與清單」畫面，經 catalog 轉接層呼叫本服務（比照 roles 轉接層）。
"""

import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.dm.audience.models import DmUserTag
from app.dm.catalog.models import DmCategory, DmTag
from app.dm.document.models import DmDocTag, DmDocVersion, DmVersionTag

# 分類碼字元集：僅英數（作為 PK、且下游 next_doc_id 以此碼組 LIKE pattern，須排除萬用字元）
_CODE_PATTERN = re.compile(r"^[A-Za-z0-9]+$")
# 對應 DM_CATEGORY.CATEGORY_CODE 之 VARCHAR(10)
_MAX_CODE_LEN = 10
#: 標籤快照尚未套用至文件層的版本狀態（#388 L1）。
#:
#: ⛔ **不含 `PUBLISHED` / `SUPERSEDED`**：其快照已於核准時套用成 `DM_DOC_TAG` 列，一併計入
#: 等於同一筆設定數兩次。
#:
#: ⛔ **也不含 `REJECTED`，而且那不是低估**：送簽要求版本為 `DRAFT`（`dm/editor/service.py`
#: 的 `submit`，否則 `DM_REVIEW_002`），而全庫**沒有任何地方**把版本自 `REJECTED` 設回
#: `DRAFT`——寫 `ver.status` 的只有 `dm/personal/service.py` 的撤回與 `dm/review/center_service.py`
#: 的退回，兩者都是自 `PENDING_REVIEW` 轉出。⇒ `REJECTED` 是版本終態，其快照**永遠不會**
#: 套用至文件層，計入反而高估。
_IN_FLIGHT_VERSION_STATUSES = ("DRAFT", "PENDING_REVIEW")


@dataclass(frozen=True)
class SoftRetireResult:
    """AUDIENCE 停用之受影響統計（既有可見性不收回）。"""

    affected_docs: int
    affected_viewers: int


class CatalogService:
    """受控資料維護（分類為代表；func / tag 同一機制）。"""

    async def create_category(self, db: AsyncSession, *, code: str, name: str, operator: str) -> DmCategory:
        """新增自訂分類（分類碼建立後鎖定＝PK；格式須英數 422 DM_CATALOG_003；重複碼 409 DM_CATALOG_001）。

        長度上限對應 `CATEGORY_CODE` 之 VARCHAR(10)——未擋會在 INSERT 時由 DB 拋
        `value too long`，落成未攔截的 500。#182 讓 DP 後台第一次可外部呼叫此路徑。
        """
        if not _CODE_PATTERN.match(code) or len(code) > _MAX_CODE_LEN:
            raise AppError(status_code=422, detail="代碼格式不合法，僅允許英文與數字", error_code="DM_CATALOG_003")
        exists = await db.scalar(select(DmCategory.category_code).where(DmCategory.category_code == code))
        if exists is not None:
            raise AppError(status_code=409, detail="此分類碼已存在，請使用其他分類碼", error_code="DM_CATALOG_001")
        cat = DmCategory(
            category_code=code, category_name=name, is_builtin=False, created_user=operator, created_date=utcnow()
        )
        db.add(cat)
        await db.flush()
        return cat

    async def rename_category(self, db: AsyncSession, *, code: str, new_name: str, operator: str) -> DmCategory:
        """改名（分類碼不可改；查無 404 DM_CATALOG_002）。"""
        cat = await self._require_category(db, code)
        cat.category_name = new_name
        cat.updated_user = operator
        cat.updated_date = utcnow()
        await db.flush()
        return cat

    async def set_category_enabled(self, db: AsyncSession, *, code: str, enabled: bool, operator: str) -> DmCategory:
        """啟用 / 停用（不刪除；停用後既有文件引用保留、僅影響後續下拉）。"""
        cat = await self._require_category(db, code)
        cat.is_enabled = enabled
        cat.updated_user = operator
        cat.updated_date = utcnow()
        await db.flush()
        return cat

    async def soft_retire_audience_tag(
        self, db: AsyncSession, *, tag_id: int, operator: str, is_unit: bool = False
    ) -> SoftRetireResult:
        """停用可見對象標籤（soft-retire）：is_enabled=False + 回傳受影響文件 / 閱覽者數。

        既有 DM_DOC_TAG / DM_USER_TAG 列保留（不收回可見性），僅擋後續指派。

        `is_unit` 決定計數比對哪一欄（#437）：可見對象為 (單位, 職位) 配對，職位存 `TAG_ID`、
        單位存 `UNIT_TAG_ID`。停用單位若仍以 `TAG_ID` 比對，兩個計數恆為 0——管理者會看到
        「不影響任何文件」而停掉一個實際上綁著大量文件的單位，且不會有任何錯誤。

        兩個計數皆須濾 `DELETED = 0`：標籤關聯採**軟刪除復用**（移除＝`deleted=1` 不刪列，
        以避開唯一約束），不濾會把已移除的文件關聯與已撤銷的閱覽者授權算進去。本數字自 #182
        起會呈現給管理者作為「要不要停用」的依據，高估會誤導該判斷。

        `affected_docs` 併計**已生效**（`DM_DOC_TAG`）與**在途草稿**（`DM_VERSION_TAG`）兩種
        設定列（#388 L1）。只數前者會漏掉所有尚未核准的設定，而管理者要決定的正是「停用後
        會發生什麼」——標籤自 #377 起於草稿階段只寫版本層，核准時才套用至文件層。

        🔴 **數的是配對列數，不是不重複的文件數**（#742，DP 端提示用語已對齊為「組…設定」）。
        故兩來源**直接相加、不做 UNION 去重**：同一份文件的同一組配對若已生效且又出現在
        在途草稿，那是兩筆各自存在的設定，分開計。

        ⚠️ **本數字不是任何一邊的界線，⛔ 勿標示為「至少」**：已廢止文件的 `DM_DOC_TAG` 列
        仍留著且計入（高估）。低估那一半已由本次補上，高估那一半仍在——理由見
        `frontend/src/dp/params/useControlled.ts` 的 `affectedText`。

        Args:
            tag_id: 要停用之標籤。
            operator: 操作者（寫入稽核欄位）。
            is_unit: True 時依 `UNIT_TAG_ID` 計數（單位組），否則依 `TAG_ID`（職位組）。
        """
        tag = await db.scalar(select(DmTag).where(DmTag.tag_id == tag_id))
        if tag is None:
            raise AppError(status_code=404, detail="查無此可見對象", error_code="DM_CATALOG_002")
        doc_col = DmDocTag.unit_tag_id if is_unit else DmDocTag.tag_id
        ver_col = DmVersionTag.unit_tag_id if is_unit else DmVersionTag.tag_id
        user_col = DmUserTag.unit_tag_id if is_unit else DmUserTag.tag_id
        effective_docs = (
            await db.scalar(select(func.count()).select_from(DmDocTag).where(doc_col == tag_id, DmDocTag.deleted == 0))
            or 0
        )
        in_flight_docs = (
            await db.scalar(
                select(func.count())
                .select_from(DmVersionTag)
                .join(DmDocVersion, DmDocVersion.version_id == DmVersionTag.version_id)
                .where(
                    ver_col == tag_id,
                    DmVersionTag.deleted == 0,
                    DmDocVersion.deleted == 0,
                    DmDocVersion.status.in_(_IN_FLIGHT_VERSION_STATUSES),
                )
            )
            or 0
        )
        affected_docs = effective_docs + in_flight_docs
        affected_viewers = (
            await db.scalar(
                select(func.count()).select_from(DmUserTag).where(user_col == tag_id, DmUserTag.deleted == 0)
            )
            or 0
        )
        tag.is_enabled = False
        tag.updated_user = operator
        tag.updated_date = utcnow()
        await db.flush()
        return SoftRetireResult(affected_docs=affected_docs, affected_viewers=affected_viewers)

    async def _require_category(self, db: AsyncSession, code: str) -> DmCategory:
        cat = await db.scalar(select(DmCategory).where(DmCategory.category_code == code))
        if cat is None:
            raise AppError(status_code=404, detail="查無此分類", error_code="DM_CATALOG_002")
        return cat
