"""Scope change detection via JSON snapshot diffing."""

import hashlib
import json


class ChangeEvent:
    """Represents a detected change in a bug bounty program."""

    __slots__ = ("platform", "handle", "name", "url", "event_type",
                 "details", "program_data")

    def __init__(self, platform, handle, name, url, event_type, details, program_data):
        self.platform = platform
        self.handle = handle
        self.name = name
        self.url = url
        self.event_type = event_type
        self.details = details  # dict with change-specific info
        self.program_data = program_data  # full current program dict

    def __repr__(self):
        return f"ChangeEvent({self.platform}/{self.handle}: {self.event_type})"


def _program_key(program, platform):
    """Extract a stable unique key for a program."""
    if platform == "hackerone":
        return program.get("handle", program.get("name", ""))
    elif platform == "bugcrowd":
        return program.get("url", program.get("name", ""))
    elif platform == "intigriti":
        # Intigriti uses company_handle/program_handle
        company = program.get("company_handle", "")
        handle = program.get("handle", program.get("name", ""))
        return f"{company}/{handle}" if company else handle
    elif platform == "yeswehack":
        return program.get("slug", program.get("title", ""))
    return program.get("name", program.get("handle", str(program)))


def _program_name(program, platform):
    """Extract display name."""
    if platform == "hackerone":
        return program.get("name", program.get("handle", ""))
    elif platform == "bugcrowd":
        return program.get("name", program.get("url", ""))
    elif platform == "intigriti":
        return program.get("name", program.get("handle", ""))
    elif platform == "yeswehack":
        return program.get("title", program.get("slug", ""))
    return program.get("name", "")


def _program_url(program, platform):
    """Extract or construct program URL."""
    if platform == "hackerone":
        handle = program.get("handle", "")
        return program.get("url", f"https://hackerone.com/{handle}")
    elif platform == "bugcrowd":
        return program.get("url", "")
    elif platform == "intigriti":
        return program.get("url", "")
    elif platform == "yeswehack":
        slug = program.get("slug", "")
        return program.get("url", f"https://yeswehack.com/programs/{slug}")
    return program.get("url", "")


def _get_scope(program, platform):
    """Extract in-scope targets as a set of (identifier, type) tuples."""
    targets = set()

    if platform == "hackerone":
        for t in program.get("targets", {}).get("in_scope", []):
            targets.add((t.get("asset_identifier", ""), t.get("asset_type", "")))
    elif platform == "bugcrowd":
        for t in program.get("targets", {}).get("in_scope", []):
            targets.add((t.get("target", ""), t.get("type", "")))
    elif platform == "intigriti":
        for t in program.get("targets", {}).get("in_scope", []):
            targets.add((t.get("endpoint", ""), t.get("type", "")))
    elif platform == "yeswehack":
        for t in program.get("targets", {}).get("in_scope", []):
            targets.add((t.get("target", ""), t.get("type", "")))

    return targets


def _get_max_bounty(program, platform):
    """Extract maximum bounty amount."""
    if platform == "hackerone":
        offers = program.get("targets", {}).get("in_scope", [])
        bounties = []
        for o in offers:
            b = o.get("max_severity_bounty")
            if b:
                try:
                    bounties.append(float(b))
                except (ValueError, TypeError):
                    pass
        if bounties:
            return max(bounties)
        # Try top-level max_bounty
        mb = program.get("max_bounty")
        if mb:
            try:
                return float(mb)
            except (ValueError, TypeError):
                pass
    elif platform in ("bugcrowd", "intigriti", "yeswehack"):
        mb = program.get("max_bounty") or program.get("max_reward")
        if mb:
            try:
                return float(mb)
            except (ValueError, TypeError):
                pass
    return 0


def _scope_hash(scope_set):
    """Hash a scope set for quick comparison."""
    items = sorted(str(s) for s in scope_set)
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()[:16]


def diff_programs(baseline, current, platform):
    """Compare two snapshots and yield ChangeEvents."""
    # Index by stable key
    old_map = {}
    for p in baseline:
        key = _program_key(p, platform)
        if key:
            old_map[key] = p

    new_map = {}
    for p in current:
        key = _program_key(p, platform)
        if key:
            new_map[key] = p

    old_keys = set(old_map.keys())
    new_keys = set(new_map.keys())

    events = []

    # New programs
    for key in new_keys - old_keys:
        prog = new_map[key]
        scope = _get_scope(prog, platform)
        events.append(ChangeEvent(
            platform=platform,
            handle=key,
            name=_program_name(prog, platform),
            url=_program_url(prog, platform),
            event_type="new_program",
            details={
                "scope_count": len(scope),
                "max_bounty": _get_max_bounty(prog, platform),
            },
            program_data=prog,
        ))

    # Removed programs
    for key in old_keys - new_keys:
        prog = old_map[key]
        events.append(ChangeEvent(
            platform=platform,
            handle=key,
            name=_program_name(prog, platform),
            url=_program_url(prog, platform),
            event_type="program_removed",
            details={},
            program_data=prog,
        ))

    # Changed programs
    for key in old_keys & new_keys:
        old_prog = old_map[key]
        new_prog = new_map[key]

        old_scope = _get_scope(old_prog, platform)
        new_scope = _get_scope(new_prog, platform)

        # Scope additions
        added = new_scope - old_scope
        if added:
            events.append(ChangeEvent(
                platform=platform,
                handle=key,
                name=_program_name(new_prog, platform),
                url=_program_url(new_prog, platform),
                event_type="scope_added",
                details={
                    "added_count": len(added),
                    "added_targets": [list(a) for a in list(added)[:10]],
                },
                program_data=new_prog,
            ))

        # Scope removals
        removed = old_scope - new_scope
        if removed:
            events.append(ChangeEvent(
                platform=platform,
                handle=key,
                name=_program_name(new_prog, platform),
                url=_program_url(new_prog, platform),
                event_type="scope_removed",
                details={
                    "removed_count": len(removed),
                    "removed_targets": [list(r) for r in list(removed)[:10]],
                },
                program_data=new_prog,
            ))

        # Bounty changes
        old_bounty = _get_max_bounty(old_prog, platform)
        new_bounty = _get_max_bounty(new_prog, platform)
        if new_bounty > old_bounty and new_bounty > 0:
            events.append(ChangeEvent(
                platform=platform,
                handle=key,
                name=_program_name(new_prog, platform),
                url=_program_url(new_prog, platform),
                event_type="bounty_increased",
                details={
                    "old_bounty": old_bounty,
                    "new_bounty": new_bounty,
                },
                program_data=new_prog,
            ))

    return events


def get_scope_info(program_data, platform):
    """Return scope set and hash for a program."""
    scope = _get_scope(program_data, platform)
    return scope, _scope_hash(scope), len(scope)


def get_max_bounty(program_data, platform):
    return _get_max_bounty(program_data, platform)
