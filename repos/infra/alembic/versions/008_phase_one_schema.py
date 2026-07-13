"""008_phase_one_schema

Revision: 008
Create Date: 2026-07-10

Phase 1 (A1/A2/Gate0) full schema per design docs v3.5 + data dictionary v1.3 + dev design v2.1.

Creates 7 new tables:
  - requirements (rebuilt with requirement_draft, cycle fields)
  - agent_results
  - dialogue_sessions
  - dialogue_messages
  - understanding_snapshots
  - event_log (with outbox support)
  - approvals

Renames old tables to *_legacy:
  - requirements -> requirements_legacy
  - chat_messages -> chat_messages_legacy
  - gate_approvals -> gate_approvals_legacy
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Rename old tables to *_legacy ──────────────────────────────────
    op.execute("ALTER TABLE IF EXISTS requirements RENAME TO requirements_legacy")
    op.execute("ALTER TABLE IF EXISTS chat_messages RENAME TO chat_messages_legacy")
    op.execute("ALTER TABLE IF EXISTS gate_approvals RENAME TO gate_approvals_legacy")

    # ── 2. New requirements table ─────────────────────────────────────────
    op.create_table(
        "requirements",
        sa.Column("id", postgresql.UUID(), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.String(500)),
        sa.Column("status", sa.String(50), nullable=False,
                  server_default="draft"),
        # 'draft' -> 'analyzing_completed' <-> 'gate_rejected' -> 'approved'

        sa.Column("requirement_draft", postgresql.JSONB()),
        sa.Column("confidence_score", sa.Numeric(3, 2)),

        sa.Column("creator_user_id", sa.String(255)),
        sa.Column("creator_name", sa.String(255)),
        sa.Column("analyzer_agent", sa.String(50), server_default="A1"),
        sa.Column("analyzed_at", postgresql.TIMESTAMP(timezone=True)),

        sa.Column("gate_rejection_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("last_gate_rejection", postgresql.JSONB()),
        sa.Column("revision_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("last_revised_at", postgresql.TIMESTAMP(timezone=True)),

        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.create_index("idx_requirements_status", "requirements", ["status"])

    # ── 3. agent_results table ────────────────────────────────────────────
    op.create_table(
        "agent_results",
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("req_id", postgresql.UUID(), nullable=False),
        sa.Column("agent_key", sa.String(10), nullable=False),
        sa.Column("cycle", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="completed"),
        # 'completed' | 'empty' | 'skipped'
        sa.Column("artifact", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.create_unique_constraint(
        "uq_agent_results_req_agent_cycle",
        "agent_results", ["req_id", "agent_key", "cycle"],
    )
    op.create_index(
        "idx_agent_results_req", "agent_results",
        ["req_id", "agent_key", sa.text("cycle DESC")],
    )
    op.create_foreign_key(
        "fk_agent_results_req", "agent_results", "requirements",
        ["req_id"], ["id"],
    )

    # ── 4. dialogue_sessions table ────────────────────────────────────────
    op.create_table(
        "dialogue_sessions",
        sa.Column("id", postgresql.UUID(), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("req_id", postgresql.UUID(), nullable=False),
        sa.Column("status", sa.String(50), server_default="active"),
        # 'active' | 'completed' | 'reopened' | 'abandoned'

        sa.Column("iterations", sa.Integer(), server_default=sa.text("0")),
        sa.Column("total_messages", sa.Integer(), server_default=sa.text("0")),
        sa.Column("current_understanding", postgresql.JSONB()),
        sa.Column("clarification_points", postgresql.JSONB()),
        sa.Column("confidence_score", sa.Numeric(3, 2)),
        sa.Column("human_confirmations", postgresql.JSONB(),
                  server_default=sa.text("'[]'::jsonb")),

        sa.Column("creator_user_id", sa.String(255)),
        sa.Column("creator_name", sa.String(255)),

        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()")),
        sa.Column("last_updated", postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()")),
        sa.Column("first_confirmed_at", postgresql.TIMESTAMP(timezone=True)),
        sa.Column("last_confirmed_at", postgresql.TIMESTAMP(timezone=True)),
    )
    op.create_unique_constraint(
        "uq_dialogue_sessions_req_id", "dialogue_sessions", ["req_id"],
    )
    op.create_foreign_key(
        "fk_dialogue_sessions_req", "dialogue_sessions", "requirements",
        ["req_id"], ["id"], ondelete="CASCADE",
    )

    # ── 5. dialogue_messages table ────────────────────────────────────────
    op.create_table(
        "dialogue_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("session_id", postgresql.UUID(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("cycle", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("understanding_snapshot_id", sa.BigInteger()),
        sa.Column("timestamp", postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()")),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
    )
    op.create_unique_constraint(
        "uq_dialogue_messages_session_cycle_seq",
        "dialogue_messages", ["session_id", "cycle", "sequence_number"],
    )
    op.create_index(
        "idx_dialogue_messages_session_cycle",
        "dialogue_messages", ["session_id", "cycle", "sequence_number"],
    )
    op.create_foreign_key(
        "fk_dialogue_messages_session", "dialogue_messages",
        "dialogue_sessions", ["session_id"], ["id"], ondelete="CASCADE",
    )

    # ── 6. understanding_snapshots table ──────────────────────────────────
    op.create_table(
        "understanding_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("session_id", postgresql.UUID(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("cycle", sa.Integer(), server_default=sa.text("0")),
        sa.Column("draft", postgresql.JSONB(), nullable=False),
        sa.Column("clarification_points", postgresql.JSONB()),
        sa.Column("confidence_score", sa.Numeric(3, 2)),
        sa.Column("knowledge_sources", postgresql.JSONB()),
        sa.Column("mcp_tools_used", postgresql.JSONB()),
        sa.Column("wireframe_data", postgresql.JSONB()),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.create_index(
        "idx_understanding_snapshots_session_cycle",
        "understanding_snapshots", ["session_id", "cycle"],
    )
    op.create_foreign_key(
        "fk_understanding_snapshots_session", "understanding_snapshots",
        "dialogue_sessions", ["session_id"], ["id"], ondelete="CASCADE",
    )

    # ── 7. event_log table (with outbox support) ──────────────────────────
    op.create_table(
        "event_log",
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("req_id", postgresql.UUID()),
        sa.Column("session_id", postgresql.UUID()),
        sa.Column("cycle", sa.Integer()),
        sa.Column("event_name", sa.String(100), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("outbox_status", sa.String(20), nullable=True),
        sa.Column("published_at", postgresql.TIMESTAMP(timezone=True)),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.create_index("idx_event_log_req", "event_log", ["req_id", "cycle"])
    op.create_index("idx_event_log_name", "event_log", ["event_name"])
    op.create_index(
        "idx_event_log_outbox", "event_log",
        ["outbox_status", "created_at"],
        postgresql_where=sa.text("outbox_status = 'pending'"),
    )

    # ── 8. approvals table ────────────────────────────────────────────────
    op.create_table(
        "approvals",
        sa.Column("id", postgresql.UUID(), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("req_id", postgresql.UUID(), nullable=False),
        sa.Column("session_id", postgresql.UUID(), nullable=False),
        sa.Column("gate_level", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("cycle", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="pending"),
        sa.Column("decision", sa.String(10)),
        sa.Column("reject_reasons", postgresql.JSONB()),
        sa.Column("revision_guidance", sa.Text()),
        sa.Column("reviewer_user_id", sa.String(255)),
        sa.Column("reviewer_name", sa.String(255)),
        sa.Column("reviewed_at", postgresql.TIMESTAMP(timezone=True)),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.create_index("idx_approvals_req", "approvals", ["req_id", "cycle"])
    op.create_foreign_key(
        "fk_approvals_req", "approvals", "requirements",
        ["req_id"], ["id"],
    )

    # ── 9. CHECK constraints (added via raw SQL for complex expressions) ──
    op.create_check_constraint(
        "ck_dialogue_messages_role",
        "dialogue_messages",
        sa.text("role IN ('human', 'ai', 'system')"),
    )
    op.create_check_constraint(
        "ck_event_log_direction",
        "event_log",
        sa.text("direction IN ('IN', 'OUT')"),
    )
    op.create_check_constraint(
        "ck_event_log_outbox",
        "event_log",
        sa.text("direction = 'IN' OR outbox_status IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_approval_decision",
        "approvals",
        sa.text(
            "(status = 'pending' AND decision IS NULL "
            "AND reviewer_user_id IS NULL AND reviewed_at IS NULL) "
            "OR (status = 'decided' AND decision IS NOT NULL "
            "AND reviewer_user_id IS NOT NULL AND reviewed_at IS NOT NULL)"
        ),
    )


def downgrade() -> None:
    # ── Drop new tables in reverse dependency order ───────────────────────
    op.drop_table("approvals")
    op.execute("DROP INDEX IF EXISTS idx_event_log_outbox")
    op.execute("DROP INDEX IF EXISTS idx_event_log_name")
    op.execute("DROP INDEX IF EXISTS idx_event_log_req")
    op.drop_table("event_log")
    op.execute("DROP INDEX IF EXISTS idx_understanding_snapshots_session_cycle")
    op.drop_table("understanding_snapshots")
    op.execute("DROP INDEX IF EXISTS idx_dialogue_messages_session_cycle")
    op.drop_table("dialogue_messages")
    op.drop_table("dialogue_sessions")
    op.execute("DROP INDEX IF EXISTS idx_agent_results_req")
    op.drop_table("agent_results")
    op.execute("DROP INDEX IF EXISTS idx_requirements_status")
    op.drop_table("requirements")

    # ── Restore old tables ────────────────────────────────────────────────
    op.execute("ALTER TABLE IF EXISTS requirements_legacy RENAME TO requirements")
    op.execute("ALTER TABLE IF EXISTS chat_messages_legacy RENAME TO chat_messages")
    op.execute("ALTER TABLE IF EXISTS gate_approvals_legacy RENAME TO gate_approvals")
