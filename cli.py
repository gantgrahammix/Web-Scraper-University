"""Command-line interface. Run `python cli.py --help`."""
import argparse
import sys

from scraper import config, db, outreach, pipeline, sheets, suggest
from scraper.google_auth import get_credentials


def cmd_run(conn, args):
    if args.regions == "none":
        regions = []
    elif args.regions:
        regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    else:
        regions = [r["region"] for r in db.list_regions(conn, active_only=True)]
    if args.keyword:
        queries = pipeline.build_queries(args.keyword, regions)
    else:
        queries = pipeline.queries_from_db(conn, regions)
    summary = pipeline.run(conn, queries, max_new=args.limit, force=args.force)
    print(f"\nSaved {summary['saved']} new schools; {summary['not_relevant']} not relevant; "
          f"{summary['already_known']} already known; {summary['prefiltered']} skipped by prefilter; "
          f"{summary['errors']} errors; "
          f"{summary['queries']} searches run, {summary['skipped_queries']} skipped (already run).")
    if not args.no_sync and summary["saved"] and config.GOOGLE_TOKEN.exists():
        n_i, n_c = sheets.sync(conn)
        print(f"Google Sheet: added {n_i} schools, {n_c} contacts. {sheets.sheet_url()}")


def cmd_keywords(conn, args):
    region = args.region or ""
    if args.suggest:
        if not region:
            raise SystemExit("--suggest needs --region, e.g. --region Germany")
        suggestions = suggest.suggest_keywords(conn, region, count=args.count)
        for i, s in enumerate(suggestions, 1):
            print(f"  {i:2}. {s['keyword']}  [{s['language']}] = {s['english_meaning']}\n      {s['why']}")
        if args.accept:
            picks = suggestions if args.accept == "all" else [suggestions[int(n) - 1] for n in args.accept.split(",")]
            print(f"Added {suggest.add_suggestions(conn, region, picks)} keywords for {region}.")
        else:
            print("\nRe-run with --accept all (or --accept 1,3,5) to add them.")
        return
    if args.add:
        for k in args.add:
            print(("added: " if db.add_keyword(conn, k, region=region) else "already exists: ") + k)
    if args.remove:
        for k in args.remove:
            kid = db.find_keyword_id(conn, k, region)
            if kid:
                db.delete_keyword(conn, kid)
                print("removed: " + k)
    for k in db.list_keywords(conn, region=region if args.region else None):
        where = f" ({k['region']})" if k["region"] else ""
        note = f"  = {k['note']}" if k["note"] else ""
        print(("  [on]  " if k["active"] else "  [off] ") + k["keyword"] + where + note)


def cmd_regions(conn, args):
    if args.add:
        for r in args.add:
            db.add_region(conn, r)
    for r in db.list_regions(conn):
        print(("  [on]  " if r["active"] else "  [off] ") + r["region"])


def cmd_sync(conn, args):
    n_i, n_c = sheets.sync(conn)
    print(f"Added {n_i} schools and {n_c} contacts. {sheets.sheet_url()}")
    if args.pull:
        print(f"Pulled Status/Notes for {sheets.pull_status(conn)} rows from the sheet.")


def cmd_check_gmail(conn, args):
    changes = outreach.check_gmail(conn)
    print(f"{len(changes)} contacts updated.")
    if config.GOOGLE_SHEET_ID:
        for cid, _ in changes:
            contact = db.get_contact(conn, cid)
            if contact["synced"]:
                sheets.mark_outreach(contact)


def cmd_google_login(conn, args):
    get_credentials(interactive=True)
    print("Google account connected.")


def cmd_stats(conn, args):
    insts = db.list_institutions(conn)
    seen = db.list_seen(conn)
    print(f"Schools saved: {len(insts)}")
    print(f"Contacts: {len(db.list_contacts(conn))}")
    print(f"Domains checked in total: {len(seen)}")
    for outcome in ("not_relevant", "blocked", "error"):
        print(f"  {outcome}: {sum(1 for s in seen if s['outcome'] == outcome)}")


def main(argv=None):
    p = argparse.ArgumentParser(description="Find university audio programs for Naturl Audio partnerships.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="search for new schools")
    r.add_argument("--keyword", "-k", action="append", help="keyword to search (default: all active keywords)")
    r.add_argument("--regions", help="comma-separated regions, or 'none' (default: all active regions)")
    r.add_argument("--limit", type=int, default=25, help="stop after this many new schools (default 25)")
    r.add_argument("--force", action="store_true", help="re-run searches that were already run")
    r.add_argument("--no-sync", action="store_true", help="don't push results to Google Sheets")

    k = sub.add_parser("keywords", help="list/add/remove keywords, or get suggestions for a country")
    k.add_argument("--region", help="work with keywords for one country (default: keywords used everywhere)")
    k.add_argument("--add", nargs="+")
    k.add_argument("--remove", nargs="+")
    k.add_argument("--suggest", action="store_true", help="ask Claude for search phrases for --region")
    k.add_argument("--count", type=int, default=12)
    k.add_argument("--accept", help="with --suggest: 'all' or numbers like 1,3,5")

    rg = sub.add_parser("regions", help="list/add regions")
    rg.add_argument("--add", nargs="+")

    s = sub.add_parser("sync", help="push new rows to Google Sheets")
    s.add_argument("--pull", action="store_true", help="also pull Status/Notes edits back from the sheet")

    sub.add_parser("check-gmail", help="detect replies, bounces and drafts you've sent")
    sub.add_parser("google-login", help="connect your Google account (Sheets + Gmail)")
    sub.add_parser("stats", help="show totals")

    args = p.parse_args(argv)
    conn = db.connect()
    handler = {"run": cmd_run, "keywords": cmd_keywords, "regions": cmd_regions, "sync": cmd_sync,
               "google-login": cmd_google_login, "stats": cmd_stats,
               "check-gmail": cmd_check_gmail}[args.cmd]
    try:
        handler(conn, args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
