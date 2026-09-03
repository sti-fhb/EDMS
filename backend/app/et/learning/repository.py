"""ET05 學員端內容查詢（US5 / #255）。

## 授權反查鏈

取檔端點拿到的是 `video_id` / `material_id`，但授權要問的是「這門**課程**你有沒有
資格」。故本模組提供反查：

```
video_id    → material_id → item → chapter → course_id
material_id →               item → chapter → course_id
```

⚠️ **`ET_ITEM` 是那條鏈的必經節點**。教材本身不帶 `course_id`——它是被項目引用的，
反查一定要經過 `ET_ITEM`。少了這一跳就只能改用「猜」（例如信任前端傳來的
`course_id`），那等於沒有授權。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.material.models import EtMaterial, EtMaterialDoc, EtMaterialVideo
from app.et.progress.models import EtEnrollment
from app.et.quiz.models import EtQuiz


class EtLearningRepository:
    """學員端之課程結構與教材內容查詢（唯讀）。"""

    # ── 授權所需 ────────────────────────────────────────────────────────────

    async def get_course(self, db: AsyncSession, course_id: int) -> EtCourse | None:
        return await db.scalar(select(EtCourse).where(EtCourse.course_id == course_id, EtCourse.deleted == 0))

    async def is_enrolled(self, db: AsyncSession, *, user_id: str, course_id: int) -> bool:
        """該學員是否**仍具成員資格**。

        `IS_REMOVED=false` 與 `DELETED=0` 兩個條件語意不同、都必要
        （見 `EtEnrollment` docstring）。被移除者不在籍——#247 SA Q1 裁示 C 的延伸：
        他不該還能取得課程教材。
        """
        found = await db.scalar(
            select(EtEnrollment.enrollment_id).where(
                EtEnrollment.user_id == user_id,
                EtEnrollment.course_id == course_id,
                EtEnrollment.is_removed.is_(False),
                EtEnrollment.deleted == 0,
            )
        )
        return found is not None

    async def course_id_of_material(self, db: AsyncSession, material_id: int) -> int | None:
        """教材 → 課程（經 `ET_ITEM` → `ET_CHAPTER`）。

        任一跳被軟刪除即回 `None`——呼叫端據此回 404「此內容已刪除」（AC 22）。
        """
        return await db.scalar(
            select(EtChapter.course_id)
            .select_from(EtItem)
            .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
            .where(
                EtItem.material_id == material_id,
                EtItem.deleted == 0,
                EtChapter.deleted == 0,
            )
        )

    async def course_id_of_material_any(self, db: AsyncSession, material_id: int) -> int | None:
        """教材 → 課程，**不濾軟刪除**。僅供授權判定使用。

        `course_id_of_material` 會在項目 / 章節任一被刪除時回 `None`，於是呼叫端在
        「還不知道你有沒有權限」的狀態下就得回應——若回「此內容已刪除」，等於向任何
        登入者確認「這個 material_id 曾經存在」，那正是取檔端點統一回 404 要防的枚舉面。

        用本函式先取得課程做授權，**確認有權之後**才回報「已刪除」（AC 22）；無權者
        仍得到與「不存在」相同的回應。
        """
        return await db.scalar(
            select(EtChapter.course_id)
            .select_from(EtItem)
            .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
            .where(EtItem.material_id == material_id)
            .limit(1)
        )

    async def course_id_of_video(self, db: AsyncSession, video_id: int) -> int | None:
        """影片 → 課程（多一跳 `ET_MATERIAL_VIDEO` → 教材）。"""
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

    # ── 學習結構 ────────────────────────────────────────────────────────────

    async def chapters(self, db: AsyncSession, course_id: int) -> list[EtChapter]:
        rows = await db.scalars(
            select(EtChapter)
            .where(EtChapter.course_id == course_id, EtChapter.deleted == 0)
            .order_by(EtChapter.sort_order, EtChapter.chapter_id)
        )
        return list(rows)

    async def items_with_titles(
        self, db: AsyncSession, chapter_ids: list[int]
    ) -> list[tuple[EtItem, str | None, str | None]]:
        """章節下的項目，連同教材名稱與測驗名稱。

        兩個 `LEFT OUTER JOIN`——項目**必為兩者之一**（`MATERIAL_ID` / `QUIZ_ID` 互斥），
        用 INNER JOIN 會讓另一型別的項目整批消失，而側欄就會少掉一半內容。
        """
        if not chapter_ids:
            return []
        rows = await db.execute(
            select(EtItem, EtMaterial.material_name, EtQuiz.quiz_name)
            .select_from(EtItem)
            .outerjoin(EtMaterial, (EtMaterial.material_id == EtItem.material_id) & (EtMaterial.deleted == 0))
            .outerjoin(EtQuiz, (EtQuiz.quiz_id == EtItem.quiz_id) & (EtQuiz.deleted == 0))
            .where(EtItem.chapter_id.in_(chapter_ids), EtItem.deleted == 0)
            .order_by(EtItem.chapter_id, EtItem.sort_order, EtItem.item_id)
        )
        return [(item, material_name, quiz_name) for item, material_name, quiz_name in rows.all()]

    # ── 教材內容 ────────────────────────────────────────────────────────────

    async def get_material(self, db: AsyncSession, material_id: int) -> EtMaterial | None:
        return await db.scalar(select(EtMaterial).where(EtMaterial.material_id == material_id, EtMaterial.deleted == 0))

    async def videos(self, db: AsyncSession, material_id: int) -> list[EtMaterialVideo]:
        rows = await db.scalars(
            select(EtMaterialVideo)
            .where(EtMaterialVideo.material_id == material_id, EtMaterialVideo.deleted == 0)
            .order_by(EtMaterialVideo.sort_order, EtMaterialVideo.video_id)
        )
        return list(rows)

    async def get_video(self, db: AsyncSession, video_id: int) -> EtMaterialVideo | None:
        return await db.scalar(
            select(EtMaterialVideo).where(EtMaterialVideo.video_id == video_id, EtMaterialVideo.deleted == 0)
        )

    async def docs(self, db: AsyncSession, material_id: int) -> list[EtMaterialDoc]:
        rows = await db.scalars(
            select(EtMaterialDoc)
            .where(EtMaterialDoc.material_id == material_id, EtMaterialDoc.deleted == 0)
            .order_by(EtMaterialDoc.sort_order, EtMaterialDoc.mat_doc_id)
        )
        return list(rows)

    async def doc_belongs_to_material(self, db: AsyncSession, *, material_id: int, doc_id: str) -> bool:
        """該 DM 文件是否確實被此教材引用。

        取檔端點的路徑是 `/materials/{material_id}/docs/{doc_id}/file`——授權由
        `material_id` 那側判定，故必須驗證 `doc_id` 真的屬於它。否則在籍任一課程的
        學員即可用自己有權的 `material_id` 搭配任意 `doc_id`，取走全站被引用過的文件。
        """
        found = await db.scalar(
            select(EtMaterialDoc.mat_doc_id).where(
                EtMaterialDoc.material_id == material_id,
                EtMaterialDoc.doc_id == doc_id,
                EtMaterialDoc.deleted == 0,
            )
        )
        return found is not None
