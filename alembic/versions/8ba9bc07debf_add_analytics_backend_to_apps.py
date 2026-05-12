"""add analytics_backend to apps

Revision ID: 8ba9bc07debf
Revises: 276accb66c04
Create Date: 2026-05-12 13:24:26.158312

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8ba9bc07debf'
down_revision: Union[str, Sequence[str], None] = '276accb66c04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('apps', sa.Column('analytics_backend', sa.String(), server_default='clickhouse', nullable=False))


def downgrade() -> None:
    op.drop_column('apps', 'analytics_backend')
