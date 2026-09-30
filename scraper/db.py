"""SQLite storage. This is the tool's memory: every domain it has ever looked at
is recorded in `seen_domains`, so later searches never process a school twice."""
import sqlite3
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS keywords (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword   TEXT NOT NULL COLLATE NOCASE,
    region    TEXT NOT NULL DEFAULT '' COLLATE NOCASE,  -- '' = searched in every region
    language  TEXT NOT NULL DEFAULT '',
    note      TEXT NOT NULL DEFAULT '',                  -- e.g. English meaning of a local term
    source    TEXT NOT NULL DEFAULT 'user',              -- user | suggested
    active    INTEGER NOT NULL DEFAULT 1,
    added_at  TEXT NOT NULL,
    UNIQUE(keyword, region)
);
CREATE TABLE IF NOT EXISTS regions (
    region    TEXT PRIMARY KEY COLLATE NOCASE,
    active    INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS queries_run (
    query        TEXT PRIMARY KEY COLLATE NOCASE,
    run_at       TEXT NOT NULL,
    result_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS seen_domains (
    domain    TEXT PRIMARY KEY,
    outcome   TEXT NOT NULL,          -- saved | not_relevant | error | blocked
    reason    TEXT,
    last_url  TEXT,
    attempts  INTEGER NOT NULL DEFAULT 1,
    seen_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS institutions (
    domain          TEXT PRIMARY KEY,
    name            TEXT,
    country         TEXT,
    city            TEXT,
    website         TEXT,
    programs        TEXT,
    relevance       INTEGER,
    relevance_reason TEXT,
    enrollment      INTEGER,
    enrollment_source TEXT,
    size_category   TEXT,
    tuition         REAL,
    tuition_currency TEXT,
    tuition_note    TEXT,
    tuition_band    TEXT,
    control         TEXT,
    found_via       TEXT,
    found_at        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'New',
    notes           TEXT DEFAULT '',
    synced          INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    domain      TEXT NOT NULL REFERENCES institutions(domain),
    name        TEXT,
    title       TEXT,
    role        TEXT,
    priority    INTEGER,
    email       TEXT,
    phone       TEXT,
    source_url  TEXT,
    outreach_status TEXT NOT NULL DEFAULT 'Not contacted',
    last_contacted_at TEXT,
    last_reply_at TEXT,
    synced      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(domain, email, name)
);
CREATE TABLE IF NOT EXISTS templates (
    name     TEXT PRIMARY KEY,
    subject  TEXT NOT NULL,
    body     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outreach (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id  INTEGER NOT NULL REFERENCES contacts(id),
    kind        TEXT NOT NULL,        -- draft | sent
    gmail_id    TEXT,                 -- draft id for drafts, message id for sends
    subject     TEXT,
    created_at  TEXT NOT NULL
);
"""

DEFAULT_KEYWORDS = [
    "audio engineering degree",
    "music production program",
    "sound design degree",
    "foley course",
    "audio post-production program",
    "mixing and mastering course",
    "music technology degree",
    "recording arts program",
    "sound for film and television degree",
    "audio production bachelor",
]

DEFAULT_REGIONS = [
    "USA", "Canada", "UK", "Ireland", "Germany", "Netherlands", "France",
    "Sweden", "Australia", "New Zealand", "Japan", "South Korea",
    "Brazil", "Mexico", "South Africa",
]

DEFAULT_TEMPLATE = {
    "name": "Partnership intro",
    "subject": "Naturl Audio x {institution}: AL-1 Limiter for your audio program",
    "body": """{greeting}

My name is {sender_name} and I'm with Naturl Audio. I came across {institution}'s {programs} and wanted to reach out about a possible education partnership.

We make the AL-1 Limiter, and we'd love to explore getting it into the hands of your students and faculty as part of the curriculum, whether that's in the studio, in mixing and mastering coursework, or in post-production.

Would you be open to a short call in the next couple of weeks? If someone else at {institution} handles partnerships or equipment decisions, I'd really appreciate being pointed in the right direction.

Thank you for your time,
{sender_name}
Naturl Audio
""",
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path=None):
    path = path or config.DB_PATH
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _seed(conn)
    return conn


def _seed(conn):
    if conn.execute("SELECT COUNT(*) FROM keywords").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO keywords (keyword, added_at) VALUES (?, ?)",
            [(k, now()) for k in DEFAULT_KEYWORDS],
        )
    if conn.execute("SELECT COUNT(*) FROM regions").fetchone()[0] == 0:
        conn.executemany("INSERT INTO regions (region) VALUES (?)", [(r,) for r in DEFAULT_REGIONS])
    if conn.execute("SELECT COUNT(*) FROM templates").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO templates (name, subject, body) VALUES (:name, :subject, :body)",
            DEFAULT_TEMPLATE,
        )
    conn.commit()


# --- keywords & regions -------------------------------------------------------

def list_keywords(conn, active_only=False, region=None):
    """region=None: all keywords. region='' : only keywords used everywhere.
    region='Germany': only keywords specific to Germany."""
    sql, args = "SELECT * FROM keywords WHERE 1=1", []
    if active_only:
        sql += " AND active = 1"
    if region is not None:
        sql += " AND region = ?"
        args.append(region)
    sql += " ORDER BY region, added_at, keyword"
    return [dict(r) for r in conn.execute(sql, args)]


def add_keyword(conn, keyword, region="", language="", note="", source="user"):
    keyword = keyword.strip()
    if not keyword:
        return False
    cur = conn.execute(
        """INSERT OR IGNORE INTO keywords (keyword, region, language, note, source, added_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (keyword, (region or "").strip(), language, note, source, now()),
    )
    conn.commit()
    return cur.rowcount == 1


def set_keyword_active(conn, keyword_id, active):
    conn.execute("UPDATE keywords SET active = ? WHERE id = ?", (int(active), keyword_id))
    conn.commit()


def delete_keyword(conn, keyword_id):
    conn.execute("DELETE FROM keywords WHERE id = ?", (keyword_id,))
    conn.commit()


def find_keyword_id(conn, keyword, region=""):
    r = conn.execute("SELECT id FROM keywords WHERE keyword = ? AND region = ?", (keyword, region)).fetchone()
    return r["id"] if r else None


def list_regions(conn, active_only=False):
    sql = "SELECT * FROM regions" + (" WHERE active = 1" if active_only else "") + " ORDER BY region"
    return [dict(r) for r in conn.execute(sql)]


def add_region(conn, region):
    region = region.strip()
    if not region:
        return False
    cur = conn.execute("INSERT OR IGNORE INTO regions (region) VALUES (?)", (region,))
    conn.commit()
    return cur.rowcount == 1


def set_region_active(conn, region, active):
    conn.execute("UPDATE regions SET active = ? WHERE region = ?", (int(active), region))
    conn.commit()


# --- queries & seen domains ---------------------------------------------------

def query_already_run(conn, query):
    return conn.execute("SELECT 1 FROM queries_run WHERE query = ?", (query,)).fetchone() is not None


def record_query(conn, query, result_count):
    conn.execute(
        "INSERT OR REPLACE INTO queries_run (query, run_at, result_count) VALUES (?, ?, ?)",
        (query, now(), result_count),
    )
    conn.commit()


def domain_status(conn, domain):
    r = conn.execute("SELECT * FROM seen_domains WHERE domain = ?", (domain,)).fetchone()
    return dict(r) if r else None


def domain_seen(conn, domain):
    return domain_status(conn, domain) is not None


def mark_domain_seen(conn, domain, outcome, reason="", url=None):
    conn.execute(
        """INSERT INTO seen_domains (domain, outcome, reason, last_url, attempts, seen_at)
           VALUES (?, ?, ?, ?, 1, ?)
           ON CONFLICT(domain) DO UPDATE SET outcome = excluded.outcome, reason = excluded.reason,
               last_url = excluded.last_url, attempts = attempts + 1, seen_at = excluded.seen_at""",
        (domain, outcome, reason, url, now()),
    )
    conn.commit()


def forget_domain(conn, domain):
    """Allow a domain to be processed again (e.g. after a crawl error)."""
    conn.execute("DELETE FROM seen_domains WHERE domain = ?", (domain,))
    conn.commit()


def list_seen(conn, outcome=None):
    if outcome:
        rows = conn.execute("SELECT * FROM seen_domains WHERE outcome = ? ORDER BY seen_at DESC", (outcome,))
    else:
        rows = conn.execute("SELECT * FROM seen_domains ORDER BY seen_at DESC")
    return [dict(r) for r in rows]


# --- institutions & contacts --------------------------------------------------

INSTITUTION_FIELDS = [
    "domain", "name", "country", "city", "website", "programs", "relevance",
    "relevance_reason", "enrollment", "enrollment_source", "size_category",
    "tuition", "tuition_currency", "tuition_note", "tuition_band", "control",
    "found_via",
]


def save_institution(conn, inst, contacts):
    row = {f: inst.get(f) for f in INSTITUTION_FIELDS}
    row["found_at"] = now()
    cols = ", ".join(row)
    params = ", ".join(f":{c}" for c in row)
    conn.execute(f"INSERT OR IGNORE INTO institutions ({cols}) VALUES ({params})", row)
    for c in contacts:
        conn.execute(
            """INSERT OR IGNORE INTO contacts
               (domain, name, title, role, priority, email, phone, source_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (inst["domain"], c.get("name") or "", c.get("title") or "", c.get("role") or "",
             c.get("priority"), c.get("email") or "", c.get("phone") or "", c.get("source_url") or ""),
        )
    conn.commit()


def list_institutions(conn):
    rows = conn.execute(
        """SELECT i.*, COUNT(c.id) AS contact_count
           FROM institutions i LEFT JOIN contacts c ON c.domain = i.domain
           GROUP BY i.domain ORDER BY i.found_at DESC"""
    )
    return [dict(r) for r in rows]


def list_contacts(conn, domain=None):
    sql = """SELECT c.*, i.name AS institution, i.programs, i.country
             FROM contacts c JOIN institutions i ON i.domain = c.domain"""
    args = ()
    if domain:
        sql += " WHERE c.domain = ?"
        args = (domain,)
    sql += " ORDER BY i.name, c.priority"
    return [dict(r) for r in conn.execute(sql, args)]


def get_contact(conn, contact_id):
    r = conn.execute(
        """SELECT c.*, i.name AS institution, i.programs, i.country
           FROM contacts c JOIN institutions i ON i.domain = c.domain WHERE c.id = ?""",
        (contact_id,),
    ).fetchone()
    return dict(r) if r else None


def update_institution(conn, domain, **fields):
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE institutions SET {sets} WHERE domain = ?", (*fields.values(), domain))
    conn.commit()


def pending_outreach(conn):
    """Latest outreach record for each contact whose draft/email is still awaiting news."""
    rows = conn.execute(
        """SELECT c.id AS contact_id, c.email, c.domain, c.outreach_status, o.kind, o.gmail_id, o.created_at
           FROM contacts c
           JOIN outreach o ON o.id = (SELECT MAX(id) FROM outreach WHERE contact_id = c.id)
           WHERE c.outreach_status IN ('Draft created', 'Email sent')"""
    )
    return [dict(r) for r in rows]


def set_outreach_status(conn, contact_id, status, reply_at=None):
    conn.execute("UPDATE contacts SET outreach_status = ? WHERE id = ?", (status, contact_id))
    if status == "Email sent":
        conn.execute("UPDATE contacts SET last_contacted_at = ? WHERE id = ?", (now(), contact_id))
    if reply_at:
        conn.execute("UPDATE contacts SET last_reply_at = ? WHERE id = ?", (reply_at, contact_id))
    new_inst_status = {"Email sent": ("Contacted", ("New",)),
                       "Replied": ("Replied", ("New", "Contacted"))}.get(status)
    if new_inst_status:
        target, from_states = new_inst_status
        conn.execute(
            f"""UPDATE institutions SET status = ?
                WHERE domain = (SELECT domain FROM contacts WHERE id = ?)
                  AND status IN ({",".join("?" * len(from_states))})""",
            (target, contact_id, *from_states),
        )
    conn.commit()


def record_outreach(conn, contact_id, kind, gmail_id, subject):
    conn.execute(
        "INSERT INTO outreach (contact_id, kind, gmail_id, subject, created_at) VALUES (?, ?, ?, ?, ?)",
        (contact_id, kind, gmail_id, subject, now()),
    )
    status = "Email sent" if kind == "sent" else "Draft created"
    conn.execute(
        "UPDATE contacts SET outreach_status = ?, last_contacted_at = ? WHERE id = ?",
        (status, now(), contact_id),
    )
    if kind == "sent":
        conn.execute(
            """UPDATE institutions SET status = 'Contacted'
               WHERE domain = (SELECT domain FROM contacts WHERE id = ?) AND status = 'New'""",
            (contact_id,),
        )
    conn.commit()


def unsynced(conn):
    insts = [dict(r) for r in conn.execute("SELECT * FROM institutions WHERE synced = 0")]
    contacts = [dict(r) for r in conn.execute(
        """SELECT c.*, i.name AS institution FROM contacts c
           JOIN institutions i ON i.domain = c.domain WHERE c.synced = 0"""
    )]
    return insts, contacts


def mark_synced(conn, domains, contact_ids):
    conn.executemany("UPDATE institutions SET synced = 1 WHERE domain = ?", [(d,) for d in domains])
    conn.executemany("UPDATE contacts SET synced = 1 WHERE id = ?", [(i,) for i in contact_ids])
    conn.commit()


# --- templates ----------------------------------------------------------------

def list_templates(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM templates ORDER BY name")]


def save_template(conn, name, subject, body):
    conn.execute(
        "INSERT OR REPLACE INTO templates (name, subject, body) VALUES (?, ?, ?)",
        (name.strip(), subject, body),
    )
    conn.commit()


def delete_template(conn, name):
    conn.execute("DELETE FROM templates WHERE name = ?", (name,))
    conn.commit()
