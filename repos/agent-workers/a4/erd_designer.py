"""
A4 Sub-module: ERD Designer

Designs entity-relationship diagrams and generates DDL statements from
entity and relationship definitions.

In production, this would:
  1. Accept structured entity/relationship output from A2 (Knowledge Analyst).
  2. Use domain-driven heuristics to infer cardinality and foreign-key placement.
  3. Generate database-agnostic DDL (with dialect overrides for PG/MySQL/SQLite).
  4. Validate against SQL linters (e.g. sqlfluff) before final emission.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Type mapping: logical type -> SQL column type
_TYPE_TO_SQL: Dict[str, str] = {
    "string": "VARCHAR(255)",
    "text": "TEXT",
    "uuid": "UUID",
    "integer": "INTEGER",
    "bigint": "BIGINT",
    "number": "DECIMAL(12,2)",
    "float": "DOUBLE PRECISION",
    "boolean": "BOOLEAN",
    "datetime": "TIMESTAMP WITH TIME ZONE",
    "date": "DATE",
    "json": "JSONB",
    "jsonb": "JSONB",
    "enum": "VARCHAR(50)",
    "blob": "BYTEA",
}


class ERDDesigner:
    """Designs ERDs and emits DDL from entity + relationship definitions."""

    # Default columns added to every table
    _DEFAULT_COLUMNS: List[Dict[str, Any]] = [
        {"name": "id", "type": "uuid", "nullable": False, "primary_key": True},
        {"name": "created_at", "type": "datetime", "nullable": False},
        {"name": "updated_at", "type": "datetime", "nullable": False},
    ]

    def __init__(self, dialect: str = "postgresql"):
        """Args:
            dialect: Target SQL dialect ('postgresql', 'mysql', 'sqlite').
        """
        self.dialect = dialect
        logger.debug("ERDDesigner initialized with dialect=%s", dialect)

    async def design(
        self,
        entities: list,
        relationships: list,
        *,
        schema_name: Optional[str] = None,
    ) -> dict:
        """Design ERD from entities and relationships.

        Args:
            entities: List of entity dicts, each with:
                - name (str): table name
                - attributes (list, optional): [{name, type, nullable, primary_key}]
            relationships: List of relationship dicts, each with:
                - from (str): source entity name
                - to (str): target entity name
                - type (str): 'one_to_one', 'one_to_many', or 'many_to_many'
                - foreign_key (str, optional): explicit FK column name

        Returns:
            Dict with:
                - tables: list of {name, columns[{name, type, nullable, primary_key, foreign_key}], indexes[]}
                - ddl: str containing CREATE TABLE statements
        """
        parsed_entities = self._parse_entities(entities)
        parsed_relationships = self._parse_relationships(relationships)

        logger.info(
            "Designing ERD: entities=%d, relationships=%d, dialect=%s",
            len(parsed_entities),
            len(parsed_relationships),
            self.dialect,
        )

        # Build tables with inferred foreign keys from relationships
        tables, junction_tables = self._build_tables(
            parsed_entities, parsed_relationships
        )

        # Build indexes (primary keys + inferred indexes on FKs and lookups)
        tables = self._build_indexes(tables)

        # Generate DDL
        ddl = self._generate_ddl(tables, junction_tables, schema_name)

        result: Dict[str, Any] = {
            "tables": tables + junction_tables,
            "ddl": ddl,
            "dialect": self.dialect,
            "entity_count": len(parsed_entities),
            "relationship_count": len(parsed_relationships),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info("ERD designed: %d tables, %d DDL statements", len(result["tables"]), ddl.count("CREATE TABLE"))
        return result

    # ---- Parsing ----

    def _parse_entities(self, entities: list) -> List[Dict[str, Any]]:
        """Normalize entity definitions from various input shapes."""
        parsed: List[Dict[str, Any]] = []
        for ent in entities:
            if isinstance(ent, str):
                parsed.append({"name": ent, "attributes": []})
            elif isinstance(ent, dict):
                name = ent.get("name") or ent.get("entity") or ent.get("table", "unknown")
                attrs = ent.get("attributes") or ent.get("fields") or ent.get("columns") or []
                parsed.append({"name": str(name), "attributes": list(attrs)})
        return parsed or [
            {"name": "items", "attributes": [{"name": "name", "type": "string"}]},
        ]

    def _parse_relationships(self, relationships: list) -> List[Dict[str, Any]]:
        """Normalize relationship definitions, inferring type if missing."""
        parsed: List[Dict[str, Any]] = []
        for rel in relationships:
            if not isinstance(rel, dict):
                continue
            from_ent = rel.get("from") or rel.get("source") or rel.get("parent")
            to_ent = rel.get("to") or rel.get("target") or rel.get("child")
            if not from_ent or not to_ent:
                continue
            rel_type = rel.get("type", "one_to_many")
            parsed.append({
                "from": str(from_ent),
                "to": str(to_ent),
                "type": rel_type,
                "foreign_key": rel.get("foreign_key") or rel.get("fk"),
            })
        return parsed

    # ---- Table & column construction ----

    def _build_tables(
        self,
        entities: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
    ) -> tuple:
        """Build table definitions with inferred FK columns from relationships."""
        tables: Dict[str, Dict[str, Any]] = {}
        junction_tables: List[Dict[str, Any]] = []

        # Seed tables from entities
        for ent in entities:
            name = ent["name"]
            columns = list(self._DEFAULT_COLUMNS)

            # Add user-defined columns (skip id if user already defines it)
            for attr in ent.get("attributes", []):
                col_name = attr.get("name", "")
                if col_name in ("id", "created_at", "updated_at"):
                    continue
                columns.append({
                    "name": col_name,
                    "type": attr.get("type", "string"),
                    "nullable": attr.get("nullable", False),
                    "primary_key": attr.get("primary_key", False),
                    "foreign_key": attr.get("foreign_key"),
                })

            tables[name] = {"name": name, "columns": columns}

        # Apply relationships to add FK columns
        for rel in relationships:
            from_name = rel["from"]
            to_name = rel["to"]
            rel_type = rel["type"]

            if rel_type == "many_to_many":
                # Create junction table
                jt_name = f"{from_name}_{to_name}"
                jt_columns = [
                    {"name": "id", "type": "uuid", "nullable": False, "primary_key": True},
                    {
                        "name": f"{from_name}_id",
                        "type": "uuid",
                        "nullable": False,
                        "primary_key": False,
                        "foreign_key": f"{from_name}.id",
                    },
                    {
                        "name": f"{to_name}_id",
                        "type": "uuid",
                        "nullable": False,
                        "primary_key": False,
                        "foreign_key": f"{to_name}.id",
                    },
                    {"name": "created_at", "type": "datetime", "nullable": False},
                ]
                junction_tables.append({"name": jt_name, "columns": jt_columns})
            elif rel_type in ("one_to_many",):
                # Add FK to the "many" side (the 'to' table)
                if to_name in tables:
                    fk_col_name = rel.get("foreign_key") or f"{from_name}_id"
                    # Avoid duplicates
                    existing = {c["name"] for c in tables[to_name]["columns"]}
                    if fk_col_name not in existing:
                        tables[to_name]["columns"].append({
                            "name": fk_col_name,
                            "type": "uuid",
                            "nullable": True,
                            "primary_key": False,
                            "foreign_key": f"{from_name}.id",
                        })
            elif rel_type == "one_to_one":
                # FK on either side; default to the 'to' side
                if to_name in tables:
                    fk_col_name = f"{from_name}_id"
                    existing = {c["name"] for c in tables[to_name]["columns"]}
                    if fk_col_name not in existing:
                        tables[to_name]["columns"].append({
                            "name": fk_col_name,
                            "type": "uuid",
                            "nullable": True,
                            "primary_key": False,
                            "foreign_key": f"{from_name}.id",
                            "unique": True,
                        })

        return list(tables.values()), junction_tables

    def _build_indexes(self, tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Add index definitions for PKs, FKs, and common lookup columns."""
        for table in tables:
            indexes: List[Dict[str, Any]] = []
            for col in table["columns"]:
                if col.get("primary_key"):
                    # Primary key index is implicit but we record it
                    indexes.append({
                        "name": f"pk_{table['name']}",
                        "columns": [col["name"]],
                        "unique": True,
                        "type": "PRIMARY KEY",
                    })
                if col.get("foreign_key"):
                    indexes.append({
                        "name": f"idx_{table['name']}_{col['name']}",
                        "columns": [col["name"]],
                        "unique": False,
                        "type": "BTREE",
                    })
                # Auto-index status columns (common lookup pattern)
                if col["name"] in ("status", "type", "email", "name"):
                    has_fk_idx = any(
                        idx["columns"] == [col["name"]] for idx in indexes
                    )
                    if not has_fk_idx:
                        indexes.append({
                            "name": f"idx_{table['name']}_{col['name']}",
                            "columns": [col["name"]],
                            "unique": col["name"] == "email",
                            "type": "BTREE",
                        })
            table["indexes"] = indexes
        return tables

    # ---- DDL generation ----

    def _generate_ddl(
        self,
        tables: List[Dict[str, Any]],
        junction_tables: List[Dict[str, Any]],
        schema_name: Optional[str],
    ) -> str:
        """Generate CREATE TABLE DDL for all tables."""
        statements: List[str] = []
        header = (
            f"-- DDL generated by A4 ERD Designer\n"
            f"-- Dialect: {self.dialect}\n"
            f"-- Generated: {datetime.now(timezone.utc).isoformat()}\n"
        )
        statements.append(header)

        if schema_name:
            statements.append(f"CREATE SCHEMA IF NOT EXISTS {self._quote(schema_name)};\n")

        all_tables = list(tables) + list(junction_tables)
        for table in all_tables:
            stmt = self._build_create_table(table, schema_name)
            statements.append(stmt)

        return "\n".join(statements)

    def _build_create_table(
        self,
        table: Dict[str, Any],
        schema_name: Optional[str] = None,
    ) -> str:
        """Build a single CREATE TABLE statement."""
        tname = table["name"]
        full_name = f"{schema_name}.{self._quote(tname)}" if schema_name else self._quote(tname)

        lines = [f"CREATE TABLE {full_name} ("]
        col_defs: List[str] = []
        for col in table["columns"]:
            sql_type = _TYPE_TO_SQL.get(col["type"], "TEXT")
            parts = [self._quote(col["name"]), sql_type]

            if col.get("nullable") is False:
                parts.append("NOT NULL")
            elif col.get("nullable") is True:
                parts.append("NULL")

            if col.get("primary_key"):
                parts.append("PRIMARY KEY")
            if col.get("unique"):
                parts.append("UNIQUE")

            col_defs.append("    " + " ".join(parts))

        # Add explicit constraints for FKs
        constraints: List[str] = []
        for col in table["columns"]:
            fk = col.get("foreign_key")
            if fk:
                ref_table, ref_col = fk.split(".", 1)
                ref_full = (
                    f"{schema_name}.{self._quote(ref_table)}"
                    if schema_name
                    else self._quote(ref_table)
                )
                constraints.append(
                    f"    CONSTRAINT fk_{tname}_{col['name']} "
                    f"FOREIGN KEY ({self._quote(col['name'])}) "
                    f"REFERENCES {ref_full}({self._quote(ref_col)})"
                )

        lines.append(",\n".join(col_defs + constraints))
        lines.append(");")
        return "\n".join(lines)

    @staticmethod
    def _quote(identifier: str) -> str:
        """Quote an identifier for the current dialect."""
        return f'"{identifier}"'
