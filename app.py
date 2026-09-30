"""Streamlit dashboard. Start with:  .venv/bin/streamlit run app.py"""
import pandas as pd
import streamlit as st

from scraper import config, db, llm, outreach, pipeline, sheets, suggest
from scraper.google_auth import GoogleAuthError, disconnect, get_credentials, is_connected

st.set_page_config(page_title="Naturl Audio - University Finder", layout="wide")


@st.cache_resource
def get_conn():
    return db.connect()


conn = get_conn()

# --- sidebar: setup status ------------------------------------------------------
with st.sidebar:
    st.header("Setup")
    st.write(("✅" if config.BRAVE_API_KEY else "❌") + " Brave Search key")
    st.write(("✅" if config.ANTHROPIC_API_KEY else "⚠️") + " Claude key" +
             ("" if config.ANTHROPIC_API_KEY else " (rules-only mode)"))
    st.write(("✅" if config.SCORECARD_API_KEY else "⚠️") + " College Scorecard key")
    if is_connected():
        st.write("✅ Google account connected")
        if config.GOOGLE_SHEET_ID:
            st.markdown(f"[Open Google Sheet]({sheets.sheet_url()})")
        if st.button("Disconnect Google"):
            disconnect()
            st.rerun()
    else:
        st.write("❌ Google account")
        if st.button("Connect Google account"):
            try:
                get_credentials(interactive=True)
                st.rerun()
            except GoogleAuthError as e:
                st.error(str(e))

    insts = db.list_institutions(conn)
    st.divider()
    st.metric("Schools saved", len(insts))
    st.metric("Domains checked", len(db.list_seen(conn)))

tab_search, tab_schools, tab_outreach, tab_keywords, tab_templates, tab_history = st.tabs(
    ["🔎 Search", "🏫 Schools", "✉️ Outreach", "🏷️ Keywords & Regions", "📝 Templates", "🗂️ Checked domains"]
)

# --- search ---------------------------------------------------------------------
with tab_search:
    st.subheader("Find new schools")
    all_kw = db.list_keywords(conn)
    kw_label = {k["id"]: k["keyword"] + (f"  ·  {k['region']} only" if k["region"] else "") for k in all_kw}
    active_rg = [r["region"] for r in db.list_regions(conn, active_only=True)]
    kws = st.multiselect("Keywords", list(kw_label), format_func=kw_label.get,
                         default=[k["id"] for k in all_kw if k["active"]])
    rgs = st.multiselect("Regions (general keywords are searched once per region; country-specific ones only in their country)",
                         [r["region"] for r in db.list_regions(conn)], default=active_rg)
    c1, c2, c3 = st.columns(3)
    max_new = c1.number_input("Stop after this many new schools", 1, 500, 10)
    force = c2.checkbox("Re-run searches already done", help="Schools already found are still skipped.")
    auto_sync = c3.checkbox("Push results to Google Sheet", value=is_connected(), disabled=not is_connected())
    queries = pipeline.queries_from_db(conn, rgs, keyword_ids=set(kws))
    pending = [q for q in queries if force or not db.query_already_run(conn, q["query"])]
    st.caption(f"{len(queries)} searches, {len(pending)} not run yet.")

    if st.button("Start search", type="primary", disabled=not (kws and config.BRAVE_API_KEY)):
        log_box = st.empty()
        lines = []

        def log(msg):
            lines.append(msg)
            log_box.code("\n".join(lines[-40:]))

        with st.spinner("Searching and reading school websites…"):
            try:
                summary = pipeline.run(conn, queries, max_new=int(max_new), force=force, log=log)
            except Exception as e:
                st.error(f"Search stopped: {e}")
                summary = None
        if summary:
            st.success(f"Saved {summary['saved']} new schools · {summary['not_relevant']} not relevant · "
                       f"{summary['already_known']} already known · {summary['prefiltered']} skipped by prefilter · "
                       f"{summary['errors']} errors")
            if auto_sync and summary["saved"]:
                try:
                    n_i, n_c = sheets.sync(conn)
                    st.success(f"Google Sheet updated: {n_i} schools, {n_c} contacts.")
                except Exception as e:
                    st.error(f"Sheet sync failed: {e}")

# --- schools --------------------------------------------------------------------
with tab_schools:
    insts = db.list_institutions(conn)
    if not insts:
        st.info("No schools yet. Run a search first.")
    else:
        df = pd.DataFrame(insts)
        f1, f2, f3, f4 = st.columns(4)
        countries = f1.multiselect("Country", sorted(df["country"].dropna().unique()))
        sizes = f2.multiselect("Size", sorted(df["size_category"].dropna().unique()))
        bands = f3.multiselect("Tuition", sorted(df["tuition_band"].dropna().unique()))
        min_rel = f4.slider("Min relevance", 0, 5, 3)
        view = df[df["relevance"] >= min_rel]
        if countries:
            view = view[view["country"].isin(countries)]
        if sizes:
            view = view[view["size_category"].isin(sizes)]
        if bands:
            view = view[view["tuition_band"].isin(bands)]
        cols = ["name", "country", "city", "domain", "programs", "relevance", "size_category", "enrollment",
                "tuition", "tuition_currency", "tuition_band", "control", "contact_count", "status", "found_at"]
        st.dataframe(view[cols], width="stretch", hide_index=True)
        st.download_button("Download CSV", view.to_csv(index=False), "schools.csv", "text/csv")

        c1, c2 = st.columns(2)
        if c1.button("Push new rows to Google Sheet", disabled=not is_connected()):
            try:
                n_i, n_c = sheets.sync(conn)
                st.success(f"Added {n_i} schools and {n_c} contacts.")
            except Exception as e:
                st.error(str(e))
        if c2.button("Pull Status/Notes from Google Sheet", disabled=not (is_connected() and config.GOOGLE_SHEET_ID)):
            try:
                st.success(f"Updated {sheets.pull_status(conn)} rows.")
            except Exception as e:
                st.error(str(e))

# --- outreach -------------------------------------------------------------------
with tab_outreach:
    if st.button("🔄 Check Gmail for replies, bounces and sent drafts", disabled=not is_connected()):
        try:
            with st.spinner("Checking Gmail…"):
                changes = outreach.check_gmail(conn, log=lambda m: None)
            for cid, status in changes:
                contact = db.get_contact(conn, cid)
                st.write(f"{contact['institution']} — {contact['email']}: **{status}**")
                if config.GOOGLE_SHEET_ID and contact["synced"]:
                    sheets.mark_outreach(contact)
            st.success(f"{len(changes)} contacts updated." if changes else "No changes.")
        except Exception as e:
            st.error(str(e))
    contacts = [c for c in db.list_contacts(conn) if c["email"]]
    templates = db.list_templates(conn)
    if not contacts:
        st.info("No contacts with email addresses yet.")
    elif not templates:
        st.info("Create a template first.")
    else:
        show_all = st.checkbox("Include contacts already emailed")
        if not show_all:
            contacts = [c for c in contacts if c["outreach_status"] == "Not contacted"]
        labels = {c["id"]: f"{c['institution']} — {c['name'] or '(no name)'}, {c['title'] or c['role']} <{c['email']}>"
                  for c in contacts}
        chosen = st.multiselect("Contacts", list(labels), format_func=labels.get)
        tpl_name = st.selectbox("Template", [t["name"] for t in templates])
        tpl = next(t for t in templates if t["name"] == tpl_name)

        if chosen and len(chosen) == 1:
            contact = db.get_contact(conn, chosen[0])
            subject, body = outreach.render(tpl, contact)
            subject = st.text_input("Subject", subject, key=f"subj{contact['id']}{tpl_name}")
            body = st.text_area("Message", body, height=320, key=f"body{contact['id']}{tpl_name}")
            messages = [(contact, subject, body)]
        elif chosen:
            messages = [(c, *outreach.render(tpl, c)) for c in map(lambda i: db.get_contact(conn, i), chosen)]
            with st.expander(f"Preview first of {len(messages)} messages"):
                st.write(f"**To:** {messages[0][0]['email']}  \n**Subject:** {messages[0][1]}")
                st.text(messages[0][2])
        else:
            messages = []

        if messages:
            picked_domains = [m[0]["domain"] for m in messages]
            dupes = sorted({m[0]["institution"] for m in messages if picked_domains.count(m[0]["domain"]) > 1})
            if dupes:
                st.warning("You picked more than one contact at: " + ", ".join(dupes) +
                           ". Schools usually respond better to one well-targeted email.")
            already = sorted({m[0]["institution"] for m in messages
                              if any(c["domain"] == m[0]["domain"] and c["id"] != m[0]["id"] and
                                     c["outreach_status"] != "Not contacted" for c in db.list_contacts(conn, m[0]["domain"]))})
            if already:
                st.info("Someone else at these schools has already been drafted or emailed: " + ", ".join(already))
            if not is_connected():
                st.warning("Connect your Google account (sidebar) to create drafts or send.")
            c1, c2 = st.columns(2)
            confirm = c2.checkbox(f"I've reviewed these and want to send {len(messages)} email(s) now")
            do_draft = c1.button("Create Gmail draft(s)", type="primary", disabled=not is_connected())
            do_send = c2.button("Send now", disabled=not (is_connected() and confirm))
            if do_draft or do_send:
                for contact, subject, body in messages:
                    try:
                        if do_send:
                            outreach.send(conn, contact, subject, body)
                        else:
                            outreach.create_draft(conn, contact, subject, body)
                        updated = db.get_contact(conn, contact["id"])
                        if config.GOOGLE_SHEET_ID and updated["synced"]:
                            sheets.mark_outreach(updated)
                        st.success(f"{'Sent to' if do_send else 'Draft created for'} {contact['email']}")
                    except Exception as e:
                        st.error(f"{contact['email']}: {e}")

# --- keywords & regions ---------------------------------------------------------
with tab_keywords:
    regions_all = [r["region"] for r in db.list_regions(conn)]
    scope = st.selectbox("Show keywords for", ["All regions (general)"] + regions_all,
                         help="General keywords are searched in every region. Country keywords only in that country.")
    region = "" if scope.startswith("All regions") else scope

    c1, c2 = st.columns([3, 2])
    with c1:
        st.subheader("Keywords" + (f" for {region}" if region else " (all regions)"))
        with st.form("add_kw", clear_on_submit=True):
            new_kw = st.text_input("Add keyword(s), one per line or comma-separated")
            if st.form_submit_button("Add"):
                for k in new_kw.replace("\n", ",").split(","):
                    db.add_keyword(conn, k, region=region)
                st.rerun()
        for k in db.list_keywords(conn, region=region):
            a, b = st.columns([6, 1])
            label = k["keyword"] + (f"  —  {k['note']}" if k["note"] else "") + (" ✨" if k["source"] == "suggested" else "")
            on = a.checkbox(label, value=bool(k["active"]), key=f"kw_{k['id']}")
            if on != bool(k["active"]):
                db.set_keyword_active(conn, k["id"], on)
            if b.button("🗑", key=f"del_{k['id']}"):
                db.delete_keyword(conn, k["id"])
                st.rerun()

    with c2:
        st.subheader("✨ Suggest keywords")
        st.caption("Claude recommends search phrases for a country, in the local language(s), using "
                   "program names already found there as hints.")
        sug_region = st.selectbox("Country", regions_all, index=regions_all.index(region) if region in regions_all else 0)
        n = st.slider("How many", 5, 25, 12)
        if st.button("Get suggestions", disabled=not llm.available()):
            with st.spinner(f"Thinking about how people search for audio programs in {sug_region}…"):
                try:
                    st.session_state["suggestions"] = (sug_region, suggest.suggest_keywords(conn, sug_region, n))
                except Exception as e:
                    st.error(str(e))
        if not llm.available():
            st.info("Needs ANTHROPIC_API_KEY in .env.")
        if "suggestions" in st.session_state:
            s_region, items = st.session_state["suggestions"]
            with st.form("accept_suggestions"):
                st.write(f"Suggestions for **{s_region}**:")
                picked = [s for i, s in enumerate(items)
                          if st.checkbox(f"{s['keyword']}  [{s['language']}] — {s['english_meaning']}",
                                         value=True, key=f"sug_{i}", help=s["why"])]
                if st.form_submit_button("Add selected"):
                    added = suggest.add_suggestions(conn, s_region, picked)
                    del st.session_state["suggestions"]
                    st.success(f"Added {added} keywords for {s_region}.")
                    st.rerun()

    st.divider()
    st.subheader("Regions")
    with st.form("add_rg", clear_on_submit=True):
        new_rg = st.text_input("Add region / country")
        if st.form_submit_button("Add"):
            db.add_region(conn, new_rg)
            st.rerun()
    cols = st.columns(4)
    for i, r in enumerate(db.list_regions(conn)):
        on = cols[i % 4].checkbox(r["region"], value=bool(r["active"]), key=f"rg_{r['region']}")
        if on != bool(r["active"]):
            db.set_region_active(conn, r["region"], on)

# --- templates ------------------------------------------------------------------
with tab_templates:
    templates = db.list_templates(conn)
    names = [t["name"] for t in templates] + ["+ New template"]
    pick = st.selectbox("Template", names)
    current = next((t for t in templates if t["name"] == pick), {"name": "", "subject": "", "body": ""})
    name = st.text_input("Name", current["name"])
    subject = st.text_input("Subject", current["subject"])
    body = st.text_area("Body", current["body"], height=360)
    st.caption("Placeholders: " + " · ".join(f"`{k}` {v}" for k, v in outreach.PLACEHOLDERS.items()))
    c1, c2 = st.columns(2)
    if c1.button("Save template", type="primary", disabled=not name.strip()):
        db.save_template(conn, name, subject, body)
        st.success("Saved.")
        st.rerun()
    if current["name"] and c2.button("Delete template"):
        db.delete_template(conn, current["name"])
        st.rerun()

# --- checked domains ------------------------------------------------------------
with tab_history:
    st.caption("Every website the tool has looked at. These are skipped in future searches.")
    seen = db.list_seen(conn)
    if seen:
        st.dataframe(pd.DataFrame(seen), width="stretch", hide_index=True)
        retry = st.text_input("Domain to check again (e.g. after an error)")
        if st.button("Allow re-check") and retry.strip():
            db.forget_domain(conn, retry.strip().lower())
            st.success(f"{retry} will be processed again next time it appears in search results.")
