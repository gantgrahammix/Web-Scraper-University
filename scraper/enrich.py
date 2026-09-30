"""Add size and cost data: College Scorecard for US schools, Wikidata elsewhere,
then bucket into size categories and tuition bands."""
import httpx

from . import config

SCORECARD_URL = "https://api.data.gov/ed/collegescorecard/v1/schools"
SCORECARD_FIELDS = ",".join([
    "school.name", "school.school_url", "school.city", "school.state", "school.ownership",
    "latest.student.size", "latest.cost.tuition.in_state", "latest.cost.tuition.out_of_state",
])
WIKIDATA_API = "https://www.wikidata.org/w/api.php"

# Rough conversion to USD, only used to pick a tuition band.
USD_RATE = {
    "USD": 1.0, "CAD": 0.73, "GBP": 1.27, "EUR": 1.08, "AUD": 0.66, "NZD": 0.60,
    "SEK": 0.095, "NOK": 0.093, "DKK": 0.145, "CHF": 1.12, "JPY": 0.0067, "KRW": 0.00073,
    "CNY": 0.14, "HKD": 0.13, "SGD": 0.74, "INR": 0.012, "BRL": 0.18, "MXN": 0.055,
    "ZAR": 0.055, "AED": 0.27,
}

US_NAMES = {"us", "usa", "united states", "united states of america", "u.s.", "u.s.a."}


def size_category(enrollment):
    if not enrollment:
        return "Unknown"
    if enrollment < 5000:
        return "Small (<5k)"
    if enrollment < 15000:
        return "Medium (5-15k)"
    if enrollment < 30000:
        return "Large (15-30k)"
    return "Very Large (30k+)"


def tuition_band(amount, currency):
    rate = USD_RATE.get((currency or "").upper())
    if not amount or rate is None:
        return "Unknown"
    usd = amount * rate
    if usd < 10000:
        return "Low (<$10k/yr)"
    if usd < 30000:
        return "Mid ($10-30k/yr)"
    return "High ($30k+/yr)"


def _norm_url(u):
    u = (u or "").lower().replace("https://", "").replace("http://", "").replace("www.", "")
    return u.split("/")[0]


def scorecard_lookup(name, domain):
    if not config.SCORECARD_API_KEY or not name:
        return None
    params = {"api_key": config.SCORECARD_API_KEY, "school.name": name, "fields": SCORECARD_FIELDS, "per_page": 20}
    try:
        resp = httpx.get(SCORECARD_URL, params=params, timeout=20)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    results = resp.json().get("results", [])
    match = next((r for r in results if _norm_url(r.get("school.school_url")).endswith(domain)), None)
    if not match:
        return None
    ownership = {1: "public", 2: "private", 3: "private"}.get(match.get("school.ownership"), "unknown")
    return {
        "enrollment": match.get("latest.student.size"),
        "tuition_in_state": match.get("latest.cost.tuition.in_state"),
        "tuition_out_of_state": match.get("latest.cost.tuition.out_of_state"),
        "control": ownership,
        "city": ", ".join(filter(None, [match.get("school.city"), match.get("school.state")])),
    }


def wikidata_enrollment(name, domain):
    """Find the institution on Wikidata (matched by official website) and return its student count."""
    if not name:
        return None
    headers = {"User-Agent": config.USER_AGENT}
    try:
        found = httpx.get(WIKIDATA_API, headers=headers, timeout=20, params={
            "action": "wbsearchentities", "search": name, "language": "en",
            "type": "item", "limit": 5, "format": "json",
        }).json().get("search", [])
        if not found:
            return None
        entities = httpx.get(WIKIDATA_API, headers=headers, timeout=20, params={
            "action": "wbgetentities", "ids": "|".join(f["id"] for f in found),
            "props": "claims", "format": "json",
        }).json().get("entities", {})
    except (httpx.HTTPError, ValueError):
        return None
    for ent in entities.values():
        claims = ent.get("claims", {})
        sites = [_norm_url(c["mainsnak"].get("datavalue", {}).get("value", "")) for c in claims.get("P856", [])]
        if not any(s.endswith(domain) for s in sites):
            continue
        counts = [c for c in claims.get("P2196", []) if c["mainsnak"].get("datavalue")]
        if counts:
            latest = max(counts, key=lambda c: c.get("qualifiers", {}).get("P585", [{}])[0]
                         .get("datavalue", {}).get("value", {}).get("time", ""))
            return int(float(latest["mainsnak"]["datavalue"]["value"]["amount"]))
    return None


def enrich(inst):
    """Mutates and returns the institution dict."""
    name, domain = inst.get("name"), inst["domain"]
    is_us = (inst.get("country") or "").strip().lower() in US_NAMES or domain.endswith(".edu")

    sc = scorecard_lookup(name, domain) if is_us else None
    if sc:
        inst["enrollment"] = sc["enrollment"] or inst.get("enrollment")
        inst["enrollment_source"] = "College Scorecard"
        inst["control"] = sc["control"]
        inst["city"] = inst.get("city") or sc["city"]
        inst["country"] = inst.get("country") or "USA"
        if sc["tuition_out_of_state"]:
            inst["tuition"] = sc["tuition_out_of_state"]
            inst["tuition_currency"] = "USD"
            in_state = sc["tuition_in_state"]
            inst["tuition_note"] = "per year, out-of-state" + (f" (in-state ${in_state:,.0f})" if in_state and in_state != sc["tuition_out_of_state"] else "")
    elif inst.get("enrollment"):
        inst["enrollment_source"] = "school website"
    else:
        count = wikidata_enrollment(name, domain)
        if count:
            inst["enrollment"] = count
            inst["enrollment_source"] = "Wikidata"

    if inst.get("enrollment"):
        inst["enrollment"] = int(inst["enrollment"])
    inst["size_category"] = size_category(inst.get("enrollment"))
    inst["tuition_band"] = tuition_band(inst.get("tuition"), inst.get("tuition_currency"))
    return inst
