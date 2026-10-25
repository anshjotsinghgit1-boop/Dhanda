import os
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()
DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
OWNER_TELEGRAM_ID = int(os.getenv('OWNER_TELEGRAM_ID', '0') or 0)
if not BOT_TOKEN:
    raise RuntimeError('BOT_TOKEN is missing. Copy .env.example to .env and configure it.')
if not DATABASE_URL:
    raise RuntimeError('DATABASE_URL is missing. Copy .env.example to .env and configure it.')
