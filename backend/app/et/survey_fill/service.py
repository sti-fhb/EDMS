"""ET05 課後問卷填寫 Service（US13 / #284）——學員端。

## 授權問「在籍」，不是「擁有權」

`survey/service.py` 的每個動作都回溯課程確認**擁有者**；本模組確認**成員資格**。
兩者相反，這是分成兩個子模組的主要理由（見 `rules` 模組 docstring）。

擁有者（教師預覽）在此**不特別放行**：他沒有進度可累積，導不出完課，入口自然不出現。
教師若真的用邀請碼加入自己的課，他就是學員，一切照學員規則走——與
`learning/service` 對 `is_preview` 的處理同一個立場。

## 本模組不寫 `DP_AUDIT_LOG`（與「CUD 皆須稽核」規範的明示例外）

`spec.md` §稽核來源功能碼明訂「**僅**上表所列之權限、破例與關鍵狀態變更寫入」，
而該表涵蓋的是 US1 / US3 / US8 / US9 / US11 / US16——**US13 不在列**。學員送出自己的
問卷回饋是一般資料異動，具名由 `ET_SURVEY_RESPONSE_M.USER_ID` + `SUBMITTED_AT` 與標準
稽核欄位承載（`data-model` 明訂本表填答**具名**、送出後不可修改 / 刪除，本身即是完整
的紀錄）。

要為它寫稽核就得新增一個 `FUNC_NAME` 語意碼，那是 spec 層的變更，不是實作可自決的。
比照 `progress/router.py` 已登記的同類例外。
"""

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.constants import COURSE_CLOSED, SURVEY_QUESTION_SINGLE
from app.et.course.rules import is_effectively_closed
from app.et.enrollment.rules import is_course_completed
from app.et.learning.repository import EtLearningRepository
from app.et.progress.repository import EtProgressRepository
from app.et.survey.models import EtSurveyOption, EtSurveyQuestion
from app.et.survey.repository import EtSurveyRepository
from app.et.survey_fill.repository import EtSurveyFillRepository, SurveyEntryFacts
from app.et.survey_fill.rules import (
    AnswerDraft,
    QuestionSpec,
    build_detail_rows,
    derive_entry_state,
    ensure_fillable,
    validate_answers,
)
from app.et.survey_fill.schemas import (
    SurveyAnswerRow,
    SurveyEntry,
    SurveyForm,
    SurveyOptionRow,
    SurveyQuestionRow,
    SurveySubmitReq,
    SurveySubmitResult,
)

logger = logging.getLogger(__name__)


def _not_enrolled() -> AppError:
    """非在籍。

    ⚠️ **工廠函式而非模組層級常數**，這是刻意與 `app/et/` 其餘 20+ 處慣例不同的。

    `AppError` 繼承 `HTTPException`，是可變物件；CPython 在 raise 一個「已帶
    `__traceback__` 的既有實例」時會把本次傳播的每個 frame **附加**到既有 traceback
    之後，而模組層級的實例永遠被 module globals 持有 → traceback 只增不減，每筆都釘住
    一個 frame 及其 locals（含請求 body 與 `Authorization` header）。實測 100 次 raise
    即累積 400 筆。

    本檔兩個 403 / 404 是**未認證成本最低的路徑**（任一登入者對任意 `course_id` 迴圈
    呼叫即可觸發，不需在籍、不需該課程存在），故不沿用那個慣例。

    > 全 codebase 的 singleton 清理屬平台層，另開 issue 追蹤；此處只是不再新增。
    """
    return AppError(status_code=403, detail="您尚未加入此課程", error_code="ET_SURVEY_011")


def _no_survey() -> AppError:
    """課程沒有問卷（或問卷已刪除）時，以 id 定址的填寫端點之回應。

    與 `ET_SURVEY_001`（教師端「查無此問卷」）共用同一碼與訊息：學員這一側的定址是
    課程而非問卷，而「這門課沒有問卷」與「問卷不存在」對他是同一件事。

    工廠函式的理由同 `_not_enrolled`。
    """
    return AppError(status_code=404, detail="查無此問卷", error_code="ET_SURVEY_001")


def _already_submitted() -> AppError:
    return AppError(status_code=409, detail="您已填寫過此問卷", error_code="ET_SURVEY_013")


class EtSurveyFillService:
    """學員端問卷填寫：取表單、送出。"""

    def __init__(
        self,
        fill: EtSurveyFillRepository | None = None,
        surveys: EtSurveyRepository | None = None,
        learning: EtLearningRepository | None = None,
        progress: EtProgressRepository | None = None,
    ) -> None:
        self._fill = fill or EtSurveyFillRepository()
        self._surveys = surveys or EtSurveyRepository()
        self._learning = learning or EtLearningRepository()
        self._progress = progress or EtProgressRepository()

    async def entry(self, db: AsyncSession, *, course_id: int, user_id: str, completed: bool) -> SurveyEntry | None:
        """側欄入口狀態（AC 1 / AC 2）；課程無問卷時回 `None`。

        🔴 **呼叫端必須先完成在籍 / 擁有者判定——本函式不做任何授權檢核。**
        這與 `get_form` / `submit`（兩者都走 `_require_facts`）不對稱，是刻意的：它服務
        的是 `/learn` 的聚合回應，而那支端點在呼叫此處**之前**已經跑過
        `ensure_can_access`（`learning/service.structure`）。

        重複判定會讓 `/learn` 多一次在籍查詢，但**漏掉判定就是一個安靜的資訊洩漏點**
        （本函式會回 `survey_id` / `survey_name` / 自己的 `submitted_at`）。新增第二個
        呼叫端時請先確認該路徑已判過。

        `completed` 由呼叫端傳入而非在此計算——`learning/service.structure()` 手上
        已經有項目清單與完成集合，再查一次進度只是白跑一趟。
        """
        facts = await self._fill.entry_facts(db, course_id=course_id, user_id=user_id)
        if facts is None:
            return None
        return SurveyEntry(
            survey_id=facts.survey_id,
            survey_name=facts.survey_name,
            state=_state_of(facts, completed=completed),
            submitted_at=facts.submitted_at,
        )

    async def get_form(self, db: AsyncSession, *, course_id: int, user_id: str) -> SurveyForm:
        """問卷填寫頁所需之題目與自己的作答（AC 3 / AC 9 / AC 10）。

        **`HIDDEN` 亦回 200**：這是讀取端點，而 `HIDDEN` 只表示側欄不顯示入口。回錯誤
        會讓「完課回退後想回看自己填答」這條路徑（FR-08）斷掉——那時 `state` 是
        `SUBMITTED`，但若把 `HIDDEN` 當錯誤處理，前端很容易連帶把整頁做成錯誤畫面。
        前端依 `state` 決定能不能改與有沒有送出鈕。

        Raises:
            AppError: 403 `ET_SURVEY_011` 非在籍；404 `ET_SURVEY_001` 課程無問卷。
        """
        facts = await self._require_facts(db, course_id=course_id, user_id=user_id)
        questions = await self._questions(db, facts.survey_id)
        answers = (
            await self._fill.my_answers(db, survey_id=facts.survey_id, user_id=user_id)
            if facts.submitted_at is not None
            else []
        )
        return SurveyForm(
            survey_id=facts.survey_id,
            survey_name=facts.survey_name,
            state=_state_of(facts, completed=await self._completed(db, course_id=course_id, user_id=user_id)),
            submitted_at=facts.submitted_at,
            questions=questions,
            my_answers=[SurveyAnswerRow(sq_id=a.sq_id, so_id=a.so_id, answer_text=a.answer_text) for a in answers],
        )

    async def submit(
        self, db: AsyncSession, *, course_id: int, req: SurveySubmitReq, operator: OperatorInfo
    ) -> SurveySubmitResult:
        """送出填答（AC 7 / AC 8）。

        ## 併發送出以 SAVEPOINT + 唯一約束收尾

        `ensure_fillable` 讀到的「未填」與 INSERT 之間沒有鎖。學員開兩個分頁各按一次
        送出（或手快點兩下）時，兩個請求都會通過檢查，第二個撞
        `UQ_ET_SURVEY_RESPONSE_SURVEY_USER`。不接的話那是未處理例外 → 500，**而且會
        連帶回滾**——但第一次其實已經成功了，學員看到失敗卻其實填成功了，這是最糟的
        組合。包 `begin_nested()` 讓衝突只回退這次 INSERT，改回 409 `ET_SURVEY_013`。

        前端收到 `ET_SURVEY_013` 不顯示紅色錯誤——他的問卷確實已經送出，正確的呈現是
        重載表單轉唯讀。比照 `enrollment/service.join` 對重複加入的處理。

        Raises:
            AppError: 403 `ET_SURVEY_011` 非在籍；404 `ET_SURVEY_001` 課程無問卷；
                403 `ET_SURVEY_012` 尚未完課；409 `ET_SURVEY_013` 已填寫過；
                409 `ET_SURVEY_014` 課程已關閉；422 `ET_SURVEY_015` ~ `017` 作答不合規。
        """
        facts = await self._require_facts(db, course_id=course_id, user_id=operator.user_id)
        completed = await self._completed(db, course_id=course_id, user_id=operator.user_id)
        ensure_fillable(_state_of(facts, completed=completed))

        specs = await self._question_specs(db, facts.survey_id)
        answers = [AnswerDraft(sq_id=a.sq_id, so_id=a.so_id, answer_text=a.answer_text) for a in req.answers]
        try:
            validate_answers(questions=specs, answers=answers)
        except AppError as exc:
            # 畸形作答（`ET_SURVEY_017`）是自家 UI 產不出來的請求，本身即是高可信度的
            # 濫用訊號。**不記 `answer_text` 內容**（`sti-backend-logging`：個資完整值
            # 不進 log），只記代碼與筆數。
            logger.warning(
                "課後問卷作答不合規 user=%s course_id=%s error_code=%s answers=%s",
                operator.user_id,
                course_id,
                exc.error_code,
                len(answers),
            )
            raise
        rows = build_detail_rows(questions=specs, answers=answers)

        try:
            async with db.begin_nested():
                response_id, submitted_at = await self._fill.create_response(
                    db, survey_id=facts.survey_id, rows=rows, operator=operator
                )
        except IntegrityError:
            # **自我驗證後才轉 409**，不無條件把任何 `IntegrityError` 都說成「已填寫過」。
            #
            # `create_response` 內有兩次 flush（主檔、明細），明細那側還有 `SQ_ID` /
            # `SO_ID` 兩個 FK。若日後某個約束被違反而一律回 `ET_SURVEY_013`，學員會看到
            # 「您已填寫過此問卷」——而前端把那個代碼當成功處理（他的問卷確實常常是已
            # 送出的），於是「什麼都沒寫進去」會被呈現為送出成功，且沒有任何痕跡。
            #
            # 以「我的填答列是否真的存在」判定，而非解析 driver 的 constraint 名稱：後者
            # 綁 asyncpg 的例外屬性，換 driver 就靜默失效。比照
            # `enrollment/service.join` 併發路徑「重查是否有 winner」的作法。
            after = await self._fill.entry_facts(db, course_id=course_id, user_id=operator.user_id)
            if after is None or after.submitted_at is None:
                logger.exception(
                    "課後問卷送出遇到非重複送出之完整性錯誤 user=%s course_id=%s", operator.user_id, course_id
                )
                raise
            raise _already_submitted() from None
        return SurveySubmitResult(response_id=response_id, submitted_at=submitted_at)

    # ── 內部 ────────────────────────────────────────────────────────────────

    async def _require_facts(self, db: AsyncSession, *, course_id: int, user_id: str) -> SurveyEntryFacts:
        """在籍檢核 + 取問卷事實。

        在籍**先於**問卷存在性判定：反過來的話，任一登入者（ET 學員角色人人都有）可
        用它問出「哪些課程建了問卷」——那是課程結構的資訊，不該對非成員開放。
        """
        if not await self._learning.is_enrolled(db, user_id=user_id, course_id=course_id):
            # 對非成員一律回同一個 403（課程不存在 / 草稿 / 無問卷 / 有問卷但你不在籍
            # 四種情形不可區分），故枚舉者從回應學不到東西——但**嘗試本身要留痕**，
            # 否則「同一帳號對數百個 course_id 連續取得 403」在預設 log level 下毫無
            # 證據（`app_error_handler` 只有 `logger.debug`）。
            #
            # 不寫 `DP_AUDIT_LOG`：見本模組 docstring 之稽核範圍說明。這裡要的是應用層
            # 的監測面，不是資安稽核鏈。
            logger.warning("非在籍者嘗試存取課後問卷 user=%s course_id=%s", user_id, course_id)
            raise _not_enrolled()
        facts = await self._fill.entry_facts(db, course_id=course_id, user_id=user_id)
        if facts is None:
            raise _no_survey()
        return facts

    async def _completed(self, db: AsyncSession, *, course_id: int, user_id: str) -> bool:
        counts = await self._progress.completion_counts_by_course(db, user_id=user_id, course_ids=[course_id])
        done, total = counts.get(course_id, (0, 0))
        return is_course_completed(done=done, total=total)

    async def _questions(self, db: AsyncSession, survey_id: int) -> list[SurveyQuestionRow]:
        questions, options = await self._load(db, survey_id)
        by_question: dict[int, list[SurveyOptionRow]] = {}
        for option in options:
            by_question.setdefault(option.sq_id, []).append(
                SurveyOptionRow(so_id=option.so_id, option_text=option.option_text)
            )
        return [
            SurveyQuestionRow(
                sq_id=q.sq_id,
                question_type=q.question_type,
                stem=q.stem,
                options=by_question.get(q.sq_id, []),
            )
            for q in questions
        ]

    async def _question_specs(self, db: AsyncSession, survey_id: int) -> list[QuestionSpec]:
        """驗證用的題目規格——每題帶**自己的**合法選項集合。

        必須逐題比對，否則學員可送出別題的選項 id，讓 US9 的統計出現不屬於該題的選項
        （而那份統計沒有任何地方會察覺）。

        ⚠️ **這道檢查不是原子的**：讀取與 INSERT 之間沒有鎖。題目凍結
        （`ET_SURVEY_003`）在**第一筆填答出現前不生效**，所以第一位學員送出的那一瞬間，
        若教師正好更新題目（舊選項軟刪 + 新選項自 1 起插入），學員送的 `SO_ID` 仍能通過
        FK（軟刪的列實體還在）而被寫入。窗口極窄且需要教師同時操作，評估為可接受；
        真要處理，最小成本是在 `begin_nested()` 內重讀一次 `option_ids` 再比對。
        """
        questions, options = await self._load(db, survey_id)
        by_question: dict[int, set[int]] = {}
        for option in options:
            by_question.setdefault(option.sq_id, set()).add(option.so_id)
        return [
            QuestionSpec(
                sq_id=q.sq_id,
                question_type=q.question_type,
                option_ids=frozenset(by_question.get(q.sq_id, set())),
            )
            for q in questions
        ]

    async def _load(self, db: AsyncSession, survey_id: int) -> tuple[list[EtSurveyQuestion], list[EtSurveyOption]]:
        """題目與選項——重用教師端的查詢（已處理軟刪除過濾與排序）。

        單選題**無選項**時仍照原樣回傳空清單、不在此擋下：那是資料異常
        （`ET_SURVEY_004` 於建立時已把關至少 2 個），而擋在讀取端會讓學員連題目都看
        不到，卻無法自己處理。送出時 `validate_answers` 會因「選不到合法選項」擋下，
        錯誤落在教師該修的地方。
        """
        questions = await self._surveys.list_questions(db, survey_id)
        single_ids = [q.sq_id for q in questions if q.question_type == SURVEY_QUESTION_SINGLE]
        options = await self._surveys.list_options(db, single_ids)
        return questions, options


def _state_of(facts: SurveyEntryFacts, *, completed: bool) -> str:
    """`SurveyEntryFacts` + 完課旗標 → 入口狀態。

    只是把 dataclass 攤成四個具名參數；判定順序全在 `rules.derive_entry_state`——
    「已填優先於課程狀態」那條規則**只有一份實作**，在此重寫一次遲早會分歧。
    """
    # #288：閱課期間已過亦視同關閉——映射成 `COURSE_CLOSED` 後交給 `derive_entry_state`，
    # 那支已正確處理已關閉（未填者見提示、已填者仍可回看，AC 10 / 11）。在此映射而非改動
    # `derive_entry_state` 的簽章，是因為「期間已過」與「已關閉」對問卷入口的後果完全相同
    # ——多一個參數只會讓那支純函式多一種要測的組合，卻不會產生任何不同的結果。
    course_status = (
        COURSE_CLOSED
        if is_effectively_closed(status=facts.course_status, open_end_at=facts.open_end_at, now=utcnow())
        else facts.course_status
    )
    return derive_entry_state(
        survey_active=facts.survey_active,
        completed=completed,
        already_submitted=facts.submitted_at is not None,
        course_status=course_status,
    )
