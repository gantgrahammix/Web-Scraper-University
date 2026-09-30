"""Brave Search API client."""
import time

import httpx

from . import config

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


# Region name -> Brave country code, so results are localized to that country.
COUNTRY_CODES = {
    "argentina": "AR", "australia": "AU", "austria": "AT", "belgium": "BE", "brazil": "BR",
    "canada": "CA", "chile": "CL", "china": "CN", "denmark": "DK", "finland": "FI", "france": "FR",
    "germany": "DE", "hong kong": "HK", "india": "IN", "indonesia": "ID", "italy": "IT",
    "japan": "JP", "south korea": "KR", "korea": "KR", "malaysia": "MY", "mexico": "MX",
    "netherlands": "NL", "new zealand": "NZ", "norway": "NO", "philippines": "PH", "poland": "PL",
    "portugal": "PT", "saudi arabia": "SA", "south africa": "ZA", "spain": "ES", "sweden": "SE",
    "switzerland": "CH", "taiwan": "TW", "turkey": "TR", "uk": "GB", "united kingdom": "GB",
    "usa": "US", "us": "US", "united states": "US",
}


class SearchError(RuntimeError):
    pass


def country_code(region):
    return COUNTRY_CODES.get((region or "").strip().lower())


def search(query, pages=1, per_page=20, country=None):
    """Return a list of {url, title, description} for a query. `country` is a region
    name (e.g. "Germany"); if Brave supports it, results are localized to that country."""
    if not config.BRAVE_API_KEY:
        raise SearchError("BRAVE_API_KEY is not set in .env")
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": config.BRAVE_API_KEY,
    }
    results = []
    with httpx.Client(timeout=20) as client:
        for page in range(pages):
            params = {"q": query, "count": per_page, "offset": page, "safesearch": "moderate"}
            if country_code(country):
                params["country"] = country_code(country)
            resp = client.get(ENDPOINT, headers=headers, params=params)
            if resp.status_code == 429:
                time.sleep(2)
                resp = client.get(ENDPOINT, headers=headers, params=params)
            if resp.status_code == 422 and "country" in params:  # country not supported: search unlocalized
                params.pop("country")
                resp = client.get(ENDPOINT, headers=headers, params=params)
            if resp.status_code != 200:
                raise SearchError(f"Brave search failed ({resp.status_code}): {resp.text[:200]}")
            web = resp.json().get("web", {}).get("results", [])
            results.extend(
                {"url": r.get("url", ""), "title": r.get("title", ""), "description": r.get("description", "")}
                for r in web
            )
            if len(web) < per_page:
                break
            time.sleep(1.1)  # free tier allows ~1 request/second
    return results
