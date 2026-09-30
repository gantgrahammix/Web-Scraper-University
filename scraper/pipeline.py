"""search -> de-duplicate -> crawl -> extract -> enrich -> save -> sync."""
from . import config, db
from .crawler import Crawler
from .domains import is_blocked, looks_academic, registered_domain
from .enrich import enrich
from .extract import AUDIO_TERMS, extract
from .search import search

MAX_ATTEMPTS = 3  # per domain, across errors and re-checks


def audio_score(hit):
    text = f"{hit.get('title', '')} {hit.get('description', '')} {hit.get('url', '')}".lower().replace("-", " ")
    return sum(term.replace("-", " ") in text for term in AUDIO_TERMS)


def should_process(status, hit):
    """Decide whether a domain we've seen before deserves another look."""
    if status is None:
        return True
    if status["outcome"] in ("saved", "blocked") or status["attempts"] >= MAX_ATTEMPTS:
        return False
    if status["outcome"] == "error":
        return True
    # not_relevant: only re-check if this hit is a different page that looks like an audio program
    return hit["url"] != status["last_url"] and audio_score(hit) >= 1


def build_queries(keywords, regions):
    queries = []
    for k in keywords:
        if regions:
            queries.extend(f"{k} university {r}" for r in regions)
        else:
            queries.append(f"{k} university")
    return queries


def run(conn, keywords, regions, max_new=25, force=False, log=print):
    """Process search results until `max_new` new schools have been saved.
    Returns a summary dict."""
    summary = {"queries": 0, "skipped_queries": 0, "saved": 0, "not_relevant": 0,
               "already_known": 0, "errors": 0, "saved_domains": []}
    crawler = Crawler()
    try:
        for query in build_queries(keywords, regions):
            if summary["saved"] >= max_new:
                break
            if not force and db.query_already_run(conn, query):
                summary["skipped_queries"] += 1
                continue
            log(f"Searching: {query}")
            results = search(query)
            summary["queries"] += 1

            # One entry per domain (its most audio-related hit), academic domains first.
            by_domain = {}
            for r in results:
                d = registered_domain(r["url"])
                if d and (d not in by_domain or audio_score(r) > audio_score(by_domain[d])):
                    by_domain[d] = r
            ordered = sorted(by_domain.items(), key=lambda kv: not looks_academic(kv[0]))

            finished = True
            for domain, hit in ordered:
                if summary["saved"] >= max_new:
                    finished = False  # leave the query unrecorded so the next run resumes it
                    break
                if not should_process(db.domain_status(conn, domain), hit):
                    summary["already_known"] += 1
                    continue
                if is_blocked(domain):
                    db.mark_domain_seen(conn, domain, "blocked", "aggregator/social/marketplace", hit["url"])
                    continue
                _process(conn, crawler, domain, hit, query, summary, log)
            if finished:
                db.record_query(conn, query, len(results))
    finally:
        crawler.close()
    return summary


def _process(conn, crawler, domain, hit, query, summary, log):
    url = hit["url"]
    log(f"  Reading {domain} ...")
    try:
        pages, start_ok = crawler.crawl_school(url, domain)
        if not pages:
            db.mark_domain_seen(conn, domain, "error", "no pages could be fetched", url)
            summary["errors"] += 1
            return
        data = extract(domain, pages, hit)
    except Exception as e:  # keep the batch going; errors are retried on later runs
        db.mark_domain_seen(conn, domain, "error", str(e)[:300], url)
        summary["errors"] += 1
        log(f"    error: {e}")
        return

    if not data["is_institution"] or data["relevance"] < config.MIN_RELEVANCE:
        reason = f"relevance {data['relevance']}: {data['relevance_reason']}" if data["is_institution"] else "not an institution"
        if not start_ok:
            # We never saw the page the search pointed at, so don't write the school off.
            db.mark_domain_seen(conn, domain, "error", f"result page didn't load; {reason}", url)
            summary["errors"] += 1
            log(f"    result page didn't load; will retry later")
            return
        db.mark_domain_seen(conn, domain, "not_relevant", reason, url)
        summary["not_relevant"] += 1
        log(f"    skipped ({reason[:90]})")
        return

    inst = {
        "domain": domain,
        "name": data["name"],
        "country": data["country"],
        "city": data["city"],
        "website": pages[0]["url"],
        "programs": "; ".join(data["programs"]),
        "relevance": data["relevance"],
        "relevance_reason": data["relevance_reason"],
        "enrollment": data["enrollment"],
        "tuition": data["tuition"],
        "tuition_currency": data["tuition_currency"],
        "tuition_note": data["tuition_note"],
        "control": data["control"],
        "found_via": query,
    }
    enrich(inst)
    db.save_institution(conn, inst, data["contacts"])
    db.mark_domain_seen(conn, domain, "saved", "", url)
    summary["saved"] += 1
    summary["saved_domains"].append(domain)
    emails = sum(1 for c in data["contacts"] if c["email"])
    log(f"    saved: {inst['name']} ({inst['country']}), relevance {inst['relevance']}, "
        f"{len(data['contacts'])} contacts / {emails} emails, {inst['size_category']}")
