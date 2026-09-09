"""ET05 課後問卷填寫 Repository（US13 / #284）——學員端。

## 題目與選項重用教師端的查詢

`EtSurveyRepository.list_questions` / `list_options` 已經處理了軟刪除過濾與排序
（`SORT_ORDER, SQ_ID` / `SQ_ID, SORT_ORDER, SO_ID`），在此重寫一份只會多出一個要
同步維護的地方——教師端日後改了排序規則，學員看到的題序就會跟編輯畫面不一致。

分開的是**授權與寫入**（見 `rules` 模組 docstring），不是同一份資料的讀法。

## 填答不軟刪除

`ET_SURVEY_RESPONSE_M` / `_D` 送出後不可修改 / 刪除（`data-model` §業務規則），故
`UQ_ET_SURVEY_RESPONSE_SURVEY_USER` 是**全表**唯一而非部分唯一索引——這與 #202 /
#203 / #204 那幾次「軟刪除列佔住唯一鍵」的情形不同，不要照那個模式改成
`postgresql_where`。查詢仍一律帶 `DELETED = 0`（BaseModel 的欄位一直都在）。
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.course.models import EtCourse
from app.et.survey.models import EtSurvey, EtSurveyResponseD, EtSurveyResponseM
from app.et.survey_fill.rules import DetailRow


@dataclass(frozen=True)
class SurveyEntryFacts:
    """導出入口狀態所需的三項事實（問卷、課程狀態、自己填過沒有）。

    以單一 dataclass 回傳而非三個獨立查詢的結果：三者必須合看才能導出狀態
    （見 `rules.derive_entry_state`），分開回會讓呼叫端有機會只取其中兩項。
    """

    survey_id: int
    survey_name: str
    survey_active: bool
    course_status: str
    #: 閱課訖止時間（#288）。呼叫端以 `course.rules.is_effectively_closed` 判定「期間
    #: 已過視同關閉」——`course_status` 單獨不足以表達那個狀態。
    open_end_at: datetime | None
    submitted_at: datetime | None


@dataclass(frozen=True)
class MyAnswer:
    """學員自己的一題填答（唯讀回看用）。"""

    sq_id: int
    so_id: int | None
    answer_text: str | None


class EtSurveyFillRepository:
    """學員端問卷填寫：入口事實、自己的填答、送出寫入。"""

    async def entry_facts(self, db: AsyncSession, *, course_id: int, user_id: str) -> SurveyEntryFacts | None:
        """該課程之問卷與該學員的填答狀態；**課程無問卷時回 `None`**。

        一次查詢取齊三項事實——`ET_SURVEY` LEFT JOIN 自己的 `_M` 列，另取課程狀態。
        側欄要在第一次繪製就決定「渲染入口 / 不渲染」，逐項查會讓 `/learn` 多兩趟。

        `LEFT JOIN` 而非兩次查詢：`_M` 沒有列是最常見的情形（未填），為它單獨走一趟
        資料庫不划算。
        """
        row = (
            await db.execute(
                select(
                    EtSurvey.survey_id,
                    EtSurvey.survey_name,
                    EtSurvey.is_active,
                    EtCourse.status,
                    EtCourse.open_end_at,
                    EtSurveyResponseM.submitted_at,
                )
                .select_from(EtSurvey)
                .join(EtCourse, EtCourse.course_id == EtSurvey.course_id)
                .outerjoin(
                    EtSurveyResponseM,
                    (EtSurveyResponseM.survey_id == EtSurvey.survey_id)
                    & (EtSurveyResponseM.user_id == user_id)
                    & (EtSurveyResponseM.deleted == 0),
                )
                .where(EtSurvey.course_id == course_id, EtSurvey.deleted == 0, EtCourse.deleted == 0)
            )
        ).first()
        if row is None:
            return None
        return SurveyEntryFacts(
            survey_id=row[0],
            survey_name=row[1],
            survey_active=row[2],
            course_status=row[3],
            open_end_at=row[4],
            submitted_at=row[5],
        )

    async def my_answers(self, db: AsyncSession, *, survey_id: int, user_id: str) -> list[MyAnswer]:
        """該學員自己的填答明細（AC 9 唯讀回看）。

        以 `SQ_ID` 排序而非 `RD_ID`：寫入時已依題目順序，但排序不該依賴插入順序——
        那是實作細節，日後若改成批次寫入就不成立。
        """
        rows = await db.execute(
            select(EtSurveyResponseD.sq_id, EtSurveyResponseD.so_id, EtSurveyResponseD.answer_text)
            .join(EtSurveyResponseM, EtSurveyResponseM.response_id == EtSurveyResponseD.response_id)
            .where(
                EtSurveyResponseM.survey_id == survey_id,
                EtSurveyResponseM.user_id == user_id,
                EtSurveyResponseM.deleted == 0,
                EtSurveyResponseD.deleted == 0,
            )
            .order_by(EtSurveyResponseD.sq_id)
        )
        return [MyAnswer(sq_id=r[0], so_id=r[1], answer_text=r[2]) for r in rows.all()]

    async def create_response(
        self, db: AsyncSession, *, survey_id: int, rows: list[DetailRow], operator: OperatorInfo
    ) -> tuple[int, datetime]:
        """寫入填答主檔與明細（AC 7）。

        `SUBMITTED_AT` 與標準稽核欄位取**同一個** `now`：兩者相差幾毫秒沒有意義，
        但不同值會讓日後比對「送出時間」與「建立時間」的人以為發生過什麼事。

        Returns:
            `(response_id, submitted_at)`。
        """
        now = utcnow()
        master = EtSurveyResponseM(
            survey_id=survey_id,
            user_id=operator.user_id,
            submitted_at=now,
            created_user=operator.user_id,
            created_date=now,
            deleted=0,
        )
        db.add(master)
        # 明細需要 `RESPONSE_ID`（Identity 由 DB 產生），故必須先 flush 主檔。
        await db.flush()
        for row in rows:
            db.add(
                EtSurveyResponseD(
                    response_id=master.response_id,
                    sq_id=row.sq_id,
                    so_id=row.so_id,
                    answer_text=row.answer_text,
                    created_user=operator.user_id,
                    created_date=now,
                    deleted=0,
                )
            )
        await db.flush()
        return master.response_id, now
