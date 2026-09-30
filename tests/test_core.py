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
    assert pipeline.build_queries(["foley"], ["UK", "Japan"]) == ["foley university UK", "foley university Japan"]
    assert pipeline.build_queries(["foley"], []) == ["foley university"]


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
