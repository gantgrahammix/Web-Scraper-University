from scraper import db, outreach, pipeline
from scraper.crawler import parse_page, score_link
from scraper.domains import is_blocked, looks_academic, registered_domain
from scraper.enrich import size_category, tuition_band
from scraper.extract import extract_with_rules, validate


def test_registered_domain():
    assert registered_domain("https://music.ox.ac.uk/courses/audio") == "ox.ac.uk"
    assert registered_domain("https://www.berklee.edu/majors/music-production") == "berklee.edu"
    assert registered_domain("sae.edu") == "sae.edu"
    assert registered_domain("") == ""
    assert is_blocked(registered_domain("https://en.wikipedia.org/wiki/Audio_engineer"))
    assert looks_academic("ox.ac.uk") and looks_academic("berklee.edu") and not looks_academic("example.com")


def test_categories():
    assert size_category(None) == "Unknown"
    assert size_category(1200) == "Small (<5k)"
    assert size_category(12000) == "Medium (5-15k)"
    assert size_category(45000) == "Very Large (30k+)"
    assert tuition_band(9250, "GBP") == "Mid ($10-30k/yr)"
    assert tuition_band(50000, "USD") == "High ($30k+/yr)"
    assert tuition_band(1500, "EUR") == "Low (<$10k/yr)"
    assert tuition_band(1500, "XYZ") == "Unknown"


def test_db_dedup_and_queries():
    conn = db.connect(":memory:")
    assert db.list_keywords(conn)  # seeded
    assert db.add_keyword(conn, "Foley Artist Training")
    assert not db.add_keyword(conn, "foley artist training")  # case-insensitive duplicate

    assert not db.domain_seen(conn, "berklee.edu")
    db.mark_domain_seen(conn, "berklee.edu", "saved")
    assert db.domain_seen(conn, "berklee.edu")

    db.record_query(conn, "audio engineering degree university UK", 20)
    assert db.query_already_run(conn, "Audio Engineering Degree University UK")

    inst = {"domain": "berklee.edu", "name": "Berklee", "relevance": 5}
    contacts = [{"name": "A B", "email": "ab@berklee.edu", "role": "dean", "priority": 3}]
    db.save_institution(conn, inst, contacts)
    db.save_institution(conn, inst, contacts)  # no duplicates
    assert len(db.list_institutions(conn)) == 1
    assert len(db.list_contacts(conn)) == 1

    c = db.list_contacts(conn)[0]
    db.record_outreach(conn, c["id"], "sent", "gmail123", "Hi")
    assert db.get_contact(conn, c["id"])["outreach_status"] == "Email sent"
    assert db.list_institutions(conn)[0]["status"] == "Contacted"


def test_validate_drops_invented_contact_details():
    pages = [{"url": "https://x.edu/contact", "title": "", "emails": ["dean@x.edu"],
              "text": "Dean of Music: Jane Doe, dean@x.edu, +1 (555) 010-2000"}]
    data = {"contacts": [
        {"name": "Jane Doe", "title": "Dean", "role": "dean", "email": "dean@x.edu",
         "phone": "+1 555 010 2000", "source_url": pages[0]["url"]},
        {"name": None, "title": None, "role": "partnerships", "email": "made.up@x.edu",
         "phone": None, "source_url": pages[0]["url"]},
    ]}
    out = validate(data, pages)["contacts"]
    assert len(out) == 1
    assert out[0]["email"] == "dean@x.edu" and out[0]["phone"]


def test_parse_page_and_rules_extraction():
    html = """<html><head><title>Audio Engineering BA | Test University</title></head><body>
      <a href="/partnerships">Industry Partnerships</a><a href="mailto:partners@test.edu">email</a>
      <p>Our audio engineering and music production degree covers mixing and mastering.</p>
      <p>Industry relations manager: partners@test.edu</p></body></html>"""
    page = parse_page("https://www.test.edu/audio", html)
    assert "partners@test.edu" in page["emails"]
    assert any(url.endswith("/partnerships") for url, _ in page["links"])
    assert score_link("https://www.test.edu/partnerships", "Industry Partnerships") > score_link("https://www.test.edu/news", "News")

    data = validate(extract_with_rules("test.edu", [page]), [page])
    assert data["relevance"] >= 3
    assert data["contacts"][0]["role"] == "partnerships"
    assert data["name"] == "Test University"


def test_render_template():
    tpl = db.DEFAULT_TEMPLATE
    contact = {"name": "Dr. Maria Lopez", "title": "Program Director", "institution": "Test University",
               "programs": "BA Audio Engineering; Music Production", "country": "Spain"}
    subject, body = outreach.render(tpl, contact)
    assert "Test University" in subject
    assert body.startswith("Dear Dr. Maria Lopez,")
    assert "Test University's BA Audio Engineering and Music Production and" in body

    _, body = outreach.render(tpl, {"name": "", "institution": "X"})
    assert body.startswith("Hello,")


def test_build_queries():
    qs = pipeline.build_queries(["foley"], ["UK", "Japan"], {"Japan": ["音響 専門学校"]})
    assert qs == [
        {"query": "foley university UK", "region": "UK"},
        {"query": "foley university Japan", "region": "Japan"},
        {"query": "音響 専門学校", "region": "Japan"},
    ]
    assert pipeline.build_queries(["foley"], []) == [{"query": "foley university", "region": ""}]


def test_regional_keywords_from_db():
    conn = db.connect(":memory:")
    for k in db.list_keywords(conn):
        db.delete_keyword(conn, k["id"])
    db.add_keyword(conn, "audio engineering degree")
    db.add_keyword(conn, "Tontechnik Studium", region="Germany", language="German", source="suggested")
    db.add_keyword(conn, "Tontechnik Studium", region="Austria")  # same phrase, other country is fine
    assert not db.add_keyword(conn, "tontechnik studium", region="Germany")
    qs = [q["query"] for q in pipeline.queries_from_db(conn, ["Germany", "UK"])]
    assert qs == ["audio engineering degree university Germany", "Tontechnik Studium",
                  "audio engineering degree university UK"]
    assert len(db.list_keywords(conn, region="Germany")) == 1


def test_prefilter_rules():
    from scraper import config, prefilter
    assert prefilter.rule_verdict("salford.ac.uk", {"title": "News", "url": "https://salford.ac.uk/news"}) == "yes"
    assert prefilter.rule_verdict("thomann.de", {"title": "Best 10 audio interfaces for students", "description": ""}) == "no"
    assert prefilter.rule_verdict("pointblankmusicschool.com",
                                  {"title": "Music Production & Sound Engineering Diploma", "description": ""}) == "yes"
    assert prefilter.rule_verdict("example.com", {"title": "Audio engineering in Berlin", "description": ""}) == "maybe"
    old = config.ANTHROPIC_API_KEY
    config.ANTHROPIC_API_KEY = ""  # no AI: uncertain results are kept, not dropped
    try:
        keep, skipped = prefilter.screen([
            ("thomann.de", {"title": "Best 10 audio interfaces", "description": ""}),
            ("example.com", {"title": "Audio engineering in Berlin", "description": ""}),
        ])
    finally:
        config.ANTHROPIC_API_KEY = old
    assert [d for d, _ in keep] == ["example.com"] and [d for d, _ in skipped] == ["thomann.de"]


class _Req:
    def __init__(self, value=None, error=None):
        self.value, self.error = value, error

    def execute(self):
        if self.error:
            raise self.error
        return self.value


class FakeGmail:
    """Just enough of the Gmail API for check_gmail."""
    def __init__(self, drafts, search_results):
        self._drafts, self._search = drafts, search_results

    def users(self):
        return self

    def drafts(self):
        return self

    def messages(self):
        return self

    def get(self, userId, id, format=None):
        if id in self._drafts:
            return _Req({"id": id})
        if id.startswith("msg"):
            return _Req({"internalDate": "1790000000000"})
        from googleapiclient.errors import HttpError
        resp = type("R", (), {"status": 404, "reason": "Not Found"})()
        return _Req(error=HttpError(resp, b"not found"))

    def list(self, userId, q, maxResults):
        hits = [v for k, v in self._search.items() if k in q]
        return _Req({"messages": hits[0]} if hits else {})


def test_check_gmail_tracking(monkeypatch):
    conn = db.connect(":memory:")
    db.save_institution(conn, {"domain": "a.edu", "name": "A"}, [
        {"name": "Still Draft", "email": "draft@a.edu"},
        {"name": "Sent Draft", "email": "sent@a.edu"},
    ])
    db.save_institution(conn, {"domain": "b.edu", "name": "B"}, [
        {"name": "Replier", "email": "r@b.edu"},
        {"name": "Bouncer", "email": "gone@b.edu"},
    ])
    ids = {c["email"]: c["id"] for c in db.list_contacts(conn)}
    db.record_outreach(conn, ids["draft@a.edu"], "draft", "d1", "s")
    db.record_outreach(conn, ids["sent@a.edu"], "draft", "d2", "s")
    db.record_outreach(conn, ids["r@b.edu"], "sent", "m1", "s")
    db.record_outreach(conn, ids["gone@b.edu"], "sent", "m2", "s")
    fake = FakeGmail(drafts={"d1"}, search_results={
        "in:sent to:sent@a.edu": [{"id": "msg-sent"}],
        "from:(r@b.edu": [{"id": "msg-reply"}],
        '"gone@b.edu"': [{"id": "msg-bounce"}],
    })
    monkeypatch.setattr(outreach, "_service", lambda: fake)
    changes = dict(outreach.check_gmail(conn, log=lambda m: None))
    status = {c["email"]: c["outreach_status"] for c in db.list_contacts(conn)}
    assert status == {"draft@a.edu": "Draft created", "sent@a.edu": "Email sent",
                      "r@b.edu": "Replied", "gone@b.edu": "Bounced"}
    assert ids["draft@a.edu"] not in changes
    inst = {i["domain"]: i["status"] for i in db.list_institutions(conn)}
    assert inst == {"a.edu": "Contacted", "b.edu": "Replied"}
    assert db.get_contact(conn, ids["r@b.edu"])["last_reply_at"].startswith("2026")


def test_recheck_rules():
    hit_news = {"url": "https://x.ac.uk/news/1", "title": "Campus news", "description": ""}
    hit_prog = {"url": "https://x.ac.uk/courses/audio-engineering", "title": "BSc Audio Engineering", "description": ""}
    assert pipeline.should_process(None, hit_news)
    assert not pipeline.should_process({"outcome": "saved", "attempts": 1, "last_url": ""}, hit_prog)
    assert not pipeline.should_process({"outcome": "blocked", "attempts": 1, "last_url": ""}, hit_prog)
    assert pipeline.should_process({"outcome": "error", "attempts": 2, "last_url": ""}, hit_news)
    assert not pipeline.should_process({"outcome": "error", "attempts": 3, "last_url": ""}, hit_news)
    rejected = {"outcome": "not_relevant", "attempts": 1, "last_url": hit_news["url"]}
    assert not pipeline.should_process(rejected, hit_news)       # same page again
    assert pipeline.should_process(rejected, hit_prog)           # new, audio-looking page
    assert pipeline.audio_score(hit_prog) > pipeline.audio_score(hit_news)


def test_attempts_counter_and_hosted_sites():
    conn = db.connect(":memory:")
    db.mark_domain_seen(conn, "x.edu", "error", "timeout", "https://x.edu/a")
    db.mark_domain_seen(conn, "x.edu", "not_relevant", "r0", "https://x.edu/b")
    st = db.domain_status(conn, "x.edu")
    assert st["attempts"] == 2 and st["outcome"] == "not_relevant" and st["last_url"] == "https://x.edu/b"
    assert registered_domain("https://audioschool.wixsite.com/home") != registered_domain("https://other.wixsite.com/")


def test_program_phrase_not_doubled():
    assert outreach._program_phrase("BSc Audio Engineering") == "BSc Audio Engineering"
    assert outreach._program_phrase("Audio Production Program") == "Audio Production Program"
    assert outreach._program_phrase("Sound Design") == "Sound Design program"
