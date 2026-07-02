"""003_releases_table

Revision: 003
Create Date: 2026-06-30

Create releases table for release management and tracking.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "releases",
        sa.Column(
            "id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="planning",
        ),
        sa.Column("release_window_start", postgresql.TIMESTAMP(timezone=True)),
        sa.Column("release_window_end", postgresql.TIMESTAMP(timezone=True)),
        sa.Column("total_reqs", sa.Integer(), server_default=sa.text("0")),
        sa.Column("completed_reqs", sa.Integer(), server_default=sa.text("0")),
        sa.Column("progress", sa.Numeric(5, 2), server_default=sa.text("0")),
        sa.Column("requirements", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("risks", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("stages", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("releases")
