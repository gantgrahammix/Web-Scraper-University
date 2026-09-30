"""Cheap check on search results before the expensive crawl + Claude read.

1. Free rules sort each hit into yes / no / maybe using its address, title and snippet.
2. The "maybe" hits from one search are sent together in a single request to a small,
   cheap model (Haiku), which picks the ones that look like schools with audio programs.

A prefilter skip applies to that search only: the domain is NOT marked as seen, so a
better hit from a later search can still bring it in."""
import re

from . import config, llm
from .domains import looks_academic

SCHOOL_WORDS = re.compile(
    r"\b(universit|college|conservato|institut|academy|academie|akademie|school|escola|escuela|"
    r"école|ecole|hochschule|fachhochschule|faculdade|facultad|faculty|polytechnic|politecnico|"
    r"degree|diploma|bachelor|master|bsc|ba \(hons\)|bmus|mfa|hnd|licenciatura|tecnólogo|"
    r"course|curso|studium|studiengang|formation|program|programme|大学|専門学校|학교|대학)",
    re.I,
)
NON_SCHOOL = re.compile(
    r"\b(shop|store|buy|price|sale|deal|review|best \d+|top \d+|forum|thread|reddit|blog|"
    r"podcast|news|job|jobs|career|salary|hiring|vacanc|plugin|preset|sample pack|tutorial|"
    r"how to|what is|vs\.?|gear|interface|headphone|microphone)\b",
    re.I,
)

SCHEMA = {
    "type": "object",
    "properties": {"keep": {"type": "array", "items": {"type": "integer"}}},
    "required": ["keep"],
    "additionalProperties": False,
}

SYSTEM = """You screen web search results for a company looking for schools (universities, colleges, \
conservatories, vocational and audio/film schools) that teach audio engineering, music production, sound \
design, foley, mixing/mastering or audio post-production. Results may be in any language.

Return the numbers of the results that are probably pages published BY such a school (a program page, \
department page, or the school's own site). Leave out shops, gear reviews, forums, blogs, news, job ads, \
online-course marketplaces and ranking/directory sites. When unsure whether a page belongs to a real \
school, keep it."""


def rule_verdict(domain, hit):
    text = f"{hit.get('title', '')} {hit.get('description', '')} {hit.get('url', '')}"
    school = bool(SCHOOL_WORDS.search(text))
    if looks_academic(domain):
        return "yes"
    if NON_SCHOOL.search(hit.get("title", "")) and not school:
        return "no"
    return "yes" if school and not NON_SCHOOL.search(text) else "maybe"


def screen(candidates, log=print):
    """candidates: list of (domain, hit). Returns (keep, skipped) as lists of (domain, hit)."""
    if not config.PREFILTER:
        return candidates, []
    keep, maybe, skipped = [], [], []
    for domain, hit in candidates:
        verdict = rule_verdict(domain, hit)
        (keep if verdict == "yes" else skipped if verdict == "no" else maybe).append((domain, hit))

    if maybe and llm.available():
        listing = "\n\n".join(
            f"[{i}] {hit.get('url', '')}\n{hit.get('title', '')}\n{hit.get('description', '')}"
            for i, (_, hit) in enumerate(maybe)
        )
        try:
            chosen = set(llm.ask_json(SYSTEM, listing, SCHEMA, model=config.PREFILTER_MODEL)["keep"])
        except Exception as e:  # if the screen fails, don't lose candidates
            log(f"    prefilter check failed ({e}); reading all uncertain results")
            chosen = set(range(len(maybe)))
        for i, item in enumerate(maybe):
            (keep if i in chosen else skipped).append(item)
    else:
        keep.extend(maybe)  # no AI available: stay on the safe side
    return keep, skipped
