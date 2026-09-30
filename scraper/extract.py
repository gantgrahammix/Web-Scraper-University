"""Read crawled pages and pull out institution details and partnership contacts.

Uses Claude when ANTHROPIC_API_KEY is set; otherwise falls back to simple rules."""
import json
import re

import anthropic

from . import config

ROLES = ["partnerships", "program_head", "dean", "department", "admissions", "general"]
ROLE_PRIORITY = {r: i + 1 for i, r in enumerate(ROLES)}

_nullable_str = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_nullable_num = {"anyOf": [{"type": "number"}, {"type": "null"}]}

SCHEMA = {
    "type": "object",
    "properties": {
        "is_institution": {"type": "boolean"},
        "name": {"type": "string"},
        "country": {"type": "string"},
        "city": _nullable_str,
        "programs": {"type": "array", "items": {"type": "string"}},
        "relevance": {"type": "integer", "enum": [0, 1, 2, 3, 4, 5]},
        "relevance_reason": {"type": "string"},
        "control": {"type": "string", "enum": ["public", "private", "unknown"]},
        "enrollment": _nullable_num,
        "tuition": _nullable_num,
        "tuition_currency": _nullable_str,
        "tuition_note": _nullable_str,
        "contacts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": _nullable_str,
                    "title": _nullable_str,
                    "role": {"type": "string", "enum": ROLES},
                    "email": _nullable_str,
                    "phone": _nullable_str,
                    "source_url": {"type": "string"},
                },
                "required": ["name", "title", "role", "email", "phone", "source_url"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "is_institution", "name", "country", "city", "programs", "relevance",
        "relevance_reason", "control", "enrollment", "tuition", "tuition_currency",
        "tuition_note", "contacts",
    ],
    "additionalProperties": False,
}

SYSTEM = """You help Naturl Audio, maker of the AL-1 Limiter (an audio mixing/mastering tool), find schools \
that could use it in their curriculum and the right person to talk to about an education partnership.

You receive text crawled from one website. Report what the pages say. Do not guess or use outside knowledge \
for contact details: every email and phone number you return must appear in the page text. Leave a field null \
when the pages don't state it.

- is_institution: true only for a real degree- or diploma-granting school, college, university, conservatory or \
accredited audio/film school. False for blogs, retailers, online-course marketplaces, directories and forums.
- relevance: 5 = dedicated audio engineering / music production / sound design / post-production program; \
4 = strong audio concentration inside a music, film or media program; 3 = some audio courses; \
1-2 = only tangential; 0 = none. Large universities often mention the program only on its own page; \
if the pages shown are generic but the search result clearly describes an audio program at this institution, \
count it.
- programs: names of the relevant programs or courses, as written on the site.
- contacts: people or offices useful for starting a partnership conversation, best first. Roles:
  partnerships = partnerships / industry relations / corporate engagement / business development office;
  program_head = director, chair, coordinator or head of the audio / music technology / production program;
  dean = dean or head of the school, college or faculty containing the program;
  department = other relevant faculty or department office; admissions; general = main contact.
  Include up to 6. Prefer named people with emails.
- enrollment: total student headcount of the institution if stated.
- tuition: annual tuition for the relevant program (or general undergraduate tuition) if stated, as a number, \
with its ISO currency code and a short note (e.g. "per year, international students")."""


def _pages_to_prompt(domain, pages, hit=None):
    parts = [f"Website: {domain}\n"]
    if hit:
        parts.append(f"SEARCH RESULT THAT LED HERE (use as a hint only):\n{hit.get('title', '')}\n"
                     f"{hit.get('description', '')}\n{hit.get('url', '')}\n")
    for p in pages:
        parts.append(f"=== PAGE: {p['url']}\nTITLE: {p['title']}\nEMAILS FOUND: {', '.join(p['emails']) or 'none'}\n{p['text']}\n")
    return "\n".join(parts)


class ExtractionError(RuntimeError):
    pass


def extract_with_claude(domain, pages, hit=None, client=None):
    client = client or anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY or None)
    response = client.beta.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": _pages_to_prompt(domain, pages, hit)}],
        output_config={
            "effort": config.CLAUDE_EFFORT,
            "format": {"type": "json_schema", "schema": SCHEMA},
        },
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise ExtractionError("Claude declined to process this site")
    if response.stop_reason == "max_tokens":
        raise ExtractionError("Claude's answer was cut off (max_tokens)")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise ExtractionError("Claude returned no text")
    return json.loads(text)


def validate(data, pages):
    """Drop contact details that don't actually appear on the crawled pages."""
    corpus = "\n".join(p["text"] + " " + " ".join(p["emails"]) for p in pages).lower()
    digits = re.sub(r"\D", "", corpus)
    clean = []
    for c in data.get("contacts", []):
        email = (c.get("email") or "").strip().lower()
        if email and email not in corpus:
            email = ""
        phone = (c.get("phone") or "").strip()
        if phone and re.sub(r"\D", "", phone) not in digits:
            phone = ""
        if not (email or phone or c.get("name")):
            continue
        clean.append({**c, "email": email, "phone": phone, "priority": ROLE_PRIORITY.get(c.get("role"), 9)})
    clean.sort(key=lambda c: (c["priority"], not c["email"]))
    data["contacts"] = clean
    return data


# --- rule-based fallback -------------------------------------------------------

AUDIO_TERMS = [
    "audio engineering", "sound engineering", "music production", "music technology",
    "sound design", "recording arts", "audio production", "post-production", "foley",
    "mixing", "mastering", "acoustics", "audio post", "sound for film", "recording studio",
]
TITLE_ROLES = [
    ("partnerships", re.compile(r"partnership|industry relations|corporate relations|business development", re.I)),
    ("dean", re.compile(r"\bdean\b", re.I)),
    ("program_head", re.compile(r"(program|programme|course) (director|leader|coordinator)|head of (audio|music|sound)|\bchair\b", re.I)),
    ("admissions", re.compile(r"admission", re.I)),
]


def extract_with_rules(domain, pages, hit=None):
    text = "\n".join(p["text"] for p in pages).lower()
    if hit:
        text += f"\n{hit.get('title', '')} {hit.get('description', '')}".lower()
    hits = [t for t in AUDIO_TERMS if t in text]
    relevance = min(5, len(hits))
    contacts = []
    for p in pages:
        for email in p["emails"]:
            idx = p["text"].lower().find(email)
            context = p["text"][max(0, idx - 200): idx] if idx >= 0 else ""
            role = next((r for r, rx in TITLE_ROLES if rx.search(context) or rx.search(email)), "general")
            contacts.append({"name": None, "title": None, "role": role, "email": email,
                             "phone": None, "source_url": p["url"]})
    title = pages[0]["title"] if pages else domain
    return {
        "is_institution": True,
        "name": re.split(r"\s[|\-–—]\s", title)[-1].strip() or domain,
        "country": "",
        "city": None,
        "programs": hits,
        "relevance": relevance,
        "relevance_reason": "keyword match (rules mode)",
        "control": "unknown",
        "enrollment": None,
        "tuition": None,
        "tuition_currency": None,
        "tuition_note": None,
        "contacts": contacts[:10],
    }


def extract(domain, pages, hit=None):
    if config.ANTHROPIC_API_KEY:
        data = extract_with_claude(domain, pages, hit)
    else:
        data = extract_with_rules(domain, pages, hit)
    return validate(data, pages)
