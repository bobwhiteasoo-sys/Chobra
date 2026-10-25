"""Initial schema: section 17 tables, tenant context functions, row level security, grants.

Revision ID: 0001_initial
Revises:
"""
import os

from alembic import op

from chobra_api.models import RLS_TABLES, Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("CHOBRA_APP_ROLE", "chobra_app")


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_workspace_ids() RETURNS uuid[] LANGUAGE sql STABLE AS $$
          SELECT COALESCE(string_to_array(NULLIF(current_setting('app.workspace_ids', true), ''), ',')::uuid[], ARRAY[]::uuid[])
        $$;
        CREATE OR REPLACE FUNCTION app_user_id() RETURNS uuid LANGUAGE sql STABLE AS $$
          SELECT NULLIF(current_setting('app.user_id', true), '')::uuid
        $$;
        """
    )
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY workspaces_access ON workspaces
          USING (id = ANY(app_workspace_ids()) OR owner_id = app_user_id())
          WITH CHECK (id = ANY(app_workspace_ids()) OR owner_id = app_user_id());
        CREATE POLICY memberships_access ON memberships
          USING (workspace_id = ANY(app_workspace_ids()) OR user_id = app_user_id())
          WITH CHECK (workspace_id = ANY(app_workspace_ids())
                      OR EXISTS (SELECT 1 FROM workspaces w WHERE w.id = workspace_id AND w.owner_id = app_user_id()));
        """
    )
    for table in RLS_TABLES:
        if table in ("workspaces", "memberships"):
            continue
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} USING (workspace_id = ANY(app_workspace_ids())) "
            f"WITH CHECK (workspace_id = ANY(app_workspace_ids()))"
        )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"REVOKE DELETE, UPDATE ON run_events, reward_ledger FROM {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION app_workspace_ids(), app_user_id() TO {APP_ROLE}")


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind)
    op.execute("DROP FUNCTION IF EXISTS app_workspace_ids(); DROP FUNCTION IF EXISTS app_user_id();")
