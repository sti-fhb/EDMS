"""tmp_598_dual_head_probe

Revision ID: aaaaaaaaaaaa
Revises: 084cef76719a
Create Date: 2026-10-30 00:00:00.000000

⛔ #598 驗證用的暫時 migration，驗完即 revert，不得合併。

刻意與 18489e30023b 共用 down_revision，造出雙頭，
用來證明 CI「檢查 Alembic heads」會變紅。
"""

from collections.abc import Sequence

revision: str = "aaaaaaaaaaaa"
down_revision: str | None = "084cef76719a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
