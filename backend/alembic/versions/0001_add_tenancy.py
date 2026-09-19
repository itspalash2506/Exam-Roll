"""0001 add tenancy

Creates organizations, users, auth_sessions. Adds jobs.org_id (NOT NULL,
indexed) and jobs.created_by.

`Job` gains an owner (P0-4, DECISIONS.md 2026-09-19) — before this, every
job in the database was readable and deletable by anyone who could reach
the API. org_id is added in three steps because existing rows (if any) have
no owner yet: (1) add nullable, (2) backfill into a pilot org created by
this same migration, (3) enforce NOT NULL and index.

The pilot org created here IS the backfill target, not a separate
throwaway "legacy" org plus a real one added later — this app has exactly
one tenant so far, and quarantining pre-auth rows into a second org neither
tracked here nor named anywhere would just be bookkeeping with no present
benefit.

Revision ID: 0001
Revises: 0000
Create Date: 2026-09-19

"""
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = '0000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'organizations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('centre_code', sa.String(50), nullable=True),
        sa.Column('university_name', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('retention_days', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('ai_processing_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        'users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column(
            'org_id', sa.String(36),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('email', sa.String(320), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('role', sa.String(20), nullable=False, server_default='member'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_users_org_id', 'users', ['org_id'])
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    op.create_table(
        'auth_sessions',
        sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column(
            'user_id', sa.String(36),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_auth_sessions_user_id', 'auth_sessions', ['user_id'])
    op.create_index('ix_auth_sessions_expires_at', 'auth_sessions', ['expires_at'])

    # Step 1: add both columns nullable — SQLite supports plain ADD COLUMN
    # natively, no batch mode needed for this part.
    op.add_column('jobs', sa.Column('org_id', sa.String(36), nullable=True))
    op.add_column('jobs', sa.Column('created_by', sa.String(36), nullable=True))

    # Step 2: backfill into a freshly created pilot org.
    pilot_org_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO organizations "
            "(id, name, created_at, retention_days, ai_processing_enabled) "
            "VALUES (:id, :name, :now, 30, :ai_on)"
        ),
        {"id": pilot_org_id, "name": "Pilot centre", "now": now, "ai_on": True},
    )
    conn.execute(
        sa.text("UPDATE jobs SET org_id = :id WHERE org_id IS NULL"),
        {"id": pilot_org_id},
    )

    # Step 3: enforce NOT NULL and add the FK constraints. batch_alter_table
    # is required here (not just for SQLite's sake): SQLite can only add a
    # NOT NULL constraint or a new FK via a create-copy-swap, which is what
    # render_as_batch=True (env.py) makes Alembic emit automatically; on
    # Postgres the same block runs as native in-place ALTER statements.
    with op.batch_alter_table('jobs') as batch_op:
        batch_op.alter_column('org_id', existing_type=sa.String(36), nullable=False)
        batch_op.create_foreign_key(
            'fk_jobs_org_id', 'organizations', ['org_id'], ['id'], ondelete='CASCADE'
        )
        batch_op.create_foreign_key(
            'fk_jobs_created_by', 'users', ['created_by'], ['id'], ondelete='SET NULL'
        )

    op.create_index('ix_jobs_org_id', 'jobs', ['org_id'])
    op.create_index('ix_jobs_org_created', 'jobs', ['org_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_jobs_org_created', table_name='jobs')
    op.drop_index('ix_jobs_org_id', table_name='jobs')

    with op.batch_alter_table('jobs') as batch_op:
        batch_op.drop_constraint('fk_jobs_created_by', type_='foreignkey')
        batch_op.drop_constraint('fk_jobs_org_id', type_='foreignkey')
        batch_op.drop_column('created_by')
        batch_op.drop_column('org_id')

    op.drop_index('ix_auth_sessions_expires_at', table_name='auth_sessions')
    op.drop_index('ix_auth_sessions_user_id', table_name='auth_sessions')
    op.drop_table('auth_sessions')

    op.drop_index('ix_users_email', table_name='users')
    op.drop_index('ix_users_org_id', table_name='users')
    op.drop_table('users')

    op.drop_table('organizations')
