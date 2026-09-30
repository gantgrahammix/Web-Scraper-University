"""Brave Search API client."""
import time

import httpx

from . import config

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class SearchError(RuntimeError):
    pass


def search(query, pages=1, per_page=20):
    """Return a list of {url, title, description} for a query."""
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
            resp = client.get(ENDPOINT, headers=headers, params=params)
            if resp.status_code == 429:
                time.sleep(2)
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
