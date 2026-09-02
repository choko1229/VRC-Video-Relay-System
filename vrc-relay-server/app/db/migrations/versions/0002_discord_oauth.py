"""discord_idをDiscord OAuthログインの必須識別子として一意制約を追加

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-02

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_users_discord_id", "users", ["discord_id"])


def downgrade() -> None:
    op.drop_constraint("uq_users_discord_id", "users", type_="unique")
