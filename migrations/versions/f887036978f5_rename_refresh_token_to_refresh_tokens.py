"""rename refresh_token to refresh_tokens

Revision ID: f887036978f5
Revises: 5147ea182851
Create Date: 2026-10-01 20:06:05.725210

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f887036978f5"
down_revision: str | Sequence[str] | None = "5147ea182851"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Written by hand: autogenerate sees a rename as create_table + drop_table,
    # which would delete every row.
    op.rename_table("refresh_token", "refresh_tokens")
    op.execute(
        "ALTER INDEX ix_refresh_token_user_id RENAME TO ix_refresh_tokens_user_id"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "ALTER INDEX ix_refresh_tokens_user_id RENAME TO ix_refresh_token_user_id"
    )
    op.rename_table("refresh_tokens", "refresh_token")
