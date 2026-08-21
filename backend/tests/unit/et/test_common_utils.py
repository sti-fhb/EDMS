"""ET 共用工具 unit test（AC 7 樂觀鎖 / AC 9 token；T028 / T031 / T032）。

三者皆為純函式或不需真 DB 的邏輯，依 sti-testing「拿掉真 DB 仍驗得了就寫 unit」原則
一律 unit——樂觀鎖以 rowcount 模擬、邀請碼以注入的長度與既有碼集合驗證。
"""

import re

import pytest

from app.core.exceptions import AppError
from app.et.common.invitation_code import INVITATION_CODE_MAX_LEN, generate_invitation_code
from app.et.common.optimistic_lock import ensure_version_matched
from app.et.common.tokens import generate_invitation_token, hash_token


class TestOptimisticLock:
    def test_更新有影響列時通過(self) -> None:
        ensure_version_matched(rowcount=1, entity="ET_COURSE")  # 不拋例外即通過

    def test_版本不符時拋出明確衝突(self) -> None:
        with pytest.raises(AppError) as exc:
            ensure_version_matched(rowcount=0, entity="ET_COURSE")
        assert exc.value.status_code == 409
        assert exc.value.error_code == "ET_LOCK_001"

    def test_錯誤訊息不含實體名稱以免洩漏_schema(self) -> None:
        """per sti-error-codes：error_message 不得嵌入動態值或欄位名稱。"""
        with pytest.raises(AppError) as exc:
            ensure_version_matched(rowcount=0, entity="ET_COURSE")
        assert "ET_COURSE" not in exc.value.detail


class TestInvitationToken:
    def test_長度足夠且為_url_safe(self) -> None:
        token = generate_invitation_token()
        # secrets.token_urlsafe(32) → 256 bits 亂數、43 字元；須塞得進 ET_INVITATION.TOKEN VARCHAR(64)
        assert 32 <= len(token) <= 64
        assert re.fullmatch(r"[A-Za-z0-9_-]+", token)

    def test_每次產出皆不同(self) -> None:
        assert len({generate_invitation_token() for _ in range(50)}) == 50

    def test_雜湊為_64_字元十六進位且同輸入同輸出(self) -> None:
        """DB 只存雜湊（ET_INVITATION.TOKEN_HASH VARCHAR(64)），驗證時重新雜湊比對。"""
        token = generate_invitation_token()
        h = hash_token(token)
        assert len(h) == 64
        assert re.fullmatch(r"[0-9a-f]{64}", h)
        assert hash_token(token) == h, "同一 token 須得到相同雜湊，否則驗證永遠失敗"

    def test_不同_token_雜湊相異(self) -> None:
        assert hash_token("a") != hash_token("b")


class TestInvitationCode:
    def test_預設八碼純數字(self) -> None:
        code = generate_invitation_code(length=8, exists=lambda _: False)
        assert re.fullmatch(r"\d{8}", code)

    def test_碰撞時重產(self) -> None:
        seen: list[str] = []

        def exists(code: str) -> bool:
            # 前兩次都宣告碰撞，第三次才放行
            seen.append(code)
            return len(seen) < 3

        code = generate_invitation_code(length=8, exists=exists)
        assert re.fullmatch(r"\d{8}", code)
        assert len(seen) == 3

    def test_長度超過欄位上限時_fail_fast(self) -> None:
        """ET_COURSE.INVITATION_CODE 為 VARCHAR(8) 硬編，參數若被調大須擋下而非靜默截斷。"""
        with pytest.raises(ValueError, match="INVITATION_CODE"):
            generate_invitation_code(length=INVITATION_CODE_MAX_LEN + 1, exists=lambda _: False)

    def test_長度小於一時_fail_fast(self) -> None:
        with pytest.raises(ValueError):
            generate_invitation_code(length=0, exists=lambda _: False)

    def test_連續碰撞達上限時放棄並報錯(self) -> None:
        """避免在碼空間耗盡時無限迴圈。"""
        with pytest.raises(RuntimeError, match="邀請碼"):
            generate_invitation_code(length=8, exists=lambda _: True)
