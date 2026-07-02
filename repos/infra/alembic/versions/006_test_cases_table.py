"""006_test_cases_table

Revision: 006
Create Date: 2026-06-30

Create test_cases table for individual test case management.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "test_cases",
        sa.Column(
            "id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "req_id",
            postgresql.UUID(),
            sa.ForeignKey("requirements.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("steps", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("preconditions", sa.Text()),
        sa.Column(
            "priority",
            sa.String(5),
            server_default="P2",
        ),
        sa.Column(
            "status",
            sa.String(20),
            server_default="pending",
        ),
        sa.Column("tags", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "ai_generated",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
        ),
        sa.Column("last_run_at", postgresql.TIMESTAMP(timezone=True)),
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
    op.create_index("idx_test_cases_req", "test_cases", ["req_id"])


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_test_cases_req")
    op.drop_table("test_cases")
