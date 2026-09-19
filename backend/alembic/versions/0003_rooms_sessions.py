"""0003 rooms and sessions

The seating planner's static inputs (FUTURE_UNIFIED.md §13.4, §15.1, §15.2):

- `rooms` — a physical room as a LIST OF COLUMNS with their own seat counts
  (`seat_columns` JSON), the benches taken out of service (`blocked_seats`
  JSON, 1-based on both axes) and how many candidates share a bench. Real
  rooms are not rectangular: LIBRARY HALL is 3/13/13/4. Capacity is NOT a
  column — §13.1 rule 5, it is derived in `Room.capacity`.
- `exam_sessions` — one centre day-shift, UNIQUE(org_id, date, shift).
- `session_papers` — M:N between a session and the papers sitting in it.

All three carry `org_id NOT NULL` from creation (§13.1 rule 3). No backfill:
these are new tables with no prior data anywhere to derive rows from.

Hand-written in the shape 0002 ended up in after its own review — indexes
created inside `batch_alter_table` (env.py sets render_as_batch for SQLite
globally, so no per-migration handling is needed) and every constraint
explicitly named, since an anonymous constraint cannot be dropped by name on
the way back down.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'rooms',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('building', sa.String(length=200), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('sort_priority', sa.Integer(), nullable=False),
        # [{"label": "Row 1", "seats": 6}, …] — order is the column order.
        sa.Column('seat_columns', sa.JSON(), nullable=False),
        # [{"col": 1, "seat": 4}, …] — 1-based on both axes.
        sa.Column('blocked_seats', sa.JSON(), nullable=False),
        sa.Column('seats_per_bench', sa.Integer(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('rooms', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rooms_org_id'), ['org_id'], unique=False)

    op.create_table(
        'exam_sessions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('shift', sa.String(length=50), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=True),
        sa.Column('end_time', sa.Time(), nullable=True),
        sa.Column('label', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        # [{"student_id", "roll_number", "exam_codes": [...], "acknowledged"}, …]
        # — students enrolled in >=2 papers of this session (§15.2 step 4).
        sa.Column('clashes', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'date', 'shift', name='uq_session_org_date_shift'),
    )
    with op.batch_alter_table('exam_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_exam_sessions_org_id'), ['org_id'], unique=False)

    op.create_table(
        'session_papers',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('offering_id', sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(['offering_id'], ['subject_offerings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['session_id'], ['exam_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'offering_id', name='uq_session_paper'),
    )
    with op.batch_alter_table('session_papers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_session_papers_offering_id'), ['offering_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_session_papers_org_id'), ['org_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_session_papers_session_id'), ['session_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Dropped in reverse dependency order: session_papers references both of
    # the others.
    with op.batch_alter_table('session_papers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_session_papers_session_id'))
        batch_op.drop_index(batch_op.f('ix_session_papers_org_id'))
        batch_op.drop_index(batch_op.f('ix_session_papers_offering_id'))

    op.drop_table('session_papers')
    with op.batch_alter_table('exam_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_exam_sessions_org_id'))

    op.drop_table('exam_sessions')
    with op.batch_alter_table('rooms', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_rooms_org_id'))

    op.drop_table('rooms')
