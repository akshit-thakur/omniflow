"""Docker diagnostic: report CHECK constraints left NOT VALID by init.sql.

database/init.sql adds domain CHECK constraints to legacy tables as NOT VALID
so they protect new writes immediately, then tries to VALIDATE each one. A
constraint stays NOT VALID only when historical rows violate it; init.sql logs
a PostgreSQL WARNING for each one but does not say which rows are at fault.
This script re-queries pg_constraint for exactly those still-invalid checks
and counts the offending rows so an operator can fix them before running
`ALTER TABLE ... VALIDATE CONSTRAINT ...` in a reviewed maintenance window.
"""

from __future__ import annotations

import sys

from sqlalchemy import text

from scripts.startup.run_migrations import build_database_url, create_engine


def find_invalid_check_constraints(engine) -> list[tuple[str, str, str]]:
    """Return (table_name, constraint_name, check_expression) for each
    convalidated=false CHECK constraint in the public schema."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT relname, conname, pg_get_constraintdef(pg_constraint.oid)
                  FROM pg_constraint
                  JOIN pg_class ON pg_class.oid = pg_constraint.conrelid
                  JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace
                 WHERE pg_namespace.nspname = 'public'
                   AND contype = 'c'
                   AND NOT convalidated
                 ORDER BY relname, conname
                """
            )
        ).all()
    return [(row[0], row[1], row[2]) for row in rows]


def _check_expression(constraint_def: str) -> str:
    # pg_get_constraintdef returns "CHECK (<expr>)"; VALIDATE re-derives it,
    # this only needs the inner predicate to count violating rows.
    prefix, suffix = "CHECK (", ")"
    if not (constraint_def.startswith(prefix) and constraint_def.endswith(suffix)):
        raise ValueError(f"Unexpected constraint definition: {constraint_def}")
    return constraint_def[len(prefix) : -len(suffix)]


def count_violations(engine, table_name: str, check_expression: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(
                    f'SELECT count(*) FROM "{table_name}" WHERE NOT ({check_expression})'
                )
            ).scalar_one()
        )


def main() -> int:
    engine = create_engine(build_database_url())
    try:
        invalid = find_invalid_check_constraints(engine)
        if not invalid:
            print("All CHECK constraints are validated.")
            return 0

        print(f"{len(invalid)} CHECK constraint(s) remain NOT VALID:\n")
        exit_code = 0
        for table_name, constraint_name, constraint_def in invalid:
            expression = _check_expression(constraint_def)
            violations = count_violations(engine, table_name, expression)
            print(f"  {table_name}.{constraint_name}: {constraint_def}")
            if violations:
                print(f"    {violations} row(s) currently violate it")
                exit_code = 1
            else:
                print(
                    "    0 rows violate it now; run "
                    f'ALTER TABLE "{table_name}" VALIDATE CONSTRAINT "{constraint_name}" '
                    "to close it out"
                )
        return exit_code
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
