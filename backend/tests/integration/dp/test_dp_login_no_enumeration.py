"""登入端點不得洩漏「待驗證列的有無」（#208）。

## 這一檔在守什麼

`POST /api/login` 在**驗證密碼之前**就查了待驗證表。只要回應隨該列存在與否而變，匿名者
**密碼隨便填**就能問出某個 Email 是否有待驗證列——而 `ADMIN_INVITE` 列同樣命中，於是
「組織邀請了誰」成為可匿名列舉的資訊。

修法是把**對外回應**收斂成一個，**稽核**仍保留區分（#208 注意事項第 3 點：對外統一、對內可區分）。

## 明知而刻意保留的殘留

`DP_AUTH_008`（已驗證帳號、密碼錯）與 `DP_AUTH_007` 仍可區分，因此「某 Email 是否為已驗證
帳號」依然可探測。這是 #208 AC 2 明訂要維持的行為（既有鎖定計數與 UX 都掛在上面），
本檔第二個 class 把它**釘住**——不是因為它好，而是因為它若被順手改掉，鎖定計數的行為
也會跟著變，而那不在 #208 的範圍內。本檔收斂的是**待驗證列的有無**。

## 為什麼四種狀態要在同一條測試裡比

分成四條各自斷言「回 DP_AUTH_007」也會全綠，但那驗不到「彼此相同」——任何一條的訊息
被改動、或未來有人替某一類加回專屬提示，四條各自的斷言都還會過。必須在同一條裡取集合。
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.exceptions import AppError
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.user.kinds import KIND_ADMIN_INVITE, KIND_SELF_REGISTER
from app.dp.user.models import DpPendingRegistration
from app.dp.user.service import AuthService
from app.dp.user.token import generate_reset_token, hash_token
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_PWD = "Abcd1234"
_ANY_PWD = "whatever-the-attacker-types"


async def _verified_user(db, *, user_id: str, email: str) -> None:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=email,
            pwd_hash=hash_password(_PWD),
            user_name="已驗證",
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=now,
            created_user="seed",
            created_date=now,
        )
    )
    await db.flush()


async def _pending(db, *, email: str, kind: str = KIND_SELF_REGISTER, minutes: int = 30) -> None:
    now = utcnow()
    db.add(
        DpPendingRegistration(
            token_hash=hash_token(generate_reset_token()),
            email=email,
            user_name="待驗證",
            pwd_hash=None,
            kind=kind,
            expires_date=now + timedelta(minutes=minutes),
            created_user="SYSTEM",
            created_date=now,
        )
    )
    await db.flush()


async def _login_error(db, email: str, password: str = _ANY_PWD) -> AppError:
    with pytest.raises(AppError) as exc:
        await AuthService().login(db, email=email, password=password)
    return exc.value


def _signature(err: AppError) -> tuple[int, str | None, str]:
    """攻擊者看得見的全部：status / error_code / message。三者任一不同即可區分狀態。"""
    return (err.status_code, err.error_code, err.detail)


class TestPendingRowNotObservable:
    async def test_四種帳號狀態的回應完全一致(self, db) -> None:
        """AC 1：自助註冊未驗證 / 管理者已邀請 / 完全不存在 / 待驗證列已逾期 → 同一個回應。

        「管理者已邀請」是這條的核心——`ADMIN_INVITE` 列命中時若給出專屬回應，等於把
        「組織邀請了誰」開放給任何人以任意密碼查詢。
        """
        await _pending(db, email="self@edms.local", kind=KIND_SELF_REGISTER)
        await _pending(db, email="invited@edms.local", kind=KIND_ADMIN_INVITE)
        await _pending(db, email="expired@edms.local", kind=KIND_SELF_REGISTER, minutes=-1)

        signatures = {
            state: _signature(await _login_error(db, email))
            for state, email in {
                "自助註冊未驗證": "self@edms.local",
                "管理者已邀請": "invited@edms.local",
                "待驗證列已逾期": "expired@edms.local",
                "完全不存在": "ghost@edms.local",
            }.items()
        }

        assert len(set(signatures.values())) == 1, f"四種狀態的回應必須無法區分，實得：{signatures}"
        status, code, _ = next(iter(signatures.values()))
        assert (status, code) == (401, "DP_AUTH_007")

        # 防呆：上面若因前置資料被回滾而四者皆變成「完全不存在」，這條會紅。
        # 沒有它，一次全域回滾就能讓整條測試貌似通過。
        remaining = (await db.execute(select(DpPendingRegistration.email))).scalars().all()
        assert {"self@edms.local", "invited@edms.local", "expired@edms.local"} <= set(remaining), (
            "待驗證列在比較過程中消失了，上面的『四者一致』是假的"
        )

    async def test_統一訊息同時鋪出三條自助出路(self, db) -> None:
        """AC 3：說話的人不知道對方是哪一種狀態，所以一句話必須同時涵蓋註冊 / 驗證 / 重寄。

        少了任何一條，就有一類使用者看著這句話無路可走——這正是 #56 當初加 `DP_AUTH_010`
        要解決的問題，本次改以「一句話涵蓋全部」解決，因此這三個詞是驗收條件而非文案偏好。
        """
        message = (await _login_error(db, "nobody@edms.local")).detail

        assert "註冊" in message, "完全不存在的使用者需要知道可以去註冊"
        assert "驗證連結" in message, "剛註冊未驗證的使用者需要知道去信箱點連結"
        assert "重新寄送" in message, "沒收到信的使用者需要知道可以重寄"

    async def test_稽核仍能區分未驗證與不存在(self, db) -> None:
        """AC 4：對外統一不得連稽核一起收斂掉——稽核是內部軌跡，不對外，不構成洩漏。

        這條與上面兩條方向相反：上面要求「看不出差別」，這條要求「查得出差別」。
        兩者同時成立才是正確的修法；只做到前者會讓事故調查失去追溯能力。
        """
        await _pending(db, email="audit_pending@edms.local")

        await _login_error(db, "audit_pending@edms.local")
        await _login_error(db, "audit_ghost@edms.local")

        reasons = (
            (
                await db.execute(
                    select(DpAuditLog.description).where(DpAuditLog.func_name == "DP-AUTH", DpAuditLog.result == "FAIL")
                )
            )
            .scalars()
            .all()
        )
        assert "帳號未驗證" in reasons and "帳號不存在" in reasons, f"稽核 reason 應可區分，實得：{set(reasons)}"


class TestVerifiedAccountUnchanged:
    """AC 2：已驗證帳號的路徑一個字都不能動（鎖定計數掛在上面）。"""

    async def test_已驗證帳號密碼錯仍回_DP_AUTH_008(self, db) -> None:
        await _verified_user(db, user_id="u_kept", email="kept@edms.local")

        err = await _login_error(db, "kept@edms.local", password="wrong-password")

        assert (err.status_code, err.error_code) == (401, "DP_AUTH_008")
        assert err.detail == "密碼錯誤"

    async def test_失敗計數仍遞增(self, db) -> None:
        """鎖定機制的入口。若有人為了「訊息一致」把這條路徑也改掉，計數會一起失效。"""
        await _verified_user(db, user_id="u_count", email="count@edms.local")

        await _login_error(db, "count@edms.local", password="wrong-password")

        user = (await db.execute(select(DpUser).where(DpUser.user_id == "u_count"))).scalar_one()
        assert user.login_fail_count == 1

    async def test_已驗證帳號與查無帳號仍可區分(self, db) -> None:
        """明知而刻意保留的殘留，釘住以免日後被誤認為「#208 沒做完」。

        #208 AC 2 明訂維持 `DP_AUTH_008`，故「某 Email 是否為已驗證帳號」仍可探測。
        若日後決定連這一格也收斂，必須連帶處理鎖定計數與前端 UX，屬另一張 issue。
        """
        await _verified_user(db, user_id="u_dist", email="dist@edms.local")

        verified = _signature(await _login_error(db, "dist@edms.local"))
        unknown = _signature(await _login_error(db, "nosuch@edms.local"))

        assert verified != unknown
