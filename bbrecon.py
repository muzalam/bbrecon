#!/usr/bin/env python3
"""bbrecon — Bug Bounty Target Discovery Tool.

Tracks changes across HackerOne, Bugcrowd, Intigriti, and YesWeHack
by diffing bounty-targets-data snapshots and scoring programs.
"""

import argparse
import os
import sys

import config
from lib import db, sources, differ, scorer, notify


PLATFORM_ALIASES = {
    "h1": "hackerone",
    "hackerone": "hackerone",
    "bc": "bugcrowd",
    "bugcrowd": "bugcrowd",
    "int": "intigriti",
    "intigriti": "intigriti",
    "ywh": "yeswehack",
    "yeswehack": "yeswehack",
}


def cmd_init(args):
    """Clone repo, create DB, generate config."""
    print("[init] Setting up bbrecon...")

    # Ensure data dir
    data_dir = config.get("data_dir")
    os.makedirs(data_dir, exist_ok=True)

    # Clone or pull repo
    print("[init] Cloning bounty-targets-data...")
    repo = config.repo_dir()
    sources.clone_repo(config.get("repo_url"), repo)
    print(f"  Repo ready at {repo}")

    # Create DB
    print("[init] Creating database...")
    conn = db.connect(config.db_path())
    db.init_schema(conn)
    conn.close()
    print(f"  Database ready at {config.db_path()}")

    # Check Discord
    if config.get("discord_webhook"):
        print("[init] Discord webhook configured")
    else:
        print("[init] No Discord webhook set (export BBRECON_DISCORD_WEBHOOK to enable)")

    print("[init] Done. Run: python3 bbrecon.py scan --dry-run")


def cmd_scan(args):
    """Full pipeline: fetch -> diff -> score -> notify."""
    since = args.since or config.get("default_since")
    min_score = args.min_score if args.min_score is not None else config.get("default_min_score")
    dry_run = args.dry_run

    # Resolve platforms
    if args.platform:
        alias = args.platform.lower()
        if alias not in PLATFORM_ALIASES:
            print(f"Unknown platform: {args.platform}")
            print(f"Valid: {', '.join(sorted(set(PLATFORM_ALIASES.values())))}")
            sys.exit(1)
        platforms = [PLATFORM_ALIASES[alias]]
    else:
        platforms = config.get("platforms")

    repo = config.repo_dir()
    if not os.path.isdir(os.path.join(repo, ".git")):
        print("Repo not found. Run 'python3 bbrecon.py init' first.")
        sys.exit(1)

    # Pull latest
    print(f"[scan] Fetching latest data...")
    sources.pull_repo(repo)
    sources.deepen_history(repo)

    # Connect DB
    conn = db.connect(config.db_path())
    db.init_schema(conn)

    weights = config.get("weights")
    all_scored = []

    for platform in platforms:
        print(f"[scan] Diffing {platform} (since {since})...")
        try:
            baseline, current = sources.get_snapshots(repo, platform, since)
        except Exception as e:
            print(f"  Error reading {platform}: {e}")
            continue

        events = differ.diff_programs(baseline, current, platform)
        print(f"  {len(events)} changes detected")

        for event in events:
            # Score
            score, sub_scores = scorer.score_program(event, weights)

            if score < min_score:
                continue

            # Dedup
            if db.is_duplicate_event(conn, event.platform, event.handle,
                                     event.event_type, event.details):
                continue

            # Persist event
            if not dry_run:
                event_id = db.insert_event(
                    conn, event.platform, event.handle,
                    event.event_type, event.details, score
                )

                # Update program record
                scope, scope_hash, scope_count = differ.get_scope_info(
                    event.program_data, event.platform
                )
                max_bounty = differ.get_max_bounty(event.program_data, event.platform)
                db.upsert_program(
                    conn, event.platform, event.handle,
                    name=event.name, url=event.url,
                    max_bounty=max_bounty, scope_hash=scope_hash,
                    scope_count=scope_count, score=score
                )
            else:
                event_id = None

            all_scored.append((event, score, sub_scores, event_id))

    # Print results
    print_items = [(e, s, ss) for e, s, ss, _ in all_scored]
    notify.print_table(print_items)

    # Notifications
    if not dry_run:
        event_ids = [eid for _, _, _, eid in all_scored if eid]

        # Discord
        if config.get("discord_webhook"):
            unnotified = [(e, s, ss) for e, s, ss, eid in all_scored if eid]
            if unnotified:
                print(f"[scan] Sending {len(unnotified)} notifications to Discord...")
                sent = notify.send_discord(config.get("discord_webhook"), unnotified)
                if sent:
                    print(f"  {sent} Discord notifications sent")

        # Mark all events as notified (prevents duplicates on next run)
        for eid in event_ids:
            db.mark_notified(conn, eid, "console")
    elif dry_run:
        print("[scan] Dry run — no DB updates, no notifications")

    conn.close()


def cmd_list(args):
    """Show top programs from DB."""
    conn = db.connect(config.db_path())
    db.init_schema(conn)

    programs = db.get_top_programs(conn, limit=args.top)
    conn.close()

    if not programs:
        print("No programs in database. Run 'python3 bbrecon.py scan' first.")
        return

    try:
        from rich.console import Console
        from rich.table import Table
        console = Console()
        table = Table(title=f"Top {args.top} Programs")
        table.add_column("Score", justify="right", style="bold")
        table.add_column("Platform", style="cyan")
        table.add_column("Program")
        table.add_column("Bounty", justify="right")
        table.add_column("Scope", justify="right")
        table.add_column("First Seen")
        for p in programs:
            score_style = "green" if p["last_score"] >= 70 else "yellow" if p["last_score"] >= 50 else "dim"
            plat = notify.PLATFORM_SHORT.get(p["platform"], p["platform"])
            bounty = notify._format_bounty(p["max_bounty"]) if p["max_bounty"] else "-"
            table.add_row(
                f"[{score_style}]{p['last_score']:.0f}[/{score_style}]",
                plat,
                p["name"] or p["handle"],
                bounty,
                str(p["scope_count"]),
                (p["first_seen_at"] or "")[:10],
            )
        console.print(table)
    except ImportError:
        header = f"{'Score':>5}  {'Plat':<4}  {'Program':<30}  {'Bounty':>8}  {'Scope':>5}  First Seen"
        print("\n" + header)
        print("-" * len(header))
        for p in programs:
            plat = notify.PLATFORM_SHORT.get(p["platform"], p["platform"])
            bounty = notify._format_bounty(p["max_bounty"]) if p["max_bounty"] else "-"
            name = (p["name"] or p["handle"])[:30]
            print(f"{p['last_score']:5.0f}  {plat:<4}  {name:<30}  {bounty:>8}  {p['scope_count']:>5}  {(p['first_seen_at'] or '')[:10]}")
        print(f"\n  {len(programs)} programs\n")


def main():
    parser = argparse.ArgumentParser(
        prog="bbrecon",
        description="Bug Bounty Target Discovery Tool"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # init
    subparsers.add_parser("init", help="Clone repo, create DB, generate config")

    # scan
    scan_parser = subparsers.add_parser("scan", help="Fetch, diff, score, notify")
    scan_parser.add_argument("--since", type=str, default=None,
                             help="Time window (e.g., 24h, 7d, 1w)")
    scan_parser.add_argument("--platform", type=str, default=None,
                             help="Platform filter (h1, bc, int, ywh)")
    scan_parser.add_argument("--min-score", type=float, default=None,
                             help="Minimum score threshold (0-100)")
    scan_parser.add_argument("--dry-run", action="store_true",
                             help="No notifications, no DB update")

    # list
    list_parser = subparsers.add_parser("list", help="Show top programs from DB")
    list_parser.add_argument("--top", type=int, default=20,
                             help="Number of programs to show")

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "scan":
        cmd_scan(args)
    elif args.command == "list":
        cmd_list(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
