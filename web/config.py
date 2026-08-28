"""Runtime configuration, entirely from the environment.

No secret, key, token, address or contact detail is written into this
repository. Everything sensitive or deployment specific is read from the
environment at start up, and the application states plainly when a value is
missing rather than substituting a placeholder that could be mistaken for
real information.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


@dataclass(frozen=True)
class Settings:
    secret_key: str
    secret_key_is_ephemeral: bool

    # Contact details. Deliberately empty by default: an invented address is
    # worse than a visible gap, and the contact page says so.
    contact_email: str | None
    contact_address: str | None
    contact_org: str | None

    # Analytics is opt in and off by default. When it is off the site sets no
    # cookies at all, and the consent banner is not shown, because asking for
    # consent to nothing trains people to dismiss the question.
    analytics_enabled: bool
    analytics_script_url: str | None

    site_origin: str
    debug: bool


    # Limits. Every one of these bounds an attacker controlled quantity.
    rate_limit_per_minute: int
    rate_limit_burst: int
    max_content_length: int
    max_simulation_steps: int


    @property
    def contact_configured(self) -> bool:
        return bool(self.contact_email or self.contact_address)

    @property
    def sets_cookies(self) -> bool:
        """True only when something actually stores state in the browser."""
        return self.analytics_enabled



def load_settings() -> Settings:
    key = os.environ.get("AGGSIM_SECRET_KEY")
    ephemeral = not key
    if ephemeral:
        # A random key per process. Sessions do not survive a restart, which
        # is the correct failure mode: it never silently falls back to a
        # predictable value.
        key = secrets.token_urlsafe(48)

    return Settings(
        secret_key=key,
        secret_key_is_ephemeral=ephemeral,
        contact_email=os.environ.get("AGGSIM_CONTACT_EMAIL") or None,
        contact_address=os.environ.get("AGGSIM_CONTACT_ADDRESS") or None,
        contact_org=os.environ.get("AGGSIM_CONTACT_ORG") or None,
        analytics_enabled=_flag("AGGSIM_ANALYTICS_ENABLED", False),
        analytics_script_url=os.environ.get("AGGSIM_ANALYTICS_SCRIPT_URL") or None,
        site_origin=os.environ.get("AGGSIM_SITE_ORIGIN", "http://localhost:5000").rstrip("/"),
        debug=_flag("AGGSIM_DEBUG", False),
        rate_limit_per_minute=_int("AGGSIM_RATE_LIMIT_PER_MINUTE", 120, 1, 6000),
        rate_limit_burst=_int("AGGSIM_RATE_LIMIT_BURST", 40, 1, 500),
        max_content_length=_int("AGGSIM_MAX_CONTENT_LENGTH", 16 * 1024, 1024, 1024 * 1024),
        max_simulation_steps=_int("AGGSIM_MAX_SIMULATION_STEPS", 40_000, 1000, 400_000),
    )
