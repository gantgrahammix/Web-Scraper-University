"""Settings loaded from .env in the project root."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _get(name, default=""):
    return os.getenv(name, default).strip()


BRAVE_API_KEY = _get("BRAVE_API_KEY")
ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
SCORECARD_API_KEY = _get("SCORECARD_API_KEY")

CLAUDE_MODEL = _get("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = _get("CLAUDE_EFFORT", "low")

GOOGLE_SHEET_ID = _get("GOOGLE_SHEET_ID")
GOOGLE_OAUTH_CLIENT = Path(_get("GOOGLE_OAUTH_CLIENT", str(ROOT / "credentials.json")))
GOOGLE_TOKEN = ROOT / "token.json"

GMAIL_SENDER = _get("GMAIL_SENDER", "javon@naturl.audio")
SENDER_NAME = _get("SENDER_NAME", "Javon")

DB_PATH = Path(_get("DB_PATH", str(ROOT / "data" / "finder.db")))

# Schools scoring below this (0-5) are recorded as "seen" but not saved as leads.
MIN_RELEVANCE = int(_get("MIN_RELEVANCE", "3"))
MAX_PAGES_PER_SCHOOL = int(_get("MAX_PAGES_PER_SCHOOL", "8"))
CRAWL_DELAY_SECONDS = float(_get("CRAWL_DELAY_SECONDS", "1.0"))

USER_AGENT = "NaturlAudioUniversityFinder/1.0 (education partnership research)"
