"""Advanced searches and persistent provider protection. Existing history is preserved."""

from alembic import op
import sqlalchemy as sa

revision = "0002_resilient_search"
down_revision = "0001_initial"


def upgrade():
    for column in [
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("min_nights", sa.Integer, nullable=False, server_default="1"),
        sa.Column("max_nights", sa.Integer, nullable=False, server_default="365"),
        sa.Column("max_duration_minutes", sa.Integer, nullable=True),
        sa.Column("airlines", sa.JSON, nullable=False, server_default="[]"),
        sa.Column(
            "strategy", sa.String(20), nullable=False, server_default="waterfall"
        ),
        sa.Column("provider_names", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("max_combinations", sa.Integer, nullable=False, server_default="12"),
        sa.Column(
            "max_provider_calls", sa.Integer, nullable=False, server_default="30"
        ),
        sa.Column(
            "require_complete_trip",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "allow_experimental", sa.Boolean, nullable=False, server_default=sa.false()
        ),
    ]:
        op.add_column("searches", column)
    op.create_table(
        "provider_states",
        sa.Column("name", sa.String(40), primary_key=True),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("calls", sa.Integer, nullable=False),
        sa.Column("failures", sa.Integer, nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(100)),
    )
    op.create_table(
        "query_cache",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_query_cache_expires_at", "query_cache", ["expires_at"])


def downgrade():
    op.drop_table("query_cache")
    op.drop_table("provider_states")
    for name in [
        "currency",
        "min_nights",
        "max_nights",
        "max_duration_minutes",
        "airlines",
        "strategy",
        "provider_names",
        "max_combinations",
        "max_provider_calls",
        "allow_experimental",
        "require_complete_trip",
    ]:
        op.drop_column("searches", name)
