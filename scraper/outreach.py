"""Templated outreach emails through Gmail (drafts by default, or send)."""
import base64
from collections import defaultdict
from datetime import datetime, timezone
from email.message import EmailMessage

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

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


PROGRAM_WORDS = ("program", "degree", "course", "diploma", "certificate", "major", "minor",
                 "bachelor", "master", "ba ", "bsc", "bmus", "ma ", "msc", "mfa", "hnd")


def _program_phrase(programs):
    items = [p.strip() for p in (programs or "").split(";") if p.strip()]
    if not items:
        return "audio program"
    named = any(w in f"{i.lower()} " for i in items[:2] for w in PROGRAM_WORDS)
    if len(items) == 1:
        return items[0] if named else f"{items[0]} program"
    joined = f"{items[0]} and {items[1]}"
    return joined if named else f"{joined} programs"


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


# --- tracking (needs the gmail.readonly permission) ----------------------------

def _search(svc, query):
    return svc.users().messages().list(userId="me", q=query, maxResults=10).execute().get("messages", [])


def _newest_time(svc, messages):
    times = [int(svc.users().messages().get(userId="me", id=m["id"], format="minimal").execute()["internalDate"])
             for m in messages]
    return datetime.fromtimestamp(max(times) / 1000, timezone.utc).isoformat(timespec="seconds")


def check_gmail(conn, log=print):
    """Update contacts whose draft/email is pending. Returns [(contact_id, new_status)]."""
    svc = _service()
    changes = []
    for row in db.pending_outreach(conn):
        cid, email, domain = row["contact_id"], row["email"], row["domain"]
        since = int(datetime.fromisoformat(row["created_at"]).timestamp()) - 60

        if row["outreach_status"] == "Draft created":
            try:
                svc.users().drafts().get(userId="me", id=row["gmail_id"], format="minimal").execute()
                continue  # still sitting in Drafts
            except HttpError as e:
                if e.resp.status != 404:
                    raise
            if _search(svc, f"in:sent to:{email} after:{since}"):
                db.set_outreach_status(conn, cid, "Email sent")
                changes.append((cid, "Email sent"))
            else:
                db.set_outreach_status(conn, cid, "Draft deleted")
                changes.append((cid, "Draft deleted"))
                continue

        if _search(svc, f'from:(mailer-daemon OR postmaster) "{email}" after:{since}'):
            db.set_outreach_status(conn, cid, "Bounced")
            changes.append((cid, "Bounced"))
            continue
        # A reply from the contact, or from anyone else at the school (e.g. they forwarded it).
        replies = _search(svc, f"from:({email} OR {domain}) after:{since} -in:sent")
        if replies:
            db.set_outreach_status(conn, cid, "Replied", reply_at=_newest_time(svc, replies))
            changes.append((cid, "Replied"))
    for cid, status in changes:
        log(f"{db.get_contact(conn, cid)['email']}: {status}")
    return changes
