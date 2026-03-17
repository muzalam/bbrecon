"""Configuration with env var overrides and sensible defaults."""

import os

CONFIG = {
    # Paths
    "data_dir": os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
    "repo_url": "https://github.com/arkadiyt/bounty-targets-data.git",

    # Scan defaults
    "default_since": "24h",
    "default_min_score": 50,
    "platforms": ["hackerone", "bugcrowd", "intigriti", "yeswehack"],

    # Scoring weights (must sum to 1.0)
    "weights": {
        "new_program": 0.25,
        "scope_change": 0.25,
        "bounty_amount": 0.20,
        "response_metrics": 0.15,
        "low_competition": 0.10,
        "attack_surface": 0.05,
    },

    # Notifications
    "discord_webhook": os.environ.get("BBRECON_DISCORD_WEBHOOK", ""),

    # Optional API tokens
    "h1_username": os.environ.get("BBRECON_H1_USERNAME", ""),
    "h1_token": os.environ.get("BBRECON_H1_TOKEN", ""),
}


def get(key, default=None):
    return CONFIG.get(key, default)


def repo_dir():
    return os.path.join(CONFIG["data_dir"], "bounty-targets-data")


def db_path():
    return os.path.join(CONFIG["data_dir"], "bbrecon.db")
