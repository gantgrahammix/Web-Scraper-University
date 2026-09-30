"""Google Sheets sync. The tool only appends new rows and updates its own outreach
columns; your Status and Notes edits in the sheet are never overwritten."""
from pathlib import Path

import gspread

from . import config, db
from .google_auth import get_credentials

INSTITUTION_HEADERS = [
    "Name", "Country", "City", "Website", "Programs", "Relevance (0-5)", "Why relevant",
    "Size Category", "Enrollment", "Enrollment Source", "Tuition", "Currency", "Tuition Note",
    "Tuition Band", "Public/Private", "Found Via", "Date Found", "Status", "Notes",
]
CONTACT_HEADERS = [
    "Institution", "Website", "Name", "Title", "Role", "Email", "Phone", "Source URL",
    "Outreach", "Last Contacted", "Last Reply",
]
STATUS_OPTIONS = ["New", "Contacted", "Replied", "Meeting set", "Partner", "Not a fit"]


def _client():
    return gspread.authorize(get_credentials(interactive=False))


def _set_sheet_id_in_env(sheet_id):
    env = config.ROOT / ".env"
    lines = env.read_text().splitlines() if env.exists() else []
    lines = [l for l in lines if not l.startswith("GOOGLE_SHEET_ID=")] + [f"GOOGLE_SHEET_ID={sheet_id}"]
    env.write_text("\n".join(lines) + "\n")
    config.GOOGLE_SHEET_ID = sheet_id


def open_or_create():
    gc = _client()
    if config.GOOGLE_SHEET_ID:
        sh = gc.open_by_key(config.GOOGLE_SHEET_ID)
    else:
        sh = gc.create("Naturl Audio - University Partnerships")
        _set_sheet_id_in_env(sh.id)
    _ensure_tabs(sh)
    return sh


def _ensure_tabs(sh):
    titles = [ws.title for ws in sh.worksheets()]
    if "Institutions" not in titles:
        ws = sh.sheet1 if titles == ["Sheet1"] else sh.add_worksheet("Institutions", rows=1000, cols=len(INSTITUTION_HEADERS))
        ws.update_title("Institutions")
        ws.update([INSTITUTION_HEADERS], "A1")
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})
        _add_status_dropdown(sh, ws)
    if "Contacts" not in titles:
        ws = sh.add_worksheet("Contacts", rows=2000, cols=len(CONTACT_HEADERS))
        ws.update([CONTACT_HEADERS], "A1")
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}})


def _add_status_dropdown(sh, ws):
    col = INSTITUTION_HEADERS.index("Status")
    sh.batch_update({"requests": [{
        "setDataValidation": {
            "range": {"sheetId": ws.id, "startRowIndex": 1, "startColumnIndex": col, "endColumnIndex": col + 1},
            "rule": {
                "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": s} for s in STATUS_OPTIONS]},
                "showCustomUi": True,
                "strict": False,
            },
        }
    }]})


def _inst_row(i):
    return [
        i["name"], i["country"], i["city"], f"https://{i['domain']}", i["programs"], i["relevance"],
        i["relevance_reason"], i["size_category"], i["enrollment"] or "", i["enrollment_source"] or "",
        i["tuition"] or "", i["tuition_currency"] or "", i["tuition_note"] or "", i["tuition_band"],
        i["control"], i["found_via"], i["found_at"][:10], i["status"], i["notes"] or "",
    ]


def _contact_row(c):
    return [
        c["institution"], f"https://{c['domain']}", c["name"], c["title"], c["role"], c["email"],
        c["phone"], c["source_url"], c["outreach_status"], (c["last_contacted_at"] or "")[:10],
        (c.get("last_reply_at") or "")[:10],
    ]


def sync(conn):
    """Append every institution/contact not yet in the sheet. Returns (n_institutions, n_contacts)."""
    insts, contacts = db.unsynced(conn)
    if not insts and not contacts:
        return 0, 0
    sh = open_or_create()
    if insts:
        sh.worksheet("Institutions").append_rows([_inst_row(i) for i in insts], value_input_option="USER_ENTERED")
    if contacts:
        sh.worksheet("Contacts").append_rows([_contact_row(c) for c in contacts], value_input_option="USER_ENTERED")
    db.mark_synced(conn, [i["domain"] for i in insts], [c["id"] for c in contacts])
    return len(insts), len(contacts)


def pull_status(conn):
    """Copy Status/Notes you edited in the sheet back into the local database."""
    ws = open_or_create().worksheet("Institutions")
    rows = ws.get_all_records()
    for r in rows:
        domain = str(r.get("Website", "")).replace("https://", "").strip("/")
        if domain:
            db.update_institution(conn, domain, status=r.get("Status") or "New", notes=r.get("Notes") or "")
    return len(rows)


def mark_outreach(contact):
    """Update the Outreach columns for one contact row (matched by email) and move the
    institution's Status forward (New -> Contacted on send, -> Replied on a reply)."""
    sh = open_or_create()
    ws = sh.worksheet("Contacts")
    email_col = CONTACT_HEADERS.index("Email") + 1
    cells = [c for c in ws.findall(contact["email"], in_column=email_col) if c.value == contact["email"]]
    out_col = CONTACT_HEADERS.index("Outreach") + 1
    for cell in cells:
        ws.update(
            [[contact["outreach_status"], (contact["last_contacted_at"] or "")[:10],
              (contact.get("last_reply_at") or "")[:10]]],
            gspread.utils.rowcol_to_a1(cell.row, out_col),
        )

    moves = {"Email sent": ("Contacted", ("", "New", None)),
             "Replied": ("Replied", ("", "New", "Contacted", None))}
    if contact["outreach_status"] in moves:
        target, from_states = moves[contact["outreach_status"]]
        iws = sh.worksheet("Institutions")
        site_col = INSTITUTION_HEADERS.index("Website") + 1
        status_col = INSTITUTION_HEADERS.index("Status") + 1
        for cell in iws.findall(f"https://{contact['domain']}", in_column=site_col):
            if iws.cell(cell.row, status_col).value in from_states:
                iws.update_cell(cell.row, status_col, target)


def sheet_url():
    return f"https://docs.google.com/spreadsheets/d/{config.GOOGLE_SHEET_ID}" if config.GOOGLE_SHEET_ID else ""
