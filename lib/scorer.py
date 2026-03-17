"""Composite scoring engine — 6 signals, configurable weights."""

import math


def _score_new_program(event):
    """Binary: 100 if new, 0 if not."""
    return 100 if event.event_type == "new_program" else 0


def _score_scope_change(event):
    """Scaled by assets added: 1->40, 5+->100."""
    if event.event_type not in ("scope_added", "new_program"):
        return 0
    count = event.details.get("added_count", event.details.get("scope_count", 0))
    if count == 0:
        return 0
    if count >= 5:
        return 100
    # Linear scale: 1->40, 2->55, 3->70, 4->85, 5->100
    return min(100, 40 + (count - 1) * 15)


def _score_bounty(event):
    """Log-scaled: $100->25, $1k->50, $10k->75, $100k->100."""
    bounty = event.details.get("max_bounty", 0) or event.details.get("new_bounty", 0)
    if bounty <= 0:
        return 0
    # log10 scale: 2(100)->25, 3(1k)->50, 4(10k)->75, 5(100k)->100
    log_val = math.log10(max(1, bounty))
    score = (log_val - 1) * 25  # $10->0, $100->25, $1k->50
    return max(0, min(100, score))


def _score_response_metrics(event):
    """Neutral (50) without API data. With enrichment, uses H1 efficiency."""
    enrichment = event.details.get("enrichment", {})
    if not enrichment:
        return 50  # Neutral score without API data

    # H1 response efficiency (if available from API enrichment)
    efficiency = enrichment.get("response_efficiency_percentage")
    if efficiency is not None:
        speed = enrichment.get("average_speed_days", 30)
        speed_factor = max(0.5, min(1.5, 30 / max(1, speed)))
        return min(100, efficiency * speed_factor)

    return 50


def _score_competition(event):
    """New=90, large scope=60, small=20. Better with API data."""
    if event.event_type == "new_program":
        return 90  # New programs = low competition

    scope_count = event.details.get("scope_count", 0)
    if scope_count == 0:
        # Check program data for scope
        scope_count = event.details.get("added_count", 0)

    if scope_count >= 10:
        return 60  # Large scope = more room
    elif scope_count >= 3:
        return 40
    return 20


def _score_attack_surface(event):
    """Wildcards x 20 + APIs x 15 + total x 2, capped at 100."""
    program = event.program_data
    if not program:
        return 30  # Default

    # Count target types
    in_scope = program.get("targets", {}).get("in_scope", [])
    wildcards = 0
    apis = 0
    total = len(in_scope)

    for target in in_scope:
        identifier = (target.get("asset_identifier", "") or
                      target.get("target", "") or
                      target.get("endpoint", ""))
        asset_type = (target.get("asset_type", "") or
                      target.get("type", "")).lower()

        if "*" in identifier:
            wildcards += 1
        if "api" in asset_type or "api" in identifier.lower():
            apis += 1

    score = wildcards * 20 + apis * 15 + total * 2
    return min(100, max(0, score))


def score_program(event, weights=None):
    """Compute composite score 0-100 for a change event."""
    if weights is None:
        weights = {
            "new_program": 0.25,
            "scope_change": 0.25,
            "bounty_amount": 0.20,
            "response_metrics": 0.15,
            "low_competition": 0.10,
            "attack_surface": 0.05,
        }

    sub_scores = {
        "new_program": _score_new_program(event),
        "scope_change": _score_scope_change(event),
        "bounty_amount": _score_bounty(event),
        "response_metrics": _score_response_metrics(event),
        "low_competition": _score_competition(event),
        "attack_surface": _score_attack_surface(event),
    }

    total = sum(sub_scores[k] * weights[k] for k in weights)
    return round(total, 1), sub_scores
