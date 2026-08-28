"""ET 課後問卷 Service（US3 / #204）。

**稽核**：沿用課程之功能碼 `ET-COURSE`（`spec.md` §稽核來源功能碼明列其涵蓋課程下
章節、教材、測驗、**問卷**之編修與刪除），`target_id` 一律填課程 ID，使同一門課的
異動在稽核查詢上串得起來。比照 `EtQuizService`。

**授權**：問卷無自己的擁有者概念——回溯至所屬課程（`ET_SURVEY.COURSE_ID` 直接指向
課程，不必像測驗那樣 join `ET_ITEM`）。

## 凍結（AC 21 / FR-ET-US3-10）

一旦存在任何未刪除之 `ET_SURVEY_RESPONSE_M`，題目與選項即凍結。凍結套用於：
新增題目、更新題目、刪除題目、題目重排。

**不套用於** `update_basic`（問卷名稱與 `IS_ACTIVE`）——AC 21 明訂此時教師「僅可
停用問卷」，把停用也擋掉等於凍結後整張卡片變成死的。

## 刪除問卷（#238 推翻 #204 之裁示 Q1）

**僅草稿課程可刪**（`ensure_survey_deletable`），已發布 / 已關閉僅可停用。
連帶軟刪其題目與選項；填答不處理——草稿課程不可能有填答。

該變更連帶要求 `UQ_ET_SURVEY_COURSE` 改為部分唯一索引（migration `8713c6177f6f`），
否則軟刪的問卷會永久佔住該課程。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.et.common.optimistic_lock import ensure_version_matched
from app.et.course.repository import EtCourseRepository
from app.et.course.rules import ensure_owner
from app.et.survey.repository import EtSurveyRepository
from app.et.survey.rules import (
    ensure_editable,
    ensure_options_match_type,
    ensure_question_reorder_complete,
    ensure_survey_absent,
    ensure_survey_deletable,
    resequence_questions,
)
from app.et.survey.schemas import (
    ApplyTemplateReq,
    SurveyCreateReq,
    SurveyDetail,
    SurveyOptionRow,
    SurveyQuestionCreateReq,
    SurveyQuestionReorderReq,
    SurveyQuestionRow,
    SurveyQuestionUpdateReq,
    SurveyTemplateRow,
    SurveyUpdateReq,
)
from app.et.survey.templates import get_template, list_templates
from app.services import AuditLogService

_MODULE = "ET"
_FUNC_NAME = "ET-COURSE"

_COURSE_NOT_FOUND = AppError(status_code=404, detail="查無此課程", error_code="ET_COURSE_001")
_NOT_FOUND = AppError(status_code=404, detail="查無此問卷", error_code="ET_SURVEY_001")
_QUESTION_NOT_FOUND = AppError(status_code=404, detail="查無此問卷題目", error_code="ET_SURVEY_005")


class EtSurveyService:
    """課後問卷、題目與選項之編修。"""

    def __init__(
        self,
        surveys: EtSurveyRepository | None = None,
        courses: EtCourseRepository | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._surveys = surveys or EtSurveyRepository()
        self._courses = courses or EtCourseRepository()
        self._audit = audit or AuditLogService()

    # ── 問卷本體 ────────────────────────────────────────────────────────────

    async def create(
        self, db: AsyncSession, course_id: int, req: SurveyCreateReq, *, operator: OperatorInfo
    ) -> SurveyDetail:
        """建立課後問卷（一門課程 0～1 份）。"""
        await self._require_owned_course(db, course_id, operator.user_id)
        existing = await self._surveys.get_by_course(db, course_id)
        ensure_survey_absent(exists=existing is not None)
        survey = await self._surveys.create(db, course_id, req.survey_name, operator)
        await self._log(db, "CREATE", operator.user_id, course_id, "建立課後問卷")
        return await self._detail(db, survey)

    async def get_by_course(self, db: AsyncSession, course_id: int, *, actor_id: str) -> SurveyDetail | None:
        """課程之問卷詳細；**尚未建立時回 `None` 而非 404**。

        「這門課沒有問卷」是完全正常的狀態（AC 23 問卷為選配），回 404 會被前端的
        錯誤處理當成故障顯示。

        讀取端不套擁有者判定——他人課程可閱覽（比照 `EtCourseService.get_detail`），
        由課程詳細之 `is_owner` 讓前端呈現唯讀。
        """
        course = await self._courses.get(db, course_id)
        if course is None:
            raise _COURSE_NOT_FOUND
        survey = await self._surveys.get_by_course(db, course_id)
        return None if survey is None else await self._detail(db, survey)

    async def update_basic(
        self, db: AsyncSession, survey_id: int, req: SurveyUpdateReq, *, operator: OperatorInfo
    ) -> None:
        """更新問卷名稱與啟用狀態。

        **刻意不套凍結檢核**——AC 21 明訂已有填答時教師「僅可停用問卷」，停用走的正是
        這條路徑。把它一起擋掉等於凍結後無路可走。
        """
        survey = await self._require_owned(db, survey_id, operator.user_id)
        rowcount = await self._surveys.update_basic(
            db, survey_id, req.version, name=req.survey_name, is_active=req.is_active, operator=operator
        )
        ensure_version_matched(rowcount=rowcount, entity="ET_SURVEY")
        action = "停用課後問卷" if not req.is_active else "更新課後問卷"
        await self._log(db, "UPDATE", operator.user_id, survey.course_id, action)

    async def delete(self, db: AsyncSession, survey_id: int, *, operator: OperatorInfo) -> None:
        """刪除問卷（**僅草稿課程**，#238）：本體與其題目、選項一併軟刪。

        已發布 / 已關閉課程改用停用——`ensure_survey_deletable` 以 `ET_SURVEY_007` 擋下。
        """
        survey = await self._surveys.get(db, survey_id)
        if survey is None:
            raise _NOT_FOUND
        course = await self._require_owned_course(db, survey.course_id, operator.user_id)
        ensure_survey_deletable(course.status)
        await self._surveys.soft_delete_survey(db, survey_id, operator)
        await self._log(db, "DELETE", operator.user_id, survey.course_id, "刪除課後問卷")

    # ── 模板 ────────────────────────────────────────────────────────────────

    def list_templates(self) -> list[SurveyTemplateRow]:
        """內建模板清單（純資料，不需 DB）。"""
        return [SurveyTemplateRow.model_validate(t) for t in list_templates()]

    async def apply_template(
        self, db: AsyncSession, survey_id: int, req: ApplyTemplateReq, *, operator: OperatorInfo
    ) -> SurveyDetail:
        """套用模板：一次建立整組題目與選項。

        **僅於問卷 0 題時可套用**（否則 409 `ET_SURVEY_010`）——避免模板題目與教師已建
        的題目混在一起、順序難以預期。前端亦僅於空問卷時顯示模板區，此處為繞過 UI 的
        把關。

        套用後題目即為該問卷的一般題目，**不與模板保持任何關聯**：之後改模板不影響
        已建立的問卷，改問卷也不回寫模板。
        """
        survey = await self._require_editable(db, survey_id, operator.user_id)
        existing = await self._surveys.list_questions(db, survey_id)
        if existing:
            raise AppError(status_code=409, detail="問卷已有題目，無法套用模板", error_code="ET_SURVEY_010")
        template = get_template(req.template_code)
        rowcount = await self._surveys.bump_version(db, survey_id, req.version, operator)
        ensure_version_matched(rowcount=rowcount, entity="ET_SURVEY")
        await self._surveys.add_questions_bulk(
            db,
            survey_id,
            [(q.question_type, q.stem, list(q.options)) for q in template.questions],
            operator,
        )
        await self._log(db, "CREATE", operator.user_id, survey.course_id, f"套用問卷模板（{template.code}）")
        refreshed = await self._surveys.get(db, survey_id)
        return await self._detail(db, refreshed)

    # ── 題目與選項 ──────────────────────────────────────────────────────────

    async def add_question(
        self, db: AsyncSession, survey_id: int, req: SurveyQuestionCreateReq, *, operator: OperatorInfo
    ) -> SurveyQuestionRow:
        """新增題目（含其全部選項），追加至最末。"""
        survey = await self._require_editable(db, survey_id, operator.user_id)
        ensure_options_match_type(req.question_type, option_count=len(req.options))
        question = await self._surveys.add_question(
            db,
            survey_id,
            question_type=req.question_type,
            stem=req.stem,
            options=[o.option_text for o in req.options],
            operator=operator,
        )
        await self._log(db, "CREATE", operator.user_id, survey.course_id, "新增問卷題目")
        return await self._question_row(db, question)

    async def update_question(
        self, db: AsyncSession, sq_id: int, req: SurveyQuestionUpdateReq, *, operator: OperatorInfo
    ) -> None:
        """更新題目與其選項（選項全量覆寫；帶題目自身之 `version`）。"""
        question = await self._surveys.get_question(db, sq_id)
        if question is None:
            raise _QUESTION_NOT_FOUND
        survey = await self._require_editable(db, question.survey_id, operator.user_id)
        ensure_options_match_type(req.question_type, option_count=len(req.options))
        rowcount = await self._surveys.replace_question(
            db,
            sq_id,
            req.version,
            question_type=req.question_type,
            stem=req.stem,
            options=[o.option_text for o in req.options],
            operator=operator,
        )
        ensure_version_matched(rowcount=rowcount, entity="ET_SURVEY_QUESTION")
        await self._log(db, "UPDATE", operator.user_id, survey.course_id, "更新問卷題目")

    async def delete_question(self, db: AsyncSession, sq_id: int, *, operator: OperatorInfo) -> None:
        """刪除題目：本體與其選項軟刪，剩餘題目順序遞補。

        填答明細不需處理——凍結檢核保證刪題只可能發生在尚無填答時。
        """
        question = await self._surveys.get_question(db, sq_id)
        if question is None:
            raise _QUESTION_NOT_FOUND
        survey = await self._require_editable(db, question.survey_id, operator.user_id)
        await self._surveys.soft_delete_question(db, sq_id, operator)
        await self._surveys.resequence_questions(db, question.survey_id, operator)
        await self._log(db, "DELETE", operator.user_id, survey.course_id, "刪除問卷題目")

    async def reorder_questions(
        self, db: AsyncSession, survey_id: int, req: SurveyQuestionReorderReq, *, operator: OperatorInfo
    ) -> None:
        """重排題目順序（送完整陣列；帶**問卷層** `version`）。

        以問卷層版本保護而非題目層——順序屬問卷結構，遞增各題版本會讓正在編輯某題的
        另一裝置無故衝突（FR-ET-US3-15）。比照章節 / 項目 / 測驗題目之重排。
        """
        survey = await self._require_editable(db, survey_id, operator.user_id)
        current = await self._surveys.list_questions(db, survey_id)
        ensure_question_reorder_complete(current_ids={q.sq_id for q in current}, requested=req.question_ids)
        rowcount = await self._surveys.bump_version(db, survey_id, req.version, operator)
        ensure_version_matched(rowcount=rowcount, entity="ET_SURVEY")
        await self._surveys.apply_question_order(db, resequence_questions(req.question_ids), operator)
        await self._log(db, "UPDATE", operator.user_id, survey.course_id, "調整問卷題目順序")

    # ── 內部 ────────────────────────────────────────────────────────────────

    async def _require_owned_course(self, db: AsyncSession, course_id: int, actor_id: str):
        course = await self._courses.get(db, course_id)
        if course is None:
            raise _COURSE_NOT_FOUND
        ensure_owner(owner_id=course.owner_id, actor_id=actor_id)
        return course

    async def _require_owned(self, db: AsyncSession, survey_id: int, actor_id: str):
        survey = await self._surveys.get(db, survey_id)
        if survey is None:
            raise _NOT_FOUND
        await self._require_owned_course(db, survey.course_id, actor_id)
        return survey

    async def _require_editable(self, db: AsyncSession, survey_id: int, actor_id: str):
        """擁有者 + 尚未凍結——題目與選項之所有寫入路徑共用。"""
        survey = await self._require_owned(db, survey_id, actor_id)
        ensure_editable(has_responses=await self._surveys.has_responses(db, survey_id))
        return survey

    async def _detail(self, db: AsyncSession, survey) -> SurveyDetail:
        questions = await self._surveys.list_questions(db, survey.survey_id)
        options = await self._surveys.list_options(db, [q.sq_id for q in questions])
        by_question: dict[int, list[SurveyOptionRow]] = {}
        for option in options:
            by_question.setdefault(option.sq_id, []).append(SurveyOptionRow.model_validate(option))

        responded = await self._surveys.count_responses(db, survey.survey_id)
        enrolled = await self._surveys.count_enrollments(db, survey.course_id)
        return SurveyDetail(
            survey_id=survey.survey_id,
            course_id=survey.course_id,
            survey_name=survey.survey_name,
            is_active=survey.is_active,
            version=survey.version,
            # 由 `responded` 推導而非另查一次——同一個交易內兩者必然一致，
            # 而分開查會讓「凍結」與「已填人數」在極端時序下互相矛盾。
            frozen=responded > 0,
            responded_count=responded,
            # 下限 0：學員退選等情形可能讓已填數超過當前在籍數，負數對教師沒有意義。
            pending_count=max(enrolled - responded, 0),
            questions=[
                SurveyQuestionRow(
                    sq_id=q.sq_id,
                    question_type=q.question_type,
                    stem=q.stem,
                    sort_order=q.sort_order,
                    version=q.version,
                    options=by_question.get(q.sq_id, []),
                )
                for q in questions
            ],
        )

    async def _question_row(self, db: AsyncSession, question) -> SurveyQuestionRow:
        options = await self._surveys.list_options(db, [question.sq_id])
        return SurveyQuestionRow(
            sq_id=question.sq_id,
            question_type=question.question_type,
            stem=question.stem,
            sort_order=question.sort_order,
            version=question.version,
            options=[SurveyOptionRow.model_validate(o) for o in options],
        )

    async def _log(self, db: AsyncSession, action: str, operator_id: str, course_id: int, description: str) -> None:
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type=action,
            result="SUCCESS",
            operator_id=operator_id,
            target_id=str(course_id),
            description=description,
        )
