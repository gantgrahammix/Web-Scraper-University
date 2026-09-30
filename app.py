"""Streamlit dashboard. Start with:  .venv/bin/streamlit run app.py"""
import pandas as pd
import streamlit as st

from scraper import config, db, outreach, pipeline, sheets
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
    active_kw = [k["keyword"] for k in db.list_keywords(conn, active_only=True)]
    active_rg = [r["region"] for r in db.list_regions(conn, active_only=True)]
    kws = st.multiselect("Keywords", [k["keyword"] for k in db.list_keywords(conn)], default=active_kw)
    rgs = st.multiselect("Regions (each keyword is searched once per region)",
                         [r["region"] for r in db.list_regions(conn)], default=active_rg)
    c1, c2, c3 = st.columns(3)
    max_new = c1.number_input("Stop after this many new schools", 1, 500, 10)
    force = c2.checkbox("Re-run searches already done", help="Schools already found are still skipped.")
    auto_sync = c3.checkbox("Push results to Google Sheet", value=is_connected(), disabled=not is_connected())
    queries = pipeline.build_queries(kws, rgs)
    pending = [q for q in queries if force or not db.query_already_run(conn, q)]
    st.caption(f"{len(queries)} searches, {len(pending)} not run yet.")

    if st.button("Start search", type="primary", disabled=not (kws and config.BRAVE_API_KEY)):
        log_box = st.empty()
        lines = []

        def log(msg):
            lines.append(msg)
            log_box.code("\n".join(lines[-40:]))

        with st.spinner("Searching and reading school websites…"):
            try:
                summary = pipeline.run(conn, kws, rgs, max_new=int(max_new), force=force, log=log)
            except Exception as e:
                st.error(f"Search stopped: {e}")
                summary = None
        if summary:
            st.success(f"Saved {summary['saved']} new schools · {summary['not_relevant']} not relevant · "
                       f"{summary['already_known']} already known · {summary['errors']} errors")
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
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Keywords")
        with st.form("add_kw", clear_on_submit=True):
            new_kw = st.text_input("Add keyword(s), one per line or comma-separated")
            if st.form_submit_button("Add"):
                for k in new_kw.replace("\n", ",").split(","):
                    db.add_keyword(conn, k)
                st.rerun()
        for k in db.list_keywords(conn):
            a, b = st.columns([5, 1])
            on = a.checkbox(k["keyword"], value=bool(k["active"]), key=f"kw_{k['keyword']}")
            if on != bool(k["active"]):
                db.set_keyword_active(conn, k["keyword"], on)
            if b.button("🗑", key=f"del_{k['keyword']}"):
                db.delete_keyword(conn, k["keyword"])
                st.rerun()
    with c2:
        st.subheader("Regions")
        with st.form("add_rg", clear_on_submit=True):
            new_rg = st.text_input("Add region / country")
            if st.form_submit_button("Add"):
                db.add_region(conn, new_rg)
                st.rerun()
        for r in db.list_regions(conn):
            on = st.checkbox(r["region"], value=bool(r["active"]), key=f"rg_{r['region']}")
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
