"""Polite, small crawler: fetches the page a search hit pointed to, plus the most
promising contact / faculty / partnership pages on the same site."""
import re
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from . import config
from .domains import same_site

MAX_CHARS_PER_PAGE = 12000

# Link text / URL words that suggest a page with the people we want to reach.
LINK_HINTS = {
    "partnership": 12, "partner": 9, "industry relation": 10, "corporate": 5, "collaborat": 6,
    "contact": 9, "staff": 8, "faculty": 8, "people": 6, "team": 5, "directory": 6,
    "dean": 9, "chair": 6, "head of": 6, "leadership": 6, "department": 4, "school of": 3,
    "tuition": 6, "fees": 5, "cost": 3,
    "audio": 2, "sound": 2, "music": 1, "recording": 2,
}
# Pages that rarely list decision-makers.
LINK_PENALTIES = {
    "news": -8, "stories": -8, "story": -8, "blog": -8, "event": -6, "podcast": -6,
    "alumni": -4, "/p2": -6, "page=": -6, "login": -10, "apply": -4, "privacy": -10,
    "cookie": -10, "sitemap": -5, "calendar": -6,
}
SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|svg|zip|mp3|mp4|mov|docx?|xlsx?|pptx?)(\?|$)", re.I)
FALLBACK_PATHS = ["/contact", "/contact-us", "/about"]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


class Crawler:
    def __init__(self):
        self.client = httpx.Client(
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": config.USER_AGENT, "Accept-Language": "en;q=1.0, *;q=0.5"},
        )
        self._robots = {}

    def close(self):
        self.client.close()

    def _allowed(self, url):
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self._robots:
            rp = RobotFileParser()
            try:
                resp = self.client.get(base + "/robots.txt")
                rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            except httpx.HTTPError:
                rp.parse([])
            self._robots[base] = rp
        return self._robots[base].can_fetch(config.USER_AGENT, url)

    def fetch(self, url):
        """Return (final_url, html) or None."""
        if not self._allowed(url):
            return None
        try:
            resp = self.client.get(url)
        except httpx.HTTPError:
            return None
        if resp.status_code != 200 or "html" not in resp.headers.get("content-type", ""):
            return None
        return str(resp.url), resp.text

    def crawl_school(self, start_url, domain, max_pages=None):
        """Return a list of {url, title, text, emails} for up to max_pages pages."""
        max_pages = max_pages or config.MAX_PAGES_PER_SCHOOL
        pages, visited, candidates = [], set(), {}

        def visit(url):
            url = url.split("#")[0]
            if url in visited:
                return None
            visited.add(url)
            got = self.fetch(url)
            time.sleep(config.CRAWL_DELAY_SECONDS)
            if not got:
                return None
            final_url, html = got
            page = parse_page(final_url, html)
            pages.append(page)
            for link_url, text in page.pop("links"):
                if same_site(link_url, domain) and link_url not in visited:
                    score = score_link(link_url, text)
                    if score > 0:
                        candidates[link_url] = max(score, candidates.get(link_url, 0))
            return page

        visit(start_url)
        if not pages:
            parsed = urlparse(start_url)
            visit(f"{parsed.scheme}://{parsed.netloc}/")

        root = f"{urlparse(pages[0]['url']).scheme}://{urlparse(pages[0]['url']).netloc}" if pages else f"https://www.{domain}"
        for path in FALLBACK_PATHS:
            candidates.setdefault(root + path, 3)

        while len(pages) < max_pages and candidates:
            url = max(candidates, key=candidates.get)
            del candidates[url]
            visit(url)
        return pages


def score_link(url, text):
    if SKIP_EXT.search(url) or url.startswith(("mailto:", "tel:", "javascript:")):
        return 0
    hay = f"{url} {text}".lower()
    score = sum(w for hint, w in LINK_HINTS.items() if hint in hay)
    if score:
        score += sum(w for hint, w in LINK_PENALTIES.items() if hint in hay)
    return max(score, 0)


def parse_page(url, html):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("mailto:"):
            continue
        links.append((urljoin(url, href), a.get_text(" ", strip=True)[:80]))

    emails = set()
    for a in soup.select('a[href^="mailto:"]'):
        addr = a["href"][7:].split("?")[0].strip()
        if EMAIL_RE.fullmatch(addr):
            emails.add(addr.lower())

    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    text = re.sub(r"\n\s*\n+", "\n", soup.get_text("\n", strip=True))
    emails.update(e.lower() for e in EMAIL_RE.findall(text) if not e.lower().endswith((".png", ".jpg")))
    return {
        "url": url,
        "title": title,
        "text": text[:MAX_CHARS_PER_PAGE],
        "emails": sorted(emails),
        "links": links,
    }
