"""Grant least-privilege access to the separate API and AI runtime roles."""

import os

from alembic import op

revision = "009_separate_runtime_roles"
down_revision = "008_add_ai_action_approval"
branch_labels = None
depends_on = None


def _ident(value: str) -> str:
    if not value or len(value) > 63 or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for char in value):
        raise RuntimeError("Runtime role names must be simple PostgreSQL identifiers")
    return f'"{value}"'


def upgrade() -> None:
    api = os.getenv("DATABASE_RUNTIME_USER", "omniflow_api")
    ai = os.getenv("AI_RUNTIME_USER", "omniflow_ai")
    api_ident = _ident(api)
    ai_ident = _ident(ai)
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {api_ident}, {ai_ident}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {api_ident}")
    op.execute(f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {api_ident}")
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {ai_ident}")
    op.execute(f"REVOKE ALL ON TABLE ai_action_requests, ai_action_proposals, ai_mutation_audit FROM {ai_ident}")
    op.execute(f"GRANT INSERT, UPDATE, DELETE ON TABLE ai_entity_embeddings TO {ai_ident}")
    op.execute(f"GRANT USAGE, SELECT, UPDATE ON SEQUENCE ai_entity_embeddings_id_seq TO {ai_ident}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {api_ident}"
    )
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {api_ident}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {ai_ident}")
    op.execute("ALTER TABLE ai_action_requests ADD COLUMN IF NOT EXISTS review JSONB")
    op.execute("ALTER TABLE ai_action_requests ADD COLUMN IF NOT EXISTS review_digest TEXT")
    op.execute("ALTER TABLE ai_action_requests ADD COLUMN IF NOT EXISTS decided_by TEXT")


def downgrade() -> None:
    api = _ident(os.getenv("DATABASE_RUNTIME_USER", "omniflow_api"))
    ai = _ident(os.getenv("AI_RUNTIME_USER", "omniflow_ai"))
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {api}, {ai}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {api}, {ai}")
