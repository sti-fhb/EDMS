"""merge_dm_editor_draft_and_et_materials

Revision ID: dfa09c18c56e
Revises: f29cb69d6199, 8ce307803975
Create Date: 2026-08-27 14:38:48.170559

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "dfa09c18c56e"
down_revision: Union[str, None] = ("f29cb69d6199", "8ce307803975")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
