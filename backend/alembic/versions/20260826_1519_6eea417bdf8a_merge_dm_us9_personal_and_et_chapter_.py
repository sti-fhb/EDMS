"""merge_dm_us9_personal_and_et_chapter_order

Revision ID: 6eea417bdf8a
Revises: e6a4c7b18d93, 8afb64daa14b
Create Date: 2026-08-26 15:19:17.129523

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6eea417bdf8a'
down_revision: Union[str, None] = ('e6a4c7b18d93', '8afb64daa14b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
