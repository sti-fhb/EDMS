"""merge et_survey_types and file_path_relative

Revision ID: 377b5d256c3e
Revises: 676114dc0672, 8713c6177f6f
Create Date: 2026-08-31 12:02:06.509603

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '377b5d256c3e'
down_revision: Union[str, None] = ('676114dc0672', '8713c6177f6f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
