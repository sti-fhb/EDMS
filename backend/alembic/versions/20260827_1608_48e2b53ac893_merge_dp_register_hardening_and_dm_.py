"""merge_dp_register_hardening_and_dm_editor_draft

Revision ID: 48e2b53ac893
Revises: 070865346fb4, dfa09c18c56e
Create Date: 2026-08-27 16:08:14.755614

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '48e2b53ac893'
down_revision: Union[str, None] = ('070865346fb4', 'dfa09c18c56e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
