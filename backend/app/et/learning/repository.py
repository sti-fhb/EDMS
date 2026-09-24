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

from collections.abc import Iterable

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.material.models import EtMaterial, EtMaterialDoc, EtMaterialVideo
from app.et.progress.models import EtEnrollment
from app.et.quiz.models import EtQuestion, EtQuiz

#: `items_with_titles` 的一列：項目本體、教材名稱、測驗名稱、是否為 0 題測驗。
LearnItemRow = tuple[EtItem, str | None, str | None, bool]


def zero_question_quiz_item_ids(rows: Iterable[LearnItemRow]) -> frozenset[int]:
    """自 `items_with_titles` 的輸出取出 **0 題測驗**之 `ITEM_ID`（`spec_us5` AC 12）。

    供 `progress/rules.build_item_state` 判定「這一項現在不可能完成，故不當閘門」
    ——理由與代價見該函式的 docstring。

    ⭐ **推導只存在這一支**。側欄（`learning/service`）與後端守門（`progress/service`）
    都必須得到同一個集合；各自寫一次 `if ... is_zero` 看似無害，但那正是
    `build_item_state` 整個防呆設計要避免的東西——兩份規則遲早只改到一份。

    回 `ITEM_ID` 而非 `QUIZ_ID`：解鎖判定以項目為單位。
    """
    return frozenset(item.item_id for item, _, _, is_zero_question_quiz in rows if is_zero_question_quiz)


class EtLearningRepository:
    """學員端之課程結構與教材內容查詢（唯讀）。"""

    # ── 授權所需 ────────────────────────────────────────────────────────────

    async def get_course(self, db: AsyncSession, course_id: int) -> EtCourse | None:
        return await db.scalar(select(EtCourse).where(EtCourse.course_id == course_id, EtCourse.deleted == 0))

    async def was_removed(self, db: AsyncSession, *, user_id: str, course_id: int) -> bool:
        """該學員是否**曾加入但被移除**。

        與 `is_enrolled` 互補：後者問「現在還在不在」，本函式問「不在的原因是被移除
        還是從未加入」。兩者的差別只在訊息，但那個訊息決定學員接下來做什麼——被移除者
        再去找一次邀請碼是白費力氣（依 #247 裁示 C，他也不能自行加回）。
        """
        found = await db.scalar(
            select(EtEnrollment.enrollment_id).where(
                EtEnrollment.user_id == user_id,
                EtEnrollment.course_id == course_id,
                EtEnrollment.is_removed.is_(True),
                EtEnrollment.deleted == 0,
            )
        )
        return found is not None

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

    async def item_id_of_material(self, db: AsyncSession, material_id: int, *, course_id: int) -> int | None:
        """教材 → 其所屬之章節項目（#424 的解鎖判定要用 `ITEM_ID`）。

        與 `course_id_of_material` 走同一條鏈、同樣濾軟刪除——兩者必須對同一批列成立，
        否則會出現「拿得到 course_id 卻拿不到 item_id」而讓解鎖判定被靜默跳過。

        ⚠️ **`course_id` 必填**。今日「1 教材 : 1 項目」，不限定也只會有一列；但本檔
        `course_id_of_material_any` 的 docstring 已預告教材日後可能被多門課程引用，屆時
        不限定範圍就會反查到**別門課**的項目，而解鎖判定拿著它去問「這位學員在*本*課程
        的進度」——算出來的鎖定狀態屬於另一門課。比照 `material_content` 對兩條反查鏈
        的一致性檢核：不去猜哪一個才對。

        影片不另開一支：`ET_MATERIAL_VIDEO` 掛在教材下，呼叫端取 `video.material_id`
        後走本方法即可。
        """
        return await db.scalar(
            select(EtItem.item_id)
            .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
            .where(
                EtItem.material_id == material_id,
                EtChapter.course_id == course_id,
                EtItem.deleted == 0,
                EtChapter.deleted == 0,
            )
            # `ET_ITEM` 的唯一索引是 `(CHAPTER_ID, SORT_ORDER)`——`MATERIAL_ID` 上沒有，
            # 「一材一項」是應用層慣例而非 DB 不變量。同課重複引用時不指定排序的話，
            # 取哪一列由資料庫決定，而兩列的解鎖狀態可能不同 ⇒ 同一個請求時而擋時而放。
            .order_by(EtItem.item_id)
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

    async def items_with_titles(self, db: AsyncSession, chapter_ids: list[int]) -> list[LearnItemRow]:
        """章節下的項目，連同教材名稱、測驗名稱，與「是否為 0 題測驗」。

        兩個 `LEFT OUTER JOIN`——項目**必為兩者之一**（`MATERIAL_ID` / `QUIZ_ID` 互斥），
        用 INNER JOIN 會讓另一型別的項目整批消失，而側欄就會少掉一半內容。

        `is_zero_question_quiz` 隨本查詢一併取回而非另開一支（`spec_us5` AC 12）：
        `progress/service._locked_ids` 在**最高頻的 `report_intervals` 路徑上**，而它
        本來就要呼叫本方法——多一支查詢就是在該路徑上多一次往返。一併取回另有一個好處：
        兩份資料出自同一次查詢，不可能互相矛盾。

        ⚠️ 題數用**相關子查詢**而非 `JOIN ET_QUESTION` + `GROUP BY HAVING`：後者要在
        同一個 `GROUP BY` 裡放進一對多，日後若有人再加一個一對多（如選項）就會是笛卡兒
        積，算出偏大但看起來合理的數字。子查詢沒有這個面。
        """
        if not chapter_ids:
            return []
        question_count = (
            select(func.count())
            .select_from(EtQuestion)
            .where(EtQuestion.quiz_id == EtItem.quiz_id, EtQuestion.deleted == 0)
            .scalar_subquery()
        )
        rows = await db.execute(
            select(
                EtItem,
                EtMaterial.material_name,
                EtQuiz.quiz_name,
                # 🔴 `QUIZ_ID IS NOT NULL` 不可省：教材項目之 `QUIZ_ID` 為 NULL，題數
                # 子查詢對它同樣得 0——少了它會讓**每一個教材項目**都被當成零題測驗而
                # 整批繞過解鎖判定，且 AC 12 看起來仍有啟用（測驗那格擋得住）。
                and_(EtItem.quiz_id.is_not(None), question_count == 0).label("is_zero_question_quiz"),
            )
            .select_from(EtItem)
            .outerjoin(EtMaterial, (EtMaterial.material_id == EtItem.material_id) & (EtMaterial.deleted == 0))
            .outerjoin(EtQuiz, (EtQuiz.quiz_id == EtItem.quiz_id) & (EtQuiz.deleted == 0))
            .where(EtItem.chapter_id.in_(chapter_ids), EtItem.deleted == 0)
            .order_by(EtItem.chapter_id, EtItem.sort_order, EtItem.item_id)
        )
        return [(item, material_name, quiz_name, bool(is_zero)) for item, material_name, quiz_name, is_zero in rows]

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
