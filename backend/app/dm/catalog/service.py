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
from app.dm.document.models import DmDocTag

# 分類碼字元集：僅英數（作為 PK、且下游 next_doc_id 以此碼組 LIKE pattern，須排除萬用字元）
_CODE_PATTERN = re.compile(r"^[A-Za-z0-9]+$")


@dataclass(frozen=True)
class SoftRetireResult:
    """AUDIENCE 停用之受影響統計（既有可見性不收回）。"""

    affected_docs: int
    affected_viewers: int


class CatalogService:
    """受控資料維護（分類為代表；func / tag 同一機制）。"""

    async def create_category(self, db: AsyncSession, *, code: str, name: str, operator: str) -> DmCategory:
        """新增自訂分類（分類碼建立後鎖定＝PK；格式須英數 422 DM_CATALOG_003；重複碼 409 DM_CATALOG_001）。"""
        if not _CODE_PATTERN.match(code):
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

    async def soft_retire_audience_tag(self, db: AsyncSession, *, tag_id: int, operator: str) -> SoftRetireResult:
        """停用 AUDIENCE 可見對象（soft-retire）：is_enabled=False + 回傳受影響文件 / 閱覽者數。

        既有 DM_DOC_TAG / DM_USER_TAG 列保留（不收回可見性），僅擋後續指派。
        """
        tag = await db.scalar(select(DmTag).where(DmTag.tag_id == tag_id))
        if tag is None:
            raise AppError(status_code=404, detail="查無此可見對象", error_code="DM_CATALOG_002")
        affected_docs = (
            await db.scalar(select(func.count()).select_from(DmDocTag).where(DmDocTag.tag_id == tag_id)) or 0
        )
        affected_viewers = (
            await db.scalar(select(func.count()).select_from(DmUserTag).where(DmUserTag.tag_id == tag_id)) or 0
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
