"""Ask Claude to recommend search phrases for a specific country, in the language(s)
schools there actually use, informed by programs already found in that country."""
from . import db, llm
from .search import country_code

SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "language": {"type": "string"},
                    "english_meaning": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["keyword", "language", "english_meaning", "why"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["suggestions"],
    "additionalProperties": False,
}

SYSTEM = """You help Naturl Audio, maker of the AL-1 Limiter (a mixing/mastering tool), find schools \
that teach audio engineering, music production, sound design, foley, mixing/mastering, audio post-production \
and related subjects, so it can offer education partnerships.

Given a country, recommend web search phrases that will surface those schools' program pages in that country. \
Write each phrase the way a prospective student there would type it into a search engine:
- Use the language(s) the country's schools publish in (several if the country is multilingual). Include \
English phrases only where English is used there, or where local programs commonly use English names.
- Use the country's real qualification and program names (e.g. Bachelor/Master, Licenciatura, Tecnólogo, \
Diplom, HND, BTS, 専門学校), local terms for the subject (e.g. Tontechnik, Tonmeister, engenharia de áudio, \
ingénieur du son) and, where natural, the word for university or school.
- Include or leave out the country's name as the request says.
- Cover different angles: degrees, vocational diplomas, film/TV sound, game audio, music technology.
- Don't repeat or trivially reword phrases that are already in use."""


def suggest_keywords(conn, region, count=12):
    if not llm.available():
        raise llm.LLMError("Keyword suggestions need ANTHROPIC_API_KEY in .env")
    existing = [k["keyword"] for k in db.list_keywords(conn) if k["region"] in ("", region)]
    found = [i for i in db.list_institutions(conn) if (i["country"] or "").lower() == region.lower()]
    programs = sorted({p.strip() for i in found for p in (i["programs"] or "").split(";") if p.strip()})
    user = f"Country: {region}\nNumber of suggestions wanted: {count}\n"
    user += ("Leave out the country's name: the search engine already limits results to this country.\n\n"
             if country_code(region) else
             "Include the country's name (in the local language) in each phrase: the search engine can't "
             "limit results to this country.\n\n")
    user += "Phrases already in use:\n" + ("\n".join(f"- {k}" for k in existing) or "(none)") + "\n\n"
    user += ("Program names already found at schools in this country (good hints for local terminology):\n"
             + ("\n".join(f"- {p}" for p in programs[:60]) or "(none yet)"))
    data = llm.ask_json(SYSTEM, user, SCHEMA)
    have = {k.lower() for k in existing}
    return [s for s in data["suggestions"] if s["keyword"].strip() and s["keyword"].strip().lower() not in have][:count]


def add_suggestions(conn, region, suggestions):
    added = 0
    for s in suggestions:
        added += db.add_keyword(conn, s["keyword"], region=region, language=s["language"],
                                note=s["english_meaning"], source="suggested")
    return added
