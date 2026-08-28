"""ET Foundation 驗收測試（AC 2 / 3 / 4 / 8；#185）。

涵蓋兩類正向測試不易觸及的斷言：

1. **反向驗證**——確認不該存在的東西確實不存在（未建 lookup 表、ET 無 SMTP 連線碼）。
2. **跨模組消費驗證**——ET 的通知範本經平台 `NotifyService` 不會靜默失敗（AC 8）。
"""

from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.exceptions import AppError
from app.core.module_admin import module_admin_gate
from app.core.module_assign import module_assign_registry
from app.core.module_provisioning import module_provisioning_gate
from app.core.module_roles import module_role_gate
from app.core.utils import utcnow
from app.et import constants as c
from app.et.bootstrap import register_et_module
from app.et.constants import ROLE_ADMIN, ROLE_STUDENT, ROLE_TEACHER
from app.et.deps import load_et_roles
from app.et.roles.models import EtUserRole
from app.services import NotifyService

pytestmark = pytest.mark.integration


@pytest.fixture
def et_registered():
    """註冊 ET 四閘 checker / provider；**teardown 清除避免污染其他模組測試**。

    比照 `tests/integration/dp/test_dp_roles.py` 之 `dm_registered`。聚合閘為 module-level
    單例，若不清除會讓「未註冊模組 → fail-closed」類測試在同一 worker 內失準。
    """
    register_et_module()
    yield
    module_assign_registry.unregister("ET")
    module_admin_gate.unregister("ET")
    module_role_gate.unregister("ET")
    module_provisioning_gate.unregister("ET")


class TestAc2LookupNotMaterialised:
    """AC 2：9 類 Lookup 為應用層常數——**不得**產生任何 lookup 資料表。"""

    async def test_未建立任何_lookup_表(self, db, et_registered) -> None:
        rows = await db.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = ANY(:names)"
            ),
            {"names": list(c.LOOKUP_SETS.keys())},
        )
        assert rows.scalars().all() == [], "Lookup 代碼應為應用層常數，不得建表"

    async def test_十類常數皆有定義(self, db, et_registered) -> None:
        """#185 建置時為 9 類；#238 新增 `ET_SURVEY_QUESTION_TYPE`（問卷問答題型）增為 10 類。

        > 同一個不變量在 `tests/unit/et/test_constants.py::test_共十類代碼集合` 也有一份
        > 守門。兩處都寫死類別數是刻意的——unit 那份跑得快、先失敗；本條屬 Foundation
        > 驗收，確保「代碼不建表、以常數表達」這個 AC 隨模組成長仍成立。
        """
        assert len(c.LOOKUP_SETS) == 10
        assert all(values for values in c.LOOKUP_SETS.values())


class TestAc3Seeds:
    """AC 3：ET_TAG 5 筆 + DP_PARAM 6 項 + DP_NOTIFY_TEMPLATE 7 類。"""

    async def test_et_tag_五筆內建且全體為_is_all(self, db, et_registered) -> None:
        rows = await db.execute(
            text('SELECT "TAG_NAME", "IS_ALL", "IS_BUILTIN" FROM "ET_TAG" ORDER BY "DISPLAY_ORDER"')
        )
        tags = rows.all()
        assert len(tags) == 5
        assert [t[0] for t in tags] == ["全體", "護理師", "行政人員", "軍人", "醫檢師"]
        assert tags[0][1] is True, "「全體」須為 IS_ALL"
        assert sum(1 for t in tags if t[1]) == 1, "全系統僅 1 筆 IS_ALL"
        assert all(t[2] for t in tags), "種子皆為內建標籤"

    async def test_et_參數六項種入平台表(self, db, et_registered) -> None:
        rows = await db.execute(
            text('SELECT "PARAM_ID" FROM "DP_PARAM_M" WHERE "PARAM_ID" LIKE :p ORDER BY 1'), {"p": "ET\\_%"}
        )
        assert rows.scalars().all() == [
            "ET_INVITATION_CODE_LENGTH",
            "ET_URGENT_REMIND_DAYS",
            "ET_VIDEO_ALLOWED_FORMATS",
            "ET_VIDEO_MAX_SIZE_MB",
            "ET_VIDEO_PLAYBACK_MAX_RATE",
            "ET_WEEKLY_STAT_DAY_TIME",
        ]

    async def test_et_通知範本七類且_channel_為平台正規詞彙(self, db, et_registered) -> None:
        rows = await db.execute(
            text('SELECT "TEMPLATE_CODE", "CHANNEL", "IS_SYSTEM" FROM "DP_NOTIFY_TEMPLATE" WHERE "MODULE" = :m'),
            {"m": "ET"},
        )
        items = rows.all()
        assert len(items) == 7
        assert {i[0] for i in items} == {
            "COURSE_INVITE",
            "COURSE_INVITE_DIGEST",
            "COURSE_UPDATE",
            "WEEKLY_REMIND",
            "URGENT_REMIND",
            "WEEKLY_REPORT",
            "APPROVAL_PASSED",
        }
        # CHANNEL 自創值會使平台 send_email 靜默不寄信
        assert all(i[1] in {"EMAIL", "MSG", "BOTH"} for i in items)
        assert not any(i[2] for i in items), "ET 7 類皆為管理者可維護，非平台系統信"

    async def test_週報範本含_csv_下載連結變數(self, db, et_registered) -> None:
        """2026-08-19 變更：郵件附件改為下載連結（平台發信不支援附件）。"""
        body = await db.scalar(
            text('SELECT "BODY" FROM "DP_NOTIFY_TEMPLATE" WHERE "MODULE" = :m AND "TEMPLATE_CODE" = :c'),
            {"m": "ET", "c": "WEEKLY_REPORT"},
        )
        assert "{REPORT_CSV_URL}" in body


class TestAc4AdminCanAssign:
    """AC 4：取得 ET 管理者角色後，可經 dp-roles 之 provider 指派他人角色。

    這是 bootstrap seed 的**實際價值**——解開「要當管理者才能指派管理者」之死結。
    """

    async def _grant(self, db, user_id: str, role: str) -> None:
        db.add(
            EtUserRole(
                user_id=user_id, role=role, is_active=True, created_user="SYSTEM", created_date=utcnow(), deleted=0
            )
        )
        await db.flush()

    async def test_管理者可經_provider_指派他人角色與標籤(self, db, et_registered) -> None:
        await self._grant(db, "ET_AC4_ADMIN", ROLE_ADMIN)
        provider = module_assign_registry.get("ET")
        assert provider is not None

        tag_id = await db.scalar(text('SELECT "TAG_ID" FROM "ET_TAG" WHERE "TAG_NAME" = :n'), {"n": "護理師"})
        await provider.assign(
            db,
            user_id="ET_AC4_TARGET",
            roles={ROLE_TEACHER, ROLE_STUDENT},
            groups={str(tag_id)},
            operator_id="ET_AC4_ADMIN",
        )
        assert await load_et_roles(db, "ET_AC4_TARGET") == frozenset({ROLE_TEACHER, ROLE_STUDENT})

        view = (await provider.get_users_assignments(db, ["ET_AC4_TARGET"]))["ET_AC4_TARGET"]
        assert view.groups == frozenset({str(tag_id)})

    async def test_自我保護_不可取消自己的管理者角色(self, db, et_registered) -> None:
        await self._grant(db, "ET_AC4_SELF", ROLE_ADMIN)
        provider = module_assign_registry.get("ET")
        with pytest.raises(AppError) as e:
            await provider.assign(
                db, user_id="ET_AC4_SELF", roles={ROLE_TEACHER}, groups=set(), operator_id="ET_AC4_SELF"
            )
        assert e.value.error_code == "ET_ROLE_001"

    async def test_無效角色代碼被擋(self, db, et_registered) -> None:
        provider = module_assign_registry.get("ET")
        with pytest.raises(AppError) as e:
            await provider.assign(db, user_id="ET_AC4_X", roles={"SUPERUSER"}, groups=set(), operator_id="ET_AC4_OP")
        assert e.value.error_code == "ET_ROLE_003"

    async def test_未啟用標籤不可新增指派(self, db, et_registered) -> None:
        provider = module_assign_registry.get("ET")
        tag_id = await db.scalar(text('SELECT "TAG_ID" FROM "ET_TAG" WHERE "TAG_NAME" = :n'), {"n": "軍人"})
        await db.execute(text('UPDATE "ET_TAG" SET "IS_ACTIVE" = false WHERE "TAG_ID" = :t'), {"t": tag_id})
        await db.flush()
        with pytest.raises(AppError) as e:
            await provider.assign(db, user_id="ET_AC4_Y", roles=set(), groups={str(tag_id)}, operator_id="ET_AC4_OP")
        assert e.value.error_code == "ET_ROLE_002"

    async def test_全體標籤不可停用(self, db, et_registered) -> None:
        """ET 業務規則之伺服器端保護——DP 端旗標與前端隱藏僅為 UX。"""
        provider = module_assign_registry.get("ET")
        tag_id = await db.scalar(text('SELECT "TAG_ID" FROM "ET_TAG" WHERE "IS_ALL" = true'))
        with pytest.raises(AppError) as e:
            await provider.set_controlled_enabled(db, "TAG", code=str(tag_id), enabled=False, operator_id="ET_AC4_OP")
        assert e.value.error_code == "ET_TAG_001"

    async def test_可指派標籤清單排除全體(self, db, et_registered) -> None:
        provider = module_assign_registry.get("ET")
        names = {i.name for i in await provider.list_audiences(db)}
        assert "全體" not in names, "「全體」代表所有學員角色者，不需逐人指派"
        assert "護理師" in names


class TestCatalogMaintenance:
    """受控主檔維護之業務保護與稽核（Code Review 補強：rename / create 原無測試）。"""

    async def test_內建標籤不可改名(self, db, et_registered) -> None:
        provider = module_assign_registry.get("ET")
        tag_id = await db.scalar(text('SELECT "TAG_ID" FROM "ET_TAG" WHERE "TAG_NAME" = :n'), {"n": "護理師"})
        with pytest.raises(AppError) as e:
            await provider.rename_controlled(db, "TAG", code=str(tag_id), new_name="護理人員", operator_id="ET_CAT_OP")
        assert e.value.status_code == 422
        assert e.value.error_code == "ET_TAG_001"

    async def test_新增標籤名稱重複被擋(self, db, et_registered) -> None:
        provider = module_assign_registry.get("ET")
        with pytest.raises(AppError) as e:
            await provider.create_controlled(db, "TAG", code="", name="軍人", operator_id="ET_CAT_OP")
        assert e.value.status_code == 409
        assert e.value.error_code == "ET_TAG_002"

    async def test_查無標籤回_404_專用碼(self, db, et_registered) -> None:
        provider = module_assign_registry.get("ET")
        with pytest.raises(AppError) as e:
            await provider.rename_controlled(db, "TAG", code="999999", new_name="X", operator_id="ET_CAT_OP")
        assert e.value.status_code == 404
        assert e.value.error_code == "ET_TAG_003"

    async def test_非_tag_類別被擋(self, db, et_registered) -> None:
        provider = module_assign_registry.get("ET")
        with pytest.raises(AppError) as e:
            await provider.list_controlled(db, "CATEGORY")
        assert e.value.error_code == "ET_TAG_003"

    async def test_新增自訂標籤成功且非內建(self, db, et_registered) -> None:
        provider = module_assign_registry.get("ET")
        await provider.create_controlled(db, "TAG", code="", name="放射師", operator_id="ET_CAT_OP")
        items = {i.name: i for i in await provider.list_controlled(db, "TAG")}
        assert "放射師" in items
        assert items["放射師"].is_builtin is False
        assert items["放射師"].is_enabled is True

    async def test_稽核_func_name_區分指派與定義維護(self, db, et_registered) -> None:
        """ET-ROLES（指派）與 ET-CATALOG（標籤庫定義）須為不同稽核來源碼。

        比照 DM 之 DM-ROLES / DM-CATALOG——否則稽核無法依 FUNC_NAME 區分兩類管理行為。
        """
        provider = module_assign_registry.get("ET")
        await provider.create_controlled(db, "TAG", code="", name="營養師", operator_id="ET_CAT_AUD")
        await provider.assign(db, user_id="ET_CAT_TARGET", roles={ROLE_STUDENT}, groups=set(), operator_id="ET_CAT_AUD")
        rows = await db.execute(
            text('SELECT DISTINCT "FUNC_NAME" FROM "DP_AUDIT_LOG" WHERE "CREATED_USER" = :u'),
            {"u": "ET_CAT_AUD"},
        )
        func_names = set(rows.scalars().all())
        assert "ET-CATALOG" in func_names
        assert "ET-ROLES" in func_names


class TestInputValidationHardening:
    """Security Review 補強：輸入界限驗證（避免未攔截 500 / 視覺重複標籤）。"""

    async def test_unicode_數字字元不得通過標籤_id_驗證(self, db, et_registered) -> None:
        """`'²'.isdigit()` 為 True 但 `int('²')` 會拋 ValueError → 原本會變成 500。"""
        provider = module_assign_registry.get("ET")
        for bad in ("²", "①", "9" * 25):
            with pytest.raises(AppError) as e:
                await provider.assign(db, user_id="ET_VAL_U1", roles=set(), groups={bad}, operator_id="ET_VAL_OP")
            assert e.value.error_code == "ET_ROLE_002", f"未擋下 {bad!r}"

    async def test_標籤名稱前後空白被正規化_不得建出視覺重複(self, db, et_registered) -> None:
        """`"軍人 "` 若不 strip 會繞過唯一約束、建出看起來一樣的標籤。"""
        provider = module_assign_registry.get("ET")
        with pytest.raises(AppError) as e:
            await provider.create_controlled(db, "TAG", code="", name="  軍人  ", operator_id="ET_VAL_OP")
        assert e.value.error_code == "ET_TAG_002", "strip 後應判定為重複"

    async def test_空白或超長標籤名稱被擋(self, db, et_registered) -> None:
        provider = module_assign_registry.get("ET")
        for bad in ("", "   ", "x" * 51):
            with pytest.raises(AppError) as e:
                await provider.create_controlled(db, "TAG", code="", name=bad, operator_id="ET_VAL_OP")
            assert e.value.error_code == "ET_TAG_004", f"未擋下 {bad!r}"


class TestLastModifiedFallback:
    """Code Review 補強：新授予而未再異動之列，最後異動欄須回退至 CREATED_*。"""

    async def test_僅建立未更新時回退至_created(self, db, et_registered) -> None:
        provider = module_assign_registry.get("ET")
        # grant_default_student_role 建立之列只有 CREATED_*、無 UPDATED_*
        from app.et.roles.provisioning import grant_default_student_role

        await grant_default_student_role(db, "ET_LMF_U1")
        view = (await provider.get_users_assignments(db, ["ET_LMF_U1"]))["ET_LMF_U1"]
        assert view.roles == frozenset({ROLE_STUDENT})
        assert view.last_modified_by == "SYSTEM", "應回退至 CREATED_USER，而非空白"
        assert view.last_modified_date is not None


class TestAc8NoSmtpInEt:
    """AC 8 反向驗證：ET 不得自建 SMTP 連線——寄信一律經平台 NotifyService。"""

    async def test_et_模組無_smtp_相關程式碼(self, db, et_registered) -> None:
        et_root = Path(__file__).resolve().parents[3] / "app" / "et"
        offenders: list[str] = []
        for py in et_root.rglob("*.py"):
            text_content = py.read_text(encoding="utf-8")
            for needle in ("smtplib", "aiosmtplib", "SMTP(", "MAIL_SERVER", "starttls"):
                if needle in text_content:
                    offenders.append(f"{py.name}: {needle}")
        assert offenders == [], f"ET 不得自建 SMTP 連線，發現：{offenders}"


class TestAc8TemplatesConsumableViaNotifyService:
    """AC 8 正向驗證：ET 的通知範本經平台 `NotifyService` 確實渲染成功並排入 outbox。

    **與「seed 已存在」之驗收不同**（後者依 sti-testing 一律不寫）：此處不斷言種了幾筆、
    也不驗欄位型別，而是驗**行為**——範本被平台消費時不會靜默失敗。

    **擋的是什麼**：`send_email` 於渲染失敗時**不拋錯**，而是整批寫 `FAILED` 後回
    `SendResult(queued_count=0, skipped_reason=None)`。注意 `skipped_reason` 與成功時
    同為 `None`，**只有 `queued_count` 分辨得出來**。因此若日後有人改了 `BODY` 的佔位
    卻沒同步 `VARIABLES` 欄，照 `VARIABLES` 傳參的 ET 功能碼會讓整批信靜默進 `FAILED`：
    收件人收不到、呼叫方也拿不到任何例外。本測試把該漂移變成 CI 失敗。

    `queued_count == 1` 這一個斷言即同時涵蓋範本啟用中、`CHANNEL` 允許寄 Email
    （否則回 `TEMPLATE_DISABLED` / `CHANNEL_NOT_EMAIL`）與渲染成功三件事，故不另立測試。
    """

    async def _et_templates(self, db) -> list[tuple[str, str]]:
        """取 ET 範本之 (TEMPLATE_CODE, VARIABLES)；VARIABLES 為呼叫端應傳的參數名清單。"""
        rows = await db.execute(
            text(
                'SELECT "TEMPLATE_CODE", "VARIABLES" FROM "DP_NOTIFY_TEMPLATE" '
                'WHERE "MODULE" = \'ET\' AND "DELETED" = 0 ORDER BY "TEMPLATE_CODE"'
            )
        )
        return [(r[0], r[1] or "") for r in rows.all()]

    @staticmethod
    def _params_per_declaration(variables: str) -> dict[str, str]:
        """模擬未來 ET 功能碼之行為：照 `VARIABLES` 欄宣告的變數名傳參。"""
        return {v.strip(): "X" for v in variables.split(",") if v.strip()}

    async def test_每個範本皆可以其宣告之參數成功排入_outbox(self, db) -> None:
        templates = await self._et_templates(db)
        assert templates, "ET 應有通知範本可驗（避免本測試空跑而假性通過）"

        service = NotifyService()
        failures: list[str] = []
        for code, variables in templates:
            result = await service.send_email(
                db,
                recipients=[f"ac8-{code.lower()}@example.invalid"],
                template_code=code,
                module="ET",
                params=self._params_per_declaration(variables),
                caller_module="ET",
            )
            if result.queued_count != 1:
                failures.append(f"{code}（queued_count={result.queued_count}, skipped={result.skipped_reason}）")
        assert failures == [], f"下列範本無法以其 VARIABLES 宣告之參數渲染，信會靜默進 FAILED：{failures}"

    async def test_outbox_落_pending_且無殘留佔位(self, db) -> None:
        """AC 8 字面要求「寫入 `DP_EMAIL_LOG` outbox」——驗狀態、來源模組與渲染結果。"""
        templates = await self._et_templates(db)
        code, variables = templates[0]
        recipient = "ac8-outbox@example.invalid"
        await NotifyService().send_email(
            db,
            recipients=[recipient],
            template_code=code,
            module="ET",
            params=self._params_per_declaration(variables),
            caller_module="ET",
        )
        status, error_msg, caller_module, subject = (
            await db.execute(
                text(
                    'SELECT "STATUS", "ERROR_MSG", "CALLER_MODULE", "SUBJECT" '
                    'FROM "DP_EMAIL_LOG" WHERE "RECIPIENT" = :r'
                ),
                {"r": recipient},
            )
        ).one()
        assert status == "PENDING", f"應排入 PENDING，實為 {status}（ERROR_MSG={error_msg}）"
        assert error_msg is None
        assert caller_module == "ET", "CALLER_MODULE 須記為 ET，稽核才追得到是哪個模組發的"
        assert "{" not in subject, "SUBJECT 不應殘留未代入之佔位"
