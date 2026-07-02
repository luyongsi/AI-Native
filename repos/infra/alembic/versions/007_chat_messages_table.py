"""007_chat_messages_table

Revision: 007
Create Date: 2026-06-30

Persist chat messages so they survive backend restarts.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_messages",
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
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_chat_messages_req", "chat_messages", ["req_id", "created_at"])


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chat_messages_req")
    op.drop_table("chat_messages")
