"""002_requirements_extended

Revision: 002
Create Date: 2026-06-30

Phase 4A (SPEC-40): Add description, pm, assignees, sla_deadline, and
related_ids columns to the requirements table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "requirements",
        sa.Column("description", sa.Text()),
    )
    op.add_column(
        "requirements",
        sa.Column("pm", sa.String(100)),
    )
    op.add_column(
        "requirements",
        sa.Column(
            "assignees",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "requirements",
        sa.Column(
            "sla_deadline",
            postgresql.TIMESTAMP(timezone=True),
        ),
    )
    op.add_column(
        "requirements",
        sa.Column(
            "related_ids",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("requirements", "related_ids")
    op.drop_column("requirements", "sla_deadline")
    op.drop_column("requirements", "assignees")
    op.drop_column("requirements", "pm")
    op.drop_column("requirements", "description")
