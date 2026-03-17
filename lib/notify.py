"""Console output + Discord webhook notifications."""

import json
import urllib.request
import urllib.error

# Try rich for nicer tables, fall back to plain text
try:
    from rich.console import Console
    from rich.table import Table
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


PLATFORM_SHORT = {
    "hackerone": "H1",
    "bugcrowd": "BC",
    "intigriti": "INT",
    "yeswehack": "YWH",
}

EVENT_LABELS = {
    "new_program": "NEW",
    "scope_added": "SCOPE+",
    "scope_removed": "SCOPE-",
    "bounty_increased": "BOUNTY+",
    "program_removed": "REMOVED",
}


def _format_bounty(amount):
    if amount >= 1000:
        return f"${amount / 1000:.0f}k"
    elif amount > 0:
        return f"${amount:.0f}"
    return "-"


def print_table(events_with_scores):
    """Print a console table of scored events."""
    if not events_with_scores:
        print("No changes detected.")
        return

    if HAS_RICH:
        _print_rich_table(events_with_scores)
    else:
        _print_plain_table(events_with_scores)


def _print_rich_table(events_with_scores):
    console = Console()
    table = Table(title="bbrecon — Target Changes", show_lines=False)
    table.add_column("Score", justify="right", style="bold")
    table.add_column("Platform", style="cyan")
    table.add_column("Event", style="yellow")
    table.add_column("Program")
    table.add_column("Bounty", justify="right")
    table.add_column("Details")

    for event, score, _ in sorted(events_with_scores, key=lambda x: -x[1]):
        score_style = "green" if score >= 70 else "yellow" if score >= 50 else "dim"
        plat = PLATFORM_SHORT.get(event.platform, event.platform)
        ev_label = EVENT_LABELS.get(event.event_type, event.event_type)
        bounty = _format_bounty(
            event.details.get("max_bounty", 0) or
            event.details.get("new_bounty", 0)
        )
        detail = _event_detail(event)

        table.add_row(
            f"[{score_style}]{score:.0f}[/{score_style}]",
            plat, ev_label, event.name or event.handle,
            bounty, detail,
        )

    console.print(table)
    console.print(f"\n  {len(events_with_scores)} changes detected\n")


def _print_plain_table(events_with_scores):
    header = f"{'Score':>5}  {'Plat':<4}  {'Event':<8}  {'Program':<30}  {'Bounty':>8}  Details"
    print("\n" + header)
    print("-" * len(header))

    for event, score, _ in sorted(events_with_scores, key=lambda x: -x[1]):
        plat = PLATFORM_SHORT.get(event.platform, event.platform)
        ev_label = EVENT_LABELS.get(event.event_type, event.event_type)
        bounty = _format_bounty(
            event.details.get("max_bounty", 0) or
            event.details.get("new_bounty", 0)
        )
        detail = _event_detail(event)
        name = (event.name or event.handle)[:30]
        print(f"{score:5.0f}  {plat:<4}  {ev_label:<8}  {name:<30}  {bounty:>8}  {detail}")

    print(f"\n  {len(events_with_scores)} changes detected\n")


def _event_detail(event):
    """One-line summary of what changed."""
    d = event.details
    if event.event_type == "new_program":
        return f"{d.get('scope_count', 0)} targets"
    elif event.event_type == "scope_added":
        targets = d.get("added_targets", [])
        if targets:
            first = targets[0][0] if isinstance(targets[0], list) else str(targets[0])
            more = f" +{len(targets) - 1}" if len(targets) > 1 else ""
            return f"{first}{more}"
        return f"+{d.get('added_count', 0)} targets"
    elif event.event_type == "scope_removed":
        return f"-{d.get('removed_count', 0)} targets"
    elif event.event_type == "bounty_increased":
        return f"{_format_bounty(d.get('old_bounty', 0))} -> {_format_bounty(d.get('new_bounty', 0))}"
    return ""


def send_discord(webhook_url, events_with_scores, max_embeds=10):
    """Send scored events to Discord webhook. Returns count sent."""
    if not webhook_url:
        return 0

    items = sorted(events_with_scores, key=lambda x: -x[1])[:max_embeds]
    embeds = []

    for event, score, sub_scores in items:
        plat = PLATFORM_SHORT.get(event.platform, event.platform)
        ev_label = EVENT_LABELS.get(event.event_type, event.event_type)
        bounty = _format_bounty(
            event.details.get("max_bounty", 0) or
            event.details.get("new_bounty", 0)
        )
        detail = _event_detail(event)
        color = 0x00FF00 if score >= 70 else 0xFFAA00 if score >= 50 else 0x888888

        embed = {
            "title": f"[{plat}] {event.name or event.handle}",
            "url": event.url if event.url and event.url.startswith("http") else None,
            "color": color,
            "fields": [
                {"name": "Event", "value": ev_label, "inline": True},
                {"name": "Score", "value": str(int(score)), "inline": True},
                {"name": "Bounty", "value": bounty, "inline": True},
                {"name": "Details", "value": detail or "-", "inline": False},
            ],
        }
        # Remove None url
        embed = {k: v for k, v in embed.items() if v is not None}
        embeds.append(embed)

    if not embeds:
        return 0

    payload = json.dumps({
        "username": "bbrecon",
        "content": f"**{len(events_with_scores)} target changes detected**",
        "embeds": embeds,
    }).encode()

    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        urllib.request.urlopen(req, timeout=15)
        return len(embeds)
    except urllib.error.URLError as e:
        print(f"  Discord webhook failed: {e}")
        return 0
