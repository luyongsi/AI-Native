"""005_notifications_table

Revision: 005
Create Date: 2026-06-30

Create notifications table for user-facing notification feed.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column(
            "id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "type",
            sa.String(20),
            nullable=False,
            server_default="system",
        ),
        sa.Column(
            "level",
            sa.String(10),
            nullable=False,
            server_default="info",
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column(
            "read",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
        ),
        sa.Column("link", sa.String(500)),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("notifications")
