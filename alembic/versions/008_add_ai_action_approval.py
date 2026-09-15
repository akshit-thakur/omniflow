"""add durable AI action approval workflow

Revision ID: 008_add_ai_action_approval
Revises: 007_harden_domain_constraints
Create Date: 2026-08-29
"""

from alembic import op

revision = "008_add_ai_action_approval"
down_revision = "007_harden_domain_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE IF NOT EXISTS ai_action_requests (
             request_id UUID PRIMARY KEY,
             status TEXT NOT NULL DEFAULT 'pending',
             context JSONB NOT NULL DEFAULT '{}'::jsonb,
             proposed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
             decided_at TIMESTAMPTZ,
             CONSTRAINT chk_ai_action_requests_status
               CHECK (status IN ('pending', 'committed', 'rejected')),
             CONSTRAINT chk_ai_action_requests_context_object
               CHECK (jsonb_typeof(context) = 'object'),
             CONSTRAINT chk_ai_action_requests_decision
               CHECK ((status = 'pending' AND decided_at IS NULL)
                  OR (status IN ('committed', 'rejected') AND decided_at IS NOT NULL))
           )"""
    )
    op.execute(
        """CREATE TABLE IF NOT EXISTS ai_action_proposals (
             request_id UUID NOT NULL REFERENCES ai_action_requests(request_id) ON DELETE CASCADE,
             action_index INTEGER NOT NULL,
             action TEXT NOT NULL,
             arguments JSONB NOT NULL DEFAULT '{}'::jsonb,
             PRIMARY KEY (request_id, action_index),
             CONSTRAINT chk_ai_action_proposals_index CHECK (action_index >= 0),
             CONSTRAINT chk_ai_action_proposals_action
               CHECK (char_length(btrim(action)) BETWEEN 1 AND 100),
             CONSTRAINT chk_ai_action_proposals_arguments_object
               CHECK (jsonb_typeof(arguments) = 'object')
           )"""
    )
    op.execute(
        """CREATE INDEX IF NOT EXISTS idx_ai_action_requests_pending
           ON ai_action_requests(proposed_at DESC) WHERE status = 'pending'"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_action_proposals")
    op.execute("DROP TABLE IF EXISTS ai_action_requests")
