"""merge et_survey_publish and dp_register_hardening

Revision ID: 1a85b7fe2cff
Revises: 48e2b53ac893, e9ec96adabab
Create Date: 2026-08-28 13:28:01.909484

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a85b7fe2cff'
down_revision: Union[str, None] = ('48e2b53ac893', 'e9ec96adabab')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
