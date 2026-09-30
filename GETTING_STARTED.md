# Getting Started

## 1. Start the app

From the project folder:

```bash
.venv/bin/streamlit run app.py
```

Then open http://localhost:8501. The sidebar shows ✅ or ❌ for each key and connection. The app
opens without keys, but it can't search until they're added.

## 2. Add your keys to `.env`

Create it from the example if it doesn't exist yet:

```bash
cp .env.example .env
open -e .env
```

Git ignores `.env`, so your keys are never uploaded to GitHub. Paste each key after its `=` sign
and save.

### Brave Search key (required for searching, free)

1. Go to https://api-dashboard.search.brave.com, sign up, and choose the **Free** plan. It may ask
   for a card, but it isn't charged.
2. Go to **API Keys → Add API key**, copy it, and paste it after `BRAVE_API_KEY=`.

### Anthropic key (needed for reading sites well, keyword suggestions and the prefilter)

1. Go to https://console.anthropic.com, sign in, and add a few dollars of credit under
   **Billing**. $5–10 is plenty for testing.
2. Go to **API Keys → Create Key**, copy it, and paste it after `ANTHROPIC_API_KEY=`.

Without this key the tool still runs, using a free but much less accurate keyword-only mode.

### College Scorecard key (optional, free, for US enrollment and tuition)

1. Go to https://api.data.gov/signup. The key arrives by email instantly.
2. Paste it after `SCORECARD_API_KEY=`.

After saving `.env`, stop the app (Ctrl+C in its terminal) and start it again so it loads the
keys.

## 3. First live test

1. **Keywords & Regions** tab → **✨ Suggest keywords**: pick one country (e.g. Germany) and click
   **Get suggestions**. Tick the ones you like and click **Add selected**.
2. **Search** tab: pick a few keywords and one region, set "Stop after this many new schools" to
   **3**, and click **Start search**.
3. **Schools** tab: check the schools, sizes, tuition and contacts that came back.
4. **Checked domains** tab: see every site that was looked at and why any were skipped.

## 4. Connect Google Sheets and Gmail

This is a one-time Google Cloud setup of about 10 minutes, using your javon@naturl.audio account.
Follow **Google setup** in [README.md](README.md#google-setup-sheets--gmail-one-time-10-minutes),
then click **Connect Google account** in the app's sidebar.

Once connected:
- Search results are added to your Google Sheet automatically. The first sync creates the Sheet
  if `GOOGLE_SHEET_ID` is empty.
- The **Outreach** tab can create Gmail drafts from your templates, or send them.
- **🔄 Check Gmail** finds replies, bounces and drafts you've sent, and updates the Sheet.
