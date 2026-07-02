"""
A4 Sub-module: DDL Validator

Validates PostgreSQL DDL syntax and semantic constraints.
- Checks DDL syntax using sqlparse
- Validates foreign key references
- Detects circular dependencies
- Reports validation errors with context
"""

import logging
from typing import Tuple, List, Dict, Set, Optional
import re

try:
    import sqlparse
    from sqlparse.sql import IdentifierList, Identifier, Where, Token
    from sqlparse.tokens import Keyword, DML
except ImportError:
    sqlparse = None

logger = logging.getLogger(__name__)


class DDLValidator:
    """Validates PostgreSQL DDL statements for syntax and semantic correctness."""

    def __init__(self):
        self.tables: Dict[str, Dict[str, any]] = {}
        self.foreign_keys: Dict[str, List[Tuple[str, str, str, str]]] = {}  # table -> [(col, ref_table, ref_col, constraint_name)]
        self.errors: List[str] = []

    def validate(self, ddl: str) -> Tuple[bool, List[str]]:
        """
        Validate DDL syntax and semantics.

        Args:
            ddl: DDL statement(s) as string.

        Returns:
            A tuple of (is_valid, error_list).
        """
        self.tables.clear()
        self.foreign_keys.clear()
        self.errors.clear()

        if not ddl or not ddl.strip():
            self.errors.append("Empty DDL string")
            return False, self.errors

        # Check if sqlparse is available
        if sqlparse is None:
            logger.warning("sqlparse not available, performing basic syntax validation")
            return self._basic_syntax_check(ddl)

        try:
            # Parse DDL
            statements = sqlparse.parse(ddl)
            if not statements:
                self.errors.append("No valid SQL statements found")
                return False, self.errors

            # Extract tables and foreign keys from each statement
            for stmt in statements:
                self._extract_table_info(stmt)

            # Validate foreign key references
            self._validate_foreign_keys()

            # Check for circular dependencies
            self._check_circular_dependencies()

            is_valid = len(self.errors) == 0
            return is_valid, self.errors

        except Exception as e:
            logger.error(f"Validation error: {e}")
            self.errors.append(f"Unexpected validation error: {str(e)}")
            return False, self.errors

    def _basic_syntax_check(self, ddl: str) -> Tuple[bool, List[str]]:
        """
        Perform basic syntax validation when sqlparse is unavailable.
        Checks for common DDL patterns and basic errors.
        """
        errors = []

        # Check for balanced parentheses and semicolons
        if ddl.count("(") != ddl.count(")"):
            errors.append("Unbalanced parentheses")

        # Check for CREATE TABLE keyword
        if not re.search(r"CREATE\s+TABLE", ddl, re.IGNORECASE):
            errors.append("No CREATE TABLE statement found")

        # Check for common syntax errors
        if re.search(r";\s*;", ddl):
            errors.append("Double semicolon detected")

        # Check for valid column type patterns
        valid_types = r"(VARCHAR|TEXT|INTEGER|BIGINT|SMALLINT|BOOLEAN|TIMESTAMP|DATE|UUID|JSONB|DECIMAL|NUMERIC|BYTEA|DOUBLE)"
        if not re.search(valid_types, ddl, re.IGNORECASE):
            errors.append("No recognizable SQL data types found")

        is_valid = len(errors) == 0
        return is_valid, errors

    def _extract_table_info(self, stmt: any) -> None:
        """Extract table name, columns, and constraints from a CREATE TABLE statement."""
        stmt_type = self._get_stmt_type(stmt)

        if stmt_type != "CREATE TABLE":
            return

        # Extract table name
        table_name = self._extract_table_name(stmt)
        if not table_name:
            self.errors.append("Could not extract table name from CREATE TABLE")
            return

        self.tables[table_name] = {
            "columns": {},  # column_name -> type
            "primary_keys": [],
            "unique_constraints": [],
        }

        # Extract columns and constraints
        self._extract_columns_and_constraints(stmt, table_name)

    def _get_stmt_type(self, stmt: any) -> str:
        """Determine the type of SQL statement (CREATE TABLE, ALTER TABLE, etc.)."""
        tokens = [t for t in stmt.tokens if not t.is_whitespace]
        if len(tokens) >= 2:
            first = str(tokens[0]).upper()
            second = str(tokens[1]).upper()
            return f"{first} {second}"
        return ""

    def _extract_table_name(self, stmt: any) -> Optional[str]:
        """Extract the table name from a CREATE TABLE statement."""
        tokens = [t for t in stmt.tokens if not t.is_whitespace]
        for i, token in enumerate(tokens):
            if token.ttype is Keyword and str(token).upper() == "TABLE":
                if i + 1 < len(tokens):
                    # Next token should be the table name
                    name_token = tokens[i + 1]
                    return str(name_token).strip('"`[]"')
        return None

    def _extract_columns_and_constraints(self, stmt: any, table_name: str) -> None:
        """Extract column definitions and constraints from CREATE TABLE statement."""
        # Find the parenthesized content
        paren_start = None
        paren_end = None

        for i, token in enumerate(stmt.tokens):
            if str(token) == "(":
                paren_start = i
            elif str(token) == ")" and paren_start is not None:
                paren_end = i
                break

        if paren_start is None or paren_end is None:
            self.errors.append(f"Invalid table definition for {table_name}")
            return

        # Extract content between parentheses
        content = "".join(str(t) for t in stmt.tokens[paren_start + 1 : paren_end])

        # Split by comma (simplified - doesn't handle nested structures perfectly)
        lines = [line.strip() for line in content.split(",") if line.strip()]

        for line in lines:
            if line.upper().startswith("CONSTRAINT"):
                self._parse_constraint(line, table_name)
            elif line.upper().startswith("FOREIGN KEY"):
                self._parse_foreign_key_constraint(line, table_name)
            elif line.upper().startswith("PRIMARY KEY"):
                self._parse_primary_key_constraint(line, table_name)
            elif line.upper().startswith("UNIQUE"):
                self._parse_unique_constraint(line, table_name)
            else:
                self._parse_column_def(line, table_name)

    def _parse_column_def(self, line: str, table_name: str) -> None:
        """Parse a single column definition."""
        tokens = line.split()
        if len(tokens) < 2:
            return

        col_name = tokens[0].strip('"`[]"')
        col_type = tokens[1].upper()

        # Store column info
        if table_name in self.tables:
            self.tables[table_name]["columns"][col_name] = col_type

    def _parse_constraint(self, line: str, table_name: str) -> None:
        """Parse a CONSTRAINT clause (could be PK, FK, or UNIQUE)."""
        if "FOREIGN KEY" in line.upper():
            self._parse_foreign_key_constraint(line, table_name)
        elif "PRIMARY KEY" in line.upper():
            self._parse_primary_key_constraint(line, table_name)
        elif "UNIQUE" in line.upper():
            self._parse_unique_constraint(line, table_name)

    def _parse_foreign_key_constraint(self, line: str, table_name: str) -> None:
        """Parse FOREIGN KEY constraint to extract references."""
        # Pattern: CONSTRAINT name FOREIGN KEY (col) REFERENCES table(col)
        fk_match = re.search(
            r"FOREIGN\s+KEY\s*\(([^)]+)\)\s+REFERENCES\s+([^\s(]+)\s*\(([^)]+)\)",
            line,
            re.IGNORECASE,
        )

        if fk_match:
            col_name = fk_match.group(1).strip('"`[]" ').strip()
            ref_table = fk_match.group(2).strip('"`[]" ').strip()
            ref_col = fk_match.group(3).strip('"`[]" ').strip()

            # Extract constraint name if present
            constraint_match = re.search(r"CONSTRAINT\s+([^\s]+)", line, re.IGNORECASE)
            constraint_name = (
                constraint_match.group(1).strip('"`[]"')
                if constraint_match
                else f"fk_{table_name}_{col_name}"
            )

            if table_name not in self.foreign_keys:
                self.foreign_keys[table_name] = []

            self.foreign_keys[table_name].append(
                (col_name, ref_table, ref_col, constraint_name)
            )

    def _parse_primary_key_constraint(self, line: str, table_name: str) -> None:
        """Parse PRIMARY KEY constraint."""
        pk_match = re.search(r"PRIMARY\s+KEY\s*\(([^)]+)\)", line, re.IGNORECASE)
        if pk_match and table_name in self.tables:
            cols = pk_match.group(1).split(",")
            self.tables[table_name]["primary_keys"] = [
                c.strip('"`[]" ').strip() for c in cols
            ]

    def _parse_unique_constraint(self, line: str, table_name: str) -> None:
        """Parse UNIQUE constraint."""
        unique_match = re.search(r"UNIQUE\s*\(([^)]+)\)", line, re.IGNORECASE)
        if unique_match and table_name in self.tables:
            cols = unique_match.group(1).split(",")
            self.tables[table_name]["unique_constraints"] = [
                c.strip('"`[]" ').strip() for c in cols
            ]

    def _validate_foreign_keys(self) -> None:
        """Validate that all foreign key references point to existing tables and columns."""
        for table_name, fk_list in self.foreign_keys.items():
            for col_name, ref_table, ref_col, constraint_name in fk_list:
                # Check if referenced table exists
                if ref_table not in self.tables:
                    self.errors.append(
                        f"Foreign key {constraint_name} in table {table_name}: "
                        f"referenced table '{ref_table}' does not exist"
                    )
                    continue

                # Check if referenced column exists in referenced table
                if ref_col not in self.tables[ref_table]["columns"]:
                    self.errors.append(
                        f"Foreign key {constraint_name} in table {table_name}: "
                        f"referenced column '{ref_table}.{ref_col}' does not exist"
                    )

    def _check_circular_dependencies(self) -> None:
        """Detect circular foreign key dependencies."""
        # Build adjacency list for dependency graph
        adjacency: Dict[str, Set[str]] = {table: set() for table in self.tables}

        for table_name, fk_list in self.foreign_keys.items():
            for _, ref_table, _, _ in fk_list:
                if ref_table in self.tables:
                    adjacency[table_name].add(ref_table)

        # Check for cycles using DFS
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def has_cycle(node: str, path: List[str]) -> bool:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in adjacency.get(node, set()):
                if neighbor not in visited:
                    if has_cycle(neighbor, path):
                        return True
                elif neighbor in rec_stack:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    cycle = " -> ".join(path[cycle_start:] + [neighbor])
                    self.errors.append(f"Circular foreign key dependency detected: {cycle}")
                    return True

            path.pop()
            rec_stack.remove(node)
            return False

        for table_name in self.tables:
            if table_name not in visited:
                has_cycle(table_name, [])

    def get_table_summary(self) -> Dict[str, any]:
        """Return summary of parsed tables and relationships."""
        return {
            "tables": self.tables,
            "foreign_keys": self.foreign_keys,
            "table_count": len(self.tables),
            "foreign_key_count": sum(len(fks) for fks in self.foreign_keys.values()),
        }
