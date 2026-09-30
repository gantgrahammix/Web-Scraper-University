"""Turn URLs into institution domains and filter out sites that aren't schools."""
from urllib.parse import urlparse

import tldextract

# Offline extractor using tldextract's bundled public-suffix snapshot. Private suffixes
# (wixsite.com, github.io, ...) are included so sites hosted there aren't merged into one.
_extract = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)

# Aggregators, social media, job boards, course marketplaces, etc.
BLOCKED_DOMAINS = {
    "wikipedia.org", "wikimedia.org", "reddit.com", "youtube.com", "facebook.com",
    "instagram.com", "twitter.com", "x.com", "tiktok.com", "linkedin.com",
    "pinterest.com", "quora.com", "medium.com", "substack.com",
    "indeed.com", "glassdoor.com", "ziprecruiter.com", "monster.com",
    "coursera.org", "udemy.com", "edx.org", "skillshare.com", "masterclass.com",
    "domestika.org", "linkedinlearning.com", "futurelearn.com", "pluralsight.com",
    "studyportals.com", "mastersportal.com", "bachelorsportal.com", "shortcoursesportal.com",
    "findamasters.com", "findaphd.com", "hotcoursesabroad.com", "topuniversities.com",
    "timeshighereducation.com", "usnews.com", "niche.com", "collegevine.com",
    "collegeboard.org", "petersons.com", "cappex.com", "unigo.com", "princetonreview.com",
    "bestcolleges.com", "collegesimply.com", "univstats.com", "collegetuitioncompare.com",
    "whatuni.com", "ucas.com", "studyinaustralia.gov.au", "educations.com",
    "gearspace.com", "soundonsound.com", "musicradar.com", "sweetwater.com",
    "splice.com", "berkleeonline.com", "amazon.com", "google.com", "apple.com",
    "spotify.com", "soundcloud.com", "bandcamp.com", "yelp.com", "tripadvisor.com",
}


def registered_domain(url):
    """'https://music.ox.ac.uk/courses' -> 'ox.ac.uk'. Returns '' if not parseable."""
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    host = urlparse(url).hostname or ""
    ext = _extract(host)
    if not ext.domain or not ext.suffix:
        return ""
    return f"{ext.domain}.{ext.suffix}".lower()


def is_blocked(domain):
    return domain in BLOCKED_DOMAINS


def same_site(url, domain):
    return registered_domain(url) == domain


def looks_academic(domain):
    """A hint only, used for sorting: domains under edu/ac suffixes are almost always schools."""
    ext = _extract(domain)
    parts = ext.suffix.split(".")
    return "edu" in parts or "ac" in parts
