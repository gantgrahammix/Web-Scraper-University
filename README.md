# Naturl Audio: University Partnership Finder

Finds universities and schools worldwide with audio engineering, music production, sound design,
foley and post-production programs. For each school it finds the people to contact about an AL-1
Limiter education partnership and records the school's size and tuition. Results go to a Google
Sheet, and you can email contacts from your Gmail (javon@naturl.audio) using templates.

New here? Start with **[GETTING_STARTED.md](GETTING_STARTED.md)**.

## How it works

1. **Search**: general keywords run once per region (e.g. "foley course university Germany").
   Country-specific keywords, often in the local language (e.g. "Tontechnik Studium" for Germany),
   run only in their country. Results come from the Brave Search API, localized to that country.
   Claude can suggest country-specific keywords for you (see below).
2. **Prefilter**: before reading a site, a cheap check looks at each result's address, title and
   snippet. Free rules skip obvious shops, forums, blogs and news. Uncertain results from a search
   are sent together to a small model (Claude Haiku) in one request. A prefilter skip applies to
   that search only; the site can still come in through a later search.
3. **Skip what's known**: every website is reduced to its domain (`music.ox.ac.uk` → `ox.ac.uk`).
   Domains the tool has already looked at are skipped. Searches already run are skipped too,
   unless you tick "Re-run searches".
4. **Read the site**: the page from the search result, plus up to ~8 of the most promising pages
   on the same site (partnerships, contact, faculty, dean, tuition). The crawler respects
   robots.txt and waits between requests.
5. **Extract**: Claude reads the pages and returns the school name, country, relevant programs, a
   relevance score (0–5), and contacts ranked partnerships → program head → dean → department →
   admissions. Emails and phone numbers that don't appear on the pages are discarded. Without a
   Claude key, a basic keyword/regex mode is used instead.
6. **Size & cost**:
   - US schools: enrollment, tuition and public/private status from the U.S. Dept. of Education
     College Scorecard.
   - Other schools: enrollment from Wikidata or the school's own site.
   - Schools are then bucketed into Small / Medium / Large / Very Large and a Low / Mid / High
     tuition band (converted to USD at a rough rate).
7. **Save**: schools go into a local database (`data/finder.db`) and are appended to the Google Sheet.
8. **Reach out**: pick contacts, pick a template, review, then create Gmail drafts (default) or send.
9. **Track**: **Check Gmail** finds drafts you've sent, replies (from the contact or anyone else at
   that school), and bounces. It updates the contact and the school's Status in the Sheet.

## Setup

```bash
# Python 3.12 environment (already created in .venv on this Mac)
~/Library/Python/3.9/bin/uv venv --python 3.12 .venv
~/Library/Python/3.9/bin/uv pip install --python .venv/bin/python -r requirements.txt

cp .env.example .env    # then fill in the keys below
```

| Key | Where | Cost |
|---|---|---|
| `BRAVE_API_KEY` | https://api-dashboard.search.brave.com | Free tier (~2,000 searches/mo) |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com | A few cents per school |
| `SCORECARD_API_KEY` | https://api.data.gov/signup | Free |

### Google setup (Sheets + Gmail, one-time, ~10 minutes)

The tool signs in as **you** (javon@naturl.audio). One login covers both the Sheet and Gmail.

1. Go to https://console.cloud.google.com and create a project (e.g. "University Finder").
2. **APIs & Services → Library**: enable **Gmail API**, **Google Sheets API** and **Google Drive API**.
3. **APIs & Services → OAuth consent screen**:
   - Choose **Internal**. This option exists because naturl.audio is a Google Workspace domain,
     and it means no Google review is needed.
   - If only External is offered, pick it and add javon@naturl.audio under **Test users**.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type **Desktop app**.
   - Download the JSON and save it in this folder as `credentials.json`.
5. Start the app and click **Connect Google account** in the sidebar (or run
   `.venv/bin/python cli.py google-login`). Approve access in the browser window.

If `GOOGLE_SHEET_ID` is blank, the first sync creates a sheet called "Naturl Audio – University
Partnerships" and saves its ID to `.env`. To use an existing sheet, put its ID (the long string in
the sheet's URL) in `GOOGLE_SHEET_ID`.

Permissions requested:
- Sheets
- Drive, limited to files this app creates
- Gmail compose, to create drafts and send
- Gmail read-only, used only by **Check Gmail**. It searches for messages from the schools you've
  contacted and for bounce notices. Nothing is stored except each contact's status and reply date,
  and the tool never changes or deletes mail.

If you signed in before a permission was added, the app will ask you to connect again.

## Using it

### Web app

```bash
.venv/bin/streamlit run app.py
```

- **Search**: choose keywords and regions, set how many new schools to find, and click Start.
- **Schools**: filter by country, size, tuition band and relevance. Export CSV, push to or pull
  from the Google Sheet.
- **Outreach**: **Check Gmail** updates replies, bounces and sent drafts. Select contacts and a template. For a single contact you can edit the message
  before creating the draft. **Create Gmail draft(s)** puts drafts in your Gmail Drafts folder
  to review and send. **Send now** sends immediately and requires ticking a confirmation box
  first.
- **Keywords & Regions**: add new keywords as you discover them, and switch any keyword or
  region on or off. Choose a country to see or add keywords for that country only.
  **✨ Suggest keywords**: Claude recommends search phrases for a country, in the language(s)
  schools there use, with an English meaning for each. It uses program names already found in
  that country as hints, so suggestions improve as you collect schools. Tick the ones you want and
  click **Add selected**.
- **Templates**: write and edit templates. Placeholders: `{greeting}`, `{first_name}`, `{name}`,
  `{title}`, `{institution}`, `{programs}`, `{country}`, `{sender_name}`.
- **Checked domains**: every site the tool has looked at, and why it was skipped. You can allow
  a site to be re-checked, e.g. after an error.

### Command line

```bash
.venv/bin/python cli.py run --limit 20                      # all active keywords × regions
.venv/bin/python cli.py run -k "foley course" --regions UK,Ireland --limit 5
.venv/bin/python cli.py keywords --add "game audio degree" "acoustics degree"
.venv/bin/python cli.py keywords --region Germany --add "Tontechnik Studium"
.venv/bin/python cli.py keywords --region Brazil --suggest             # show suggestions
.venv/bin/python cli.py keywords --region Brazil --suggest --accept all
.venv/bin/python cli.py check-gmail                         # replies, bounces, sent drafts
.venv/bin/python cli.py sync --pull                         # push new rows; pull Status/Notes edits
.venv/bin/python cli.py stats
```

## The Google Sheet

- **Institutions tab**: Name, Country, City, Website, Programs, Relevance, Size Category,
  Enrollment, Tuition, Tuition Band, Public/Private, Found Via, Date Found, **Status** (dropdown),
  **Notes**.
- **Contacts tab**: Institution, Name, Title, Role, Email, Phone, Source URL, Outreach,
  Last Contacted, Last Reply.

The tool only appends new rows. It updates exactly two things itself:
- a contact's Outreach / Last Contacted / Last Reply columns
- the school's Status: New → Contacted when an email is sent, and New/Contacted → Replied when
  someone there replies

Your other edits are never overwritten.

## Notes

- Always check contacts before emailing. Sites go out of date, and the tool only knows what the
  pages say.
- Send in modest batches. Keep the template personal and honest about who you are, and stop
  emailing anyone who asks you to. That keeps your domain's email reputation healthy and
  respects anti-spam rules such as CAN-SPAM in the US and GDPR in the EU/UK.
- Settings in `.env`:
  - `MIN_RELEVANCE` (default 3): how strict the audio-program filter is.
  - `MAX_PAGES_PER_SCHOOL`: how many pages are read per school.
  - `CLAUDE_MODEL` / `CLAUDE_EFFORT`: which Claude model is used, and how much effort it spends
    on each school.
  - `PREFILTER=off`: turns the prefilter off. `PREFILTER_MODEL` sets the model it uses
    (default `claude-haiku-4-5`).

## Tests

```bash
.venv/bin/python -m pytest -q
```
