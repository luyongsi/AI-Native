"""004_alerts_table

Revision: 004
Create Date: 2026-06-30

Create alerts table for system alerts and incident tracking.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column(
            "id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "level",
            sa.String(10),
            nullable=False,
            server_default="info",
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("source", sa.String(50)),
        sa.Column("affected", sa.String(200)),
        sa.Column("root_cause", sa.Text()),
        sa.Column("ai_suggestion", sa.Text()),
        sa.Column(
            "acknowledged",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("alerts")
