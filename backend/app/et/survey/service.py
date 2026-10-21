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
from app.core.request_context import get_client_ip
from app.et.audit_target import course_audit_payload
from app.et.common.optimistic_lock import ensure_version_matched
from app.et.course.repository import EtCourseRepository
from app.et.course.rules import ensure_owner
from app.et.course.stage_rules import ENTITY_SURVEY, ENTITY_SURVEY_OPTION, ENTITY_SURVEY_QUESTION
from app.et.course.stage_writer import EtCourseStageWriter, exposed_id, is_staged
from app.et.survey.repository import EtSurveyRepository
from app.et.survey.rules import (
    basic_update_action,
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
        stage_writer: EtCourseStageWriter | None = None,
    ) -> None:
        self._surveys = surveys or EtSurveyRepository()
        self._courses = courses or EtCourseRepository()
        self._audit = audit or AuditLogService()
        self._stage_writer = stage_writer or EtCourseStageWriter()

    # ── 問卷本體 ────────────────────────────────────────────────────────────

    async def create(
        self, db: AsyncSession, course_id: int, req: SurveyCreateReq, *, operator: OperatorInfo
    ) -> SurveyDetail:
        """建立課後問卷（一門課程 0～1 份）。"""
        course = await self._require_owned_course(db, course_id, operator.user_id)
        if is_staged(course):
            await self._stage_writer.lock_course(db, course_id)
            await self._stage_writer.ensure_seeded(db, course_id, operator)
            # ⚠️ 「已經有問卷了嗎」要問**暫存樹**，不是活表：本次編輯剛建的那份不在活表，
            # 問活表會讓教師連按兩次建出兩份，而一門課只能有 0～1 份。
            existing = await self._stage_writer.children_of(db, course_id, ENTITY_SURVEY, None)
            ensure_survey_absent(exists=bool(existing))
            await self._stage_writer.append(
                db,
                course_id,
                ENTITY_SURVEY,
                parent_stage_id=None,
                payload={"survey_name": req.survey_name, "is_active": True},
                operator=operator,
            )
            await self._log(db, "CREATE", operator.user_id, course_id, "建立課後問卷（暫存）")
            staged = await self._staged_detail(db, course_id, operator.user_id)
            if staged is None:  # pragma: no cover - 剛寫進去必定讀得回來
                raise _NOT_FOUND
            return staged

        existing_live = await self._surveys.get_by_course(db, course_id)
        ensure_survey_absent(exists=existing_live is not None)
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
        # 擁有者 + 已開始編輯 ⇒ 讀暫存版（#631）。少了這段，教師看到的是學員那一版，
        # 存檔時整份取代，他上一次的暫存編輯被自己的畫面蓋回去。
        staged = await self._staged_detail(db, course_id, actor_id)
        if staged is not None:
            return staged
        survey = await self._surveys.get_by_course(db, course_id)
        return None if survey is None else await self._detail(db, survey)

    async def update_basic(
        self, db: AsyncSession, survey_id: int, req: SurveyUpdateReq, *, operator: OperatorInfo
    ) -> None:
        """更新問卷名稱與啟用狀態。

        **刻意不套凍結檢核**——AC 21 明訂已有填答時教師「僅可停用問卷」，停用走的正是
        這條路徑。把它一起擋掉等於凍結後無路可走。
        """
        # `editable=False`：名稱與停用**不受凍結限制**（AC 21，見本方法 docstring）
        ref, course_id = await self._staged_survey(db, survey_id, operator.user_id, operator, editable=False)
        # 稽核要分得出停用 / 重新啟用 / 改名，得先知道更新前的狀態（#768 第 13 項）。
        # 暫存模式讀暫存節點（那才是教師畫面上的那一份），否則讀活表。
        if ref is not None:
            node = await self._stage_writer.node_by_stage_id(db, ref.stage_id, ENTITY_SURVEY)
            before_active = bool(node.payload.get("is_active", True)) if node is not None else True
        else:
            live = await self._surveys.get(db, survey_id)
            before_active = live.is_active if live is not None else True
        action = basic_update_action(before_active=before_active, after_active=req.is_active)
        if ref is not None:
            rowcount = await self._stage_writer.update_payload(
                db,
                ref.stage_id,
                version=req.version,
                payload={"survey_name": req.survey_name, "is_active": req.is_active},
                operator=operator,
            )
            ensure_version_matched(rowcount=rowcount, entity="ET_SURVEY")
            await self._log(db, "UPDATE", operator.user_id, course_id, f"{action}（暫存）")
            return

        rowcount = await self._surveys.update_basic(
            db, survey_id, req.version, name=req.survey_name, is_active=req.is_active, operator=operator
        )
        ensure_version_matched(rowcount=rowcount, entity="ET_SURVEY")
        await self._log(db, "UPDATE", operator.user_id, course_id, action)

    async def delete(self, db: AsyncSession, survey_id: int, *, operator: OperatorInfo) -> None:
        """刪除問卷（**僅草稿課程**，#238）：本體與其題目、選項一併軟刪。

        已發布 / 已關閉課程改用停用——`ensure_survey_deletable` 以 `ET_SURVEY_007` 擋下。

        🔴 **負數 id 也走 `ET_SURVEY_007`，不是 404**（2026-10-18 security review L-6）。
        負數只可能是「本次編輯在一門已發布 / 已關閉課程上新建的問卷」——那門課依定義
        不可刪問卷，所以結論與正數路徑**完全相同**，只是查活表查不到而已。

        ⚠️ 不補這一句的話，教師對著畫面上明明存在的問卷按刪除會看到「找不到問卷」，
        而真正的理由是「這門課只能停用」。錯的不是行為、是**他據以下一步的資訊**。
        """
        if survey_id < 0:
            ref = await self._stage_writer.resolve_new(db, survey_id, ENTITY_SURVEY)
            if ref is None:
                raise _NOT_FOUND
            course = await self._require_owned_course(db, ref.course_id, operator.user_id)
            # ⚠️ 用**真的**課程狀態問規則，不要寫死一個狀態丟進去——規則與理由只有一份。
            # 課程是草稿時這一行會放行，但那在結構上不可能發生（草稿直寫活表、不產生負數
            # id），所以之後的 `_NOT_FOUND` 才是對的：真的查無此問卷。
            ensure_survey_deletable(course.status)
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
        ref, course_id = await self._staged_survey(db, survey_id, operator.user_id, operator, editable=True)
        if ref is not None:
            # 「已有題目嗎」同樣要問**暫存樹**：問活表的話，教師這次剛加的題目不算數，
            # 模板會疊上去，而那正是 `ET_SURVEY_010` 要避免的「混在一起、順序難預期」。
            if await self._stage_writer.children_of(db, course_id, ENTITY_SURVEY_QUESTION, ref.stage_id):
                raise AppError(status_code=409, detail="問卷已有題目，無法套用模板", error_code="ET_SURVEY_010")
            template = get_template(req.template_code)
            rowcount = await self._stage_writer.bump_version(db, ref.stage_id, req.version, operator)
            ensure_version_matched(rowcount=rowcount, entity="ET_SURVEY")
            for question in template.questions:
                sq_stage = await self._stage_writer.append(
                    db,
                    course_id,
                    ENTITY_SURVEY_QUESTION,
                    parent_stage_id=ref.stage_id,
                    payload={"question_type": question.question_type, "stem": question.stem},
                    operator=operator,
                )
                for text in question.options:
                    await self._stage_writer.append(
                        db,
                        course_id,
                        ENTITY_SURVEY_OPTION,
                        parent_stage_id=sq_stage,
                        payload={"option_text": text},
                        operator=operator,
                    )
            await self._log(db, "CREATE", operator.user_id, course_id, f"套用問卷模板（{template.code}，暫存）")
            staged = await self._staged_detail(db, course_id, operator.user_id)
            if staged is None:  # pragma: no cover - 剛寫進去必定讀得回來
                raise _NOT_FOUND
            return staged

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
        # `bump_version` 走的是 Core update，session 裡的 `survey` 還握著舊版號。
        # 用 refresh 而非重新 `get()`——後者回 `EtSurvey | None`，會多一個永遠不會
        # 成立卻得處理的分支（#204 的 `update_question` 就踩過同型）。
        await db.refresh(survey)
        return await self._detail(db, survey)

    # ── 題目與選項 ──────────────────────────────────────────────────────────

    async def add_question(
        self, db: AsyncSession, survey_id: int, req: SurveyQuestionCreateReq, *, operator: OperatorInfo
    ) -> SurveyQuestionRow:
        """新增題目（含其全部選項），追加至最末。"""
        ref, course_id = await self._staged_survey(db, survey_id, operator.user_id, operator, editable=True)
        ensure_options_match_type(req.question_type, option_count=len(req.options))
        if ref is not None:
            sq_stage = await self._stage_writer.append(
                db,
                ref.course_id,
                ENTITY_SURVEY_QUESTION,
                parent_stage_id=ref.stage_id,
                payload={"question_type": req.question_type, "stem": req.stem},
                operator=operator,
            )
            for option in req.options:
                await self._stage_writer.append(
                    db,
                    ref.course_id,
                    ENTITY_SURVEY_OPTION,
                    parent_stage_id=sq_stage,
                    payload={"option_text": option.option_text},
                    operator=operator,
                )
            await self._log(db, "CREATE", operator.user_id, course_id, "新增問卷題目（暫存）")
            node = await self._stage_writer.node_by_stage_id(db, sq_stage, ENTITY_SURVEY_QUESTION)
            if node is None:  # pragma: no cover - 剛寫進去必定讀得回來
                raise _QUESTION_NOT_FOUND
            return await self._staged_question_row(db, ref.course_id, node)

        survey = await self._require_editable(db, survey_id, operator.user_id)
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
        ref, course_id, _live_survey_id = await self._staged_sq(db, sq_id, operator.user_id, operator)
        ensure_options_match_type(req.question_type, option_count=len(req.options))
        if ref is not None:
            rowcount = await self._stage_writer.update_payload(
                db,
                ref.stage_id,
                version=req.version,
                payload={"question_type": req.question_type, "stem": req.stem},
                operator=operator,
            )
            ensure_version_matched(rowcount=rowcount, entity="ET_SURVEY_QUESTION")
            # 選項**全量覆寫**（同測驗題目的理由：選項沒有穩定的業務鍵，比對差異必然配錯）
            for old in await self._stage_writer.children_of(db, course_id, ENTITY_SURVEY_OPTION, ref.stage_id):
                await self._stage_writer.delete_subtree(db, old.stage_id, operator)
            for option in req.options:
                await self._stage_writer.append(
                    db,
                    course_id,
                    ENTITY_SURVEY_OPTION,
                    parent_stage_id=ref.stage_id,
                    payload={"option_text": option.option_text},
                    operator=operator,
                )
            await self._log(db, "UPDATE", operator.user_id, course_id, "更新問卷題目（暫存）")
            return

        question = await self._surveys.get_question(db, sq_id)
        if question is None:
            raise _QUESTION_NOT_FOUND
        survey = await self._require_editable(db, question.survey_id, operator.user_id)
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
        ref, course_id, _live_survey_id = await self._staged_sq(db, sq_id, operator.user_id, operator)
        if ref is not None:
            # ⛔ 不在此 resequence：暫存列的 `SORT_ORDER` 由 `apply_order` 或套用時的
            # `_park_sort_orders` 處理，刪完留洞沒關係（暫存表沒有順序唯一索引）。
            await self._stage_writer.delete_subtree(db, ref.stage_id, operator)
            await self._log(db, "DELETE", operator.user_id, course_id, "刪除問卷題目（暫存）")
            return

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
        ref, course_id = await self._staged_survey(db, survey_id, operator.user_id, operator, editable=True)
        if ref is not None:
            nodes = await self._stage_writer.children_of(db, course_id, ENTITY_SURVEY_QUESTION, ref.stage_id)
            by_exposed = {exposed_id(source_id=n.source_id, stage_id=n.stage_id): n.stage_id for n in nodes}
            ensure_question_reorder_complete(current_ids=set(by_exposed), requested=req.question_ids)
            rowcount = await self._stage_writer.bump_version(db, ref.stage_id, req.version, operator)
            ensure_version_matched(rowcount=rowcount, entity="ET_SURVEY")
            await self._stage_writer.apply_order(db, [by_exposed[i] for i in req.question_ids], operator)
            await self._log(db, "UPDATE", operator.user_id, course_id, "調整問卷題目順序（暫存）")
            return

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

    async def _staged_survey(self, db: AsyncSession, survey_id: int, actor_id: str, operator, *, editable: bool):
        """問卷 id → 暫存節點；回 `(None, course_id)` 代表該走活表路徑（#631 PR 2b）。

        🔴 **凍結照樣檢核**（`editable=True` 時）：SA Q2 ② 裁示「仍凍結」——有填答時題目
        與選項不可改，暫存模式一樣。判定看的是**活表**那份問卷有沒有填答，因為填答是對
        已生效版本做的。

        ⚠️ 這裡是「編輯當下」那一次檢核；`stage_apply._ensure_survey_not_frozen` 是
        「套用當下」再問一次。兩者缺一不可——中間隔著可能很長的編輯期間（TOCTOU）。
        """
        ref = await self._stage_writer.resolve_new(db, survey_id, ENTITY_SURVEY)
        if ref is not None:
            course = await self._courses.get(db, ref.course_id)
            if course is None:
                raise _NOT_FOUND
            ensure_owner(owner_id=course.owner_id, actor_id=actor_id)
            await self._stage_writer.lock_course(db, ref.course_id)
            # 本次編輯新建的問卷還沒進活表 ⇒ 不可能有填答，不必問凍結。
            # ⛔ 這個「不問凍結」是**承重的**，理由見 `_staged_sq` 同一處的擋牌。
            return ref, ref.course_id

        survey = await self._require_owned(db, survey_id, actor_id)
        if editable:
            ensure_editable(has_responses=await self._surveys.has_responses(db, survey_id))
        course = await self._courses.get(db, survey.course_id)
        if not is_staged(course):
            return None, survey.course_id
        await self._stage_writer.lock_course(db, survey.course_id)
        ref = await self._stage_writer.ref_for_source(
            db, survey.course_id, ENTITY_SURVEY, survey_id, operator, gone_error=_NOT_FOUND
        )
        return ref, survey.course_id

    async def _staged_sq(self, db: AsyncSession, sq_id: int, actor_id: str, operator):
        """問卷題目 id → 暫存節點；回 `(None, course_id, survey_id)` 代表走活表路徑。

        ## ⛔ 負數分支的「不問凍結」是逃生門，不是漏檢（2026-10-18 security review M-2）

        負數 id ＝ **本次編輯才新增、活表還沒有**的題目。學員不可能填答一個還沒生效的
        題目，所以不問凍結在語意上正確——但它同時是教師唯一的脫身路徑：

        教師在 T1 新增一題（此時無填答，合法）→ 學員在 T2 對**既有題目**填答 →
        教師在 T3 按「更新」，`stage_apply._ensure_survey_not_frozen` 比對「暫存結構 ≠
        活表結構」而 422。此時他要能把 T1 新增的那題**刪掉**，結構才會重新相等、更新
        才過得去——走的正是這條分支。

        若有人「順手把負數分支也補上凍結檢核」，那一題就永遠刪不掉，而
        `_ensure_survey_not_frozen` 會讓**整門課**的更新從此 422：章節、教材、測驗的編輯
        一起陪葬，唯一出路剩下「放棄編輯」丟掉全部。⚠️ 既有測試不會紅——沒有任何一條
        測試走「新增題目 → 產生填答 → 刪掉新題 → 更新成功」這條路。

        ⚠️ **這條逃生門只蓋得住「新增」**。教師若在 T1 改了**既有**題目的題幹，正數分支
        的 `ensure_editable` 會讓他改不回去，而更新也過不去——那個死結本 PR 未解，列為
        已知限制（見 PR 說明），須另開 issue。
        """
        ref = await self._stage_writer.resolve_new(db, sq_id, ENTITY_SURVEY_QUESTION)
        if ref is not None:
            course = await self._courses.get(db, ref.course_id)
            if course is None:
                raise _QUESTION_NOT_FOUND
            ensure_owner(owner_id=course.owner_id, actor_id=actor_id)
            await self._stage_writer.lock_course(db, ref.course_id)
            return ref, ref.course_id, None

        question = await self._surveys.get_question(db, sq_id)
        if question is None:
            raise _QUESTION_NOT_FOUND
        survey_ref, course_id = await self._staged_survey(db, question.survey_id, actor_id, operator, editable=True)
        if survey_ref is None:
            return None, course_id, question.survey_id
        ref = await self._stage_writer.ref_for_source(
            db, course_id, ENTITY_SURVEY_QUESTION, sq_id, operator, gone_error=_QUESTION_NOT_FOUND
        )
        return ref, course_id, question.survey_id

    async def _staged_detail(self, db: AsyncSession, course_id: int, actor_id: str) -> SurveyDetail | None:
        """暫存版的問卷詳細；回 `None` 代表沒有暫存區（或本次沒有問卷節點）、該走活表。

        ⚠️ **只對擁有者**（同 `course/service.get_detail` 的理由：他人看到的必須是學員
        看得到的那一版）。

        ⚠️ 沒有問卷節點時回 `None` 是安全的：`delete` 僅草稿課程可用，所以已發布課程的
        問卷**不可能**在暫存期間被刪掉——節點空只會是「這門課本來就沒有問卷」，退回活表
        一樣查不到。⛔ 若日後開放已發布課程刪問卷，這裡要改成區分兩者，否則刪除會靜默
        復活（形狀同 `has_stage` 的那個 bug）。
        """
        course = await self._courses.get(db, course_id)
        if course is None or course.owner_id != actor_id or not is_staged(course):
            return None
        if not await self._stage_writer.has_stage(db, course_id):
            return None
        roots = await self._stage_writer.children_of(db, course_id, ENTITY_SURVEY, None)
        if not roots:
            return None
        node = roots[0]
        questions = await self._stage_writer.children_of(db, course_id, ENTITY_SURVEY_QUESTION, node.stage_id)
        rows = [await self._staged_question_row(db, course_id, q) for q in questions]
        # 填答統計一律取**活表**：那是事實，與編輯中的題目無關。本次新建的問卷（尚無
        # `source_id`）還沒有人填過，一律 0。
        live_id = node.source_id
        responded = 0 if live_id is None else await self._surveys.count_responses(db, live_id)
        enrolled = await self._surveys.count_enrollments(db, course_id)
        return SurveyDetail(
            survey_id=exposed_id(source_id=node.source_id, stage_id=node.stage_id),
            course_id=course_id,
            survey_name=str(node.payload.get("survey_name") or ""),
            is_active=bool(node.payload.get("is_active")),
            version=node.version,
            frozen=responded > 0,
            responded_count=responded,
            pending_count=max(enrolled - responded, 0),
            questions=rows,
        )

    async def _staged_question_row(self, db: AsyncSession, course_id: int, node) -> SurveyQuestionRow:
        """暫存版的 `_question_row`——id 一律走 `exposed_id`（新增的回負數）。"""
        options = await self._stage_writer.children_of(db, course_id, ENTITY_SURVEY_OPTION, node.stage_id)
        return SurveyQuestionRow(
            sq_id=exposed_id(source_id=node.source_id, stage_id=node.stage_id),
            question_type=str(node.payload.get("question_type") or ""),
            stem=str(node.payload.get("stem") or ""),
            sort_order=node.sort_order,
            version=node.version,
            options=[
                # ⚠️ 問卷選項的欄位叫 `so_id`，測驗的叫 `option_id`——兩個 schema 不同名。
                # 寫錯會在 pydantic 驗證時爆 500，而不是靜默，算是幸運。
                SurveyOptionRow(
                    so_id=exposed_id(source_id=o.source_id, stage_id=o.stage_id),
                    option_text=str(o.payload.get("option_text") or ""),
                    sort_order=o.sort_order,
                )
                for o in options
            ],
        )

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
        # after_value 只帶 course_name：供 DP05 對象欄顯示課程名而非 ID（#717）。
        # 取**當下**值存進稽核列，課程日後改名不改寫歷史；⛔ 不得加入學員姓名（個資）。
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type=action,
            result="SUCCESS",
            operator_id=operator_id,
            target_id=str(course_id),
            description=description,
            after_value=await course_audit_payload(db, course_id) or None,
            source_ip=get_client_ip(),
        )
