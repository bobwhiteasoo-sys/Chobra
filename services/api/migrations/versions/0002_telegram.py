"""Browser-bound Telegram QR sign in and bot polling cursor."""
from alembic import op
from chobra_api.models import TelegramLogin, BotCursor
import os
revision = "0002_telegram"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    for table in (TelegramLogin.__table__, BotCursor.__table__):
        table.create(op.get_bind(), checkfirst=True)
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table.name} TO {os.environ.get('CHOBRA_APP_ROLE', 'chobra_app')}")

def downgrade():
    BotCursor.__table__.drop(op.get_bind())
    TelegramLogin.__table__.drop(op.get_bind())
