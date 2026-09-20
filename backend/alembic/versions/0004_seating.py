"""0004 seating plans

The seating planner's output (FUTURE_UNIFIED.md §13.2, §13.4, §15.5):

- `seating_plans` — one versioned allocation of one session's roster, with
  the §15.3 strategy resolved into stored JSON, the seed, and the gaps the
  allocator deliberately left empty to satisfy adjacency. Status is
  draft | published | superseded; publishing freezes the plan and any later
  change is a new version.
- `seating_plan_rooms` — which rooms the plan uses, in order, and which exam
  each room block serves.
- `seat_assignments` — one candidate on one seat, carrying §13.2's two
  UNIQUE constraints: a seat cannot hold two candidates, and a candidate
  cannot sit the same paper twice.

All three carry `org_id NOT NULL` from creation (§13.1 rule 3), including
the join-shaped `seating_plan_rooms` — following the `session_papers` /
`enrollments` precedent, so Gate M's tenant filter only ever adds a WHERE.

`room_id` is ON DELETE RESTRICT, not CASCADE: §15.1 says a room used by a
published plan is deactivated, never deleted, and a cascade would silently
delete the seating chart of an exam that has already been sat.

Hand-written in 0003's shape — indexes created inside `batch_alter_table`
(env.py sets render_as_batch for SQLite globally) and every constraint named
explicitly, since an anonymous one cannot be dropped by name on the way back
down.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'seating_plans',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        # draft | published | superseded (§15.5)
        sa.Column('status', sa.String(length=20), nullable=False),
        # The §15.3 strategy table, resolved — never partial, so a changed
        # default cannot alter an existing plan's meaning.
        sa.Column('strategy', sa.JSON(), nullable=False),
        sa.Column('seed', sa.Integer(), nullable=False),
        # [{"room_id", "col_index", "seat_index", "bench_pos", "reason"}, …]
        sa.Column('gaps', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.String(length=36), nullable=True),
        sa.Column('published_by', sa.String(length=36), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['published_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['session_id'], ['exam_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'version', name='uq_plan_session_version'),
    )
    with op.batch_alter_table('seating_plans', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_seating_plans_org_id'), ['org_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_seating_plans_session_id'), ['session_id'], unique=False)

    op.create_table(
        'seating_plan_rooms',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('plan_id', sa.String(length=36), nullable=False),
        sa.Column('room_id', sa.String(length=36), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        # NULL = this room takes any paper in the session.
        sa.Column('exam_id', sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(['exam_id'], ['exams.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['plan_id'], ['seating_plans.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('plan_id', 'room_id', name='uq_plan_room'),
    )
    with op.batch_alter_table('seating_plan_rooms', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_seating_plan_rooms_org_id'), ['org_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_seating_plan_rooms_plan_id'), ['plan_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_seating_plan_rooms_room_id'), ['room_id'], unique=False)

    op.create_table(
        'seat_assignments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('plan_id', sa.String(length=36), nullable=False),
        sa.Column('room_id', sa.String(length=36), nullable=False),
        # 1-BASED on all three axes, matching Room.blocked_seats and
        # utils/room_capacity.py. No translation layer anywhere.
        sa.Column('col_index', sa.Integer(), nullable=False),
        sa.Column('seat_index', sa.Integer(), nullable=False),
        sa.Column('bench_pos', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.String(length=36), nullable=False),
        sa.Column('offering_id', sa.String(length=36), nullable=False),
        sa.Column('locked', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['offering_id'], ['subject_offerings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['plan_id'], ['seating_plans.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'plan_id', 'room_id', 'col_index', 'seat_index', 'bench_pos',
            name='uq_seat_assignment_seat',
        ),
        sa.UniqueConstraint(
            'plan_id', 'student_id', 'offering_id',
            name='uq_seat_assignment_candidate',
        ),
    )
    with op.batch_alter_table('seat_assignments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_seat_assignments_offering_id'), ['offering_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_seat_assignments_org_id'), ['org_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_seat_assignments_plan_id'), ['plan_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_seat_assignments_room_id'), ['room_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_seat_assignments_student_id'), ['student_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Reverse dependency order: both child tables reference seating_plans.
    with op.batch_alter_table('seat_assignments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_seat_assignments_student_id'))
        batch_op.drop_index(batch_op.f('ix_seat_assignments_room_id'))
        batch_op.drop_index(batch_op.f('ix_seat_assignments_plan_id'))
        batch_op.drop_index(batch_op.f('ix_seat_assignments_org_id'))
        batch_op.drop_index(batch_op.f('ix_seat_assignments_offering_id'))

    op.drop_table('seat_assignments')
    with op.batch_alter_table('seating_plan_rooms', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_seating_plan_rooms_room_id'))
        batch_op.drop_index(batch_op.f('ix_seating_plan_rooms_plan_id'))
        batch_op.drop_index(batch_op.f('ix_seating_plan_rooms_org_id'))

    op.drop_table('seating_plan_rooms')
    with op.batch_alter_table('seating_plans', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_seating_plans_session_id'))
        batch_op.drop_index(batch_op.f('ix_seating_plans_org_id'))

    op.drop_table('seating_plans')
