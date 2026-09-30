"""Templated outreach emails through Gmail (drafts by default, or send)."""
import base64
from collections import defaultdict
from email.message import EmailMessage

from googleapiclient.discovery import build

from . import config, db
from .google_auth import get_credentials

PLACEHOLDERS = {
    "{greeting}": "'Dear Dr. Smith,' / 'Hello Jane,' / 'Hello,' (chosen automatically)",
    "{first_name}": "Contact's first name",
    "{name}": "Contact's full name",
    "{title}": "Contact's job title",
    "{institution}": "School name",
    "{programs}": "Relevant program(s) found",
    "{country}": "School's country",
    "{sender_name}": "Your name (SENDER_NAME in .env)",
}


def _greeting(name, title):
    name = (name or "").strip()
    if not name:
        return "Hello,"
    parts = name.replace(",", " ").split()
    if parts[0].lower().rstrip(".") in ("dr", "prof", "professor"):
        return f"Dear {name},"
    if title and "professor" in title.lower() and len(parts) > 1:
        return f"Dear Professor {parts[-1]},"
    return f"Hello {parts[0]},"


def _program_phrase(programs):
    items = [p.strip() for p in (programs or "").split(";") if p.strip()]
    if not items:
        return "audio program"
    if len(items) == 1:
        return f"{items[0]} program"
    return f"{items[0]} and {items[1]} programs"


def render(template, contact):
    name = (contact.get("name") or "").strip()
    values = defaultdict(str, {
        "greeting": _greeting(name, contact.get("title")),
        "first_name": name.split()[0] if name else "there",
        "name": name,
        "title": contact.get("title") or "",
        "institution": contact.get("institution") or "your school",
        "programs": _program_phrase(contact.get("programs")),
        "country": contact.get("country") or "",
        "sender_name": config.SENDER_NAME,
    })
    return template["subject"].format_map(values), template["body"].format_map(values)


def _service():
    return build("gmail", "v1", credentials=get_credentials(interactive=False), cache_discovery=False)


def connected_account():
    return _service().users().getProfile(userId="me").execute().get("emailAddress")


def _raw(to, subject, body):
    msg = EmailMessage()
    msg["To"] = to
    msg["From"] = config.GMAIL_SENDER
    msg["Subject"] = subject
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def create_draft(conn, contact, subject, body):
    raw = _raw(contact["email"], subject, body)
    draft = _service().users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    db.record_outreach(conn, contact["id"], "draft", draft["id"], subject)
    return draft["id"]


def send(conn, contact, subject, body):
    raw = _raw(contact["email"], subject, body)
    sent = _service().users().messages().send(userId="me", body={"raw": raw}).execute()
    db.record_outreach(conn, contact["id"], "sent", sent["id"], subject)
    return sent["id"]
