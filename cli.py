"""Command-line interface. Run `python cli.py --help`."""
import argparse
import sys

from scraper import config, db, pipeline, sheets
from scraper.google_auth import get_credentials


def cmd_run(conn, args):
    keywords = args.keyword or [k["keyword"] for k in db.list_keywords(conn, active_only=True)]
    if args.regions == "none":
        regions = []
    elif args.regions:
        regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    else:
        regions = [r["region"] for r in db.list_regions(conn, active_only=True)]
    summary = pipeline.run(conn, keywords, regions, max_new=args.limit, force=args.force)
    print(f"\nSaved {summary['saved']} new schools; {summary['not_relevant']} not relevant; "
          f"{summary['already_known']} already known; {summary['errors']} errors; "
          f"{summary['queries']} searches run, {summary['skipped_queries']} skipped (already run).")
    if not args.no_sync and summary["saved"] and config.GOOGLE_TOKEN.exists():
        n_i, n_c = sheets.sync(conn)
        print(f"Google Sheet: added {n_i} schools, {n_c} contacts. {sheets.sheet_url()}")


def cmd_keywords(conn, args):
    if args.add:
        for k in args.add:
            print(("added: " if db.add_keyword(conn, k) else "already exists: ") + k)
    if args.remove:
        for k in args.remove:
            db.delete_keyword(conn, k)
            print("removed: " + k)
    for k in db.list_keywords(conn):
        print(("  [on]  " if k["active"] else "  [off] ") + k["keyword"])


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

    k = sub.add_parser("keywords", help="list/add/remove keywords")
    k.add_argument("--add", nargs="+")
    k.add_argument("--remove", nargs="+")

    rg = sub.add_parser("regions", help="list/add regions")
    rg.add_argument("--add", nargs="+")

    s = sub.add_parser("sync", help="push new rows to Google Sheets")
    s.add_argument("--pull", action="store_true", help="also pull Status/Notes edits back from the sheet")

    sub.add_parser("google-login", help="connect your Google account (Sheets + Gmail)")
    sub.add_parser("stats", help="show totals")

    args = p.parse_args(argv)
    conn = db.connect()
    handler = {"run": cmd_run, "keywords": cmd_keywords, "regions": cmd_regions, "sync": cmd_sync,
               "google-login": cmd_google_login, "stats": cmd_stats}[args.cmd]
    try:
        handler(conn, args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
