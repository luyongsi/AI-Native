"""009_stage_two_schema

Revision: 009
Create Date: 2026-07-13

Stage 2 (A3/A4/A5/Gate1) schema per design docs v1.1 + data dictionary v1.3.

Adds:
  - prototype_artifacts table (A3 managed, versioned prototype storage)
  - design_specs table (A4 managed, versioned spec/OpenAPI/ERD/DDL storage)
  - api_schemas table (A4 managed, versioned API schema storage)
  - erd_designs table (A4 managed, versioned ERD design storage)
  - requirements column extensions (phase, design_status, design_revision_count, spec)

Modifies:
  - approvals: add a3_rework column (Gate1 only)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Extend requirements table ─────────────────────────────────────
    op.add_column("requirements",
                  sa.Column("phase", sa.String(20),
                            server_default="requirement"))
    op.add_column("requirements",
                  sa.Column("design_status", sa.String(30)))
    op.add_column("requirements",
                  sa.Column("design_revision_count", sa.Integer(),
                            server_default=sa.text("0")))
    op.add_column("requirements",
                  sa.Column("spec", postgresql.JSONB()))

    op.create_index("idx_requirements_phase", "requirements", ["phase"])
    op.create_index("idx_requirements_design_status", "requirements",
                    ["design_status"])

    # ── 2. Extend approvals table (a3_rework for Gate1) ──────────────────
    op.add_column("approvals",
                  sa.Column("a3_rework", sa.Boolean(),
                            server_default=sa.text("false")))

    # ── 3. prototype_artifacts table (A3 managed) ────────────────────────
    op.create_table(
        "prototype_artifacts",
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("req_id", postgresql.UUID(), nullable=False),
        sa.Column("cycle", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("version", sa.Integer(), nullable=False,
                  server_default=sa.text("1")),
        sa.Column("prototype_url", sa.Text()),
        sa.Column("html_content", sa.Text()),
        sa.Column("screens", postgresql.JSONB(),
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("annotations", postgresql.JSONB(),
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(20),
                  server_default="draft"),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.create_unique_constraint(
        "uq_prototype_artifacts_req_cycle_version",
        "prototype_artifacts", ["req_id", "cycle", "version"],
    )
    op.create_index(
        "idx_prototype_artifacts_req",
        "prototype_artifacts",
        ["req_id", "cycle", sa.text("version DESC")],
    )
    op.create_foreign_key(
        "fk_prototype_artifacts_req", "prototype_artifacts",
        "requirements", ["req_id"], ["id"],
    )

    # ── 4. design_specs table (A4 managed) ───────────────────────────────
    op.create_table(
        "design_specs",
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("req_id", postgresql.UUID(), nullable=False),
        sa.Column("cycle", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("version", sa.Integer(), nullable=False,
                  server_default=sa.text("1")),
        sa.Column("spec_doc", postgresql.JSONB()),
        sa.Column("openapi_schema", postgresql.JSONB()),
        sa.Column("erd_diagram", postgresql.JSONB()),
        sa.Column("ddl_statements", sa.Text()),
        sa.Column("quality_score", sa.Numeric(3, 2)),
        sa.Column("source", sa.String(20), server_default="llm"),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.create_unique_constraint(
        "uq_design_specs_req_cycle_version",
        "design_specs", ["req_id", "cycle", "version"],
    )
    op.create_index(
        "idx_design_specs_req",
        "design_specs",
        ["req_id", "cycle", sa.text("version DESC")],
    )
    op.create_foreign_key(
        "fk_design_specs_req", "design_specs",
        "requirements", ["req_id"], ["id"],
    )

    # ── 5. api_schemas table (A4 managed, versioned) ─────────────────────
    op.create_table(
        "api_schemas",
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("req_id", postgresql.UUID(), nullable=False),
        sa.Column("schema_json", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False,
                  server_default=sa.text("1")),
        sa.Column("validation_passed", sa.Boolean(),
                  server_default=sa.text("false")),
        sa.Column("validation_log", postgresql.JSONB(),
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("source", sa.String(20), server_default="llm"),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.create_index("idx_api_schemas_req", "api_schemas",
                    ["req_id", sa.text("version DESC")])
    op.create_foreign_key(
        "fk_api_schemas_req", "api_schemas",
        "requirements", ["req_id"], ["id"],
    )

    # ── 6. erd_designs table (A4 managed, versioned) ─────────────────────
    op.create_table(
        "erd_designs",
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("req_id", postgresql.UUID(), nullable=False),
        sa.Column("erd_mermaid", sa.Text()),
        sa.Column("ddl", sa.Text()),
        sa.Column("entities", postgresql.JSONB(),
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("relationships", postgresql.JSONB(),
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("validation_passed", sa.Boolean(),
                  server_default=sa.text("false")),
        sa.Column("validation_errors", postgresql.JSONB(),
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_incremental", sa.Boolean(),
                  server_default=sa.text("false")),
        sa.Column("existing_tables", postgresql.JSONB(),
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("version", sa.Integer(), nullable=False,
                  server_default=sa.text("1")),
        sa.Column("source", sa.String(20), server_default="llm"),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.create_index("idx_erd_designs_req", "erd_designs",
                    ["req_id", sa.text("version DESC")])
    op.create_foreign_key(
        "fk_erd_designs_req", "erd_designs",
        "requirements", ["req_id"], ["id"],
    )

    # ── 7. CHECK constraints ─────────────────────────────────────────────
    op.create_check_constraint(
        "ck_prototype_artifacts_status",
        "prototype_artifacts",
        sa.text("status IN ('draft', 'confirmed')"),
    )
    op.create_check_constraint(
        "ck_design_specs_quality_score",
        "design_specs",
        sa.text("quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1)"),
    )


def downgrade() -> None:
    op.drop_table("erd_designs")
    op.drop_table("api_schemas")
    op.drop_table("design_specs")
    op.drop_table("prototype_artifacts")

    op.execute("ALTER TABLE approvals DROP COLUMN IF EXISTS a3_rework")

    op.execute("DROP INDEX IF EXISTS idx_requirements_design_status")
    op.execute("DROP INDEX IF EXISTS idx_requirements_phase")
    op.execute("ALTER TABLE requirements DROP COLUMN IF EXISTS spec")
    op.execute("ALTER TABLE requirements DROP COLUMN IF EXISTS design_revision_count")
    op.execute("ALTER TABLE requirements DROP COLUMN IF EXISTS design_status")
    op.execute("ALTER TABLE requirements DROP COLUMN IF EXISTS phase")
