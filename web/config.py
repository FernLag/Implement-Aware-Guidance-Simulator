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
import tempfile
from dataclasses import dataclass
from pathlib import Path


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

    # Where contact messages go. Probed for writability at start up, because
    # a serverless or read-only filesystem would otherwise fail at the moment
    # someone presses send, after they had already typed the message.
    message_store: Path | None
    message_store_writable: bool
    # True where the disk survives only until the next deploy or restart, which
    # is the case on every free tier here. Writable is not the same as durable,
    # and the contact page says which one it has.
    storage_ephemeral: bool

    # Limits. Every one of these bounds an attacker controlled quantity.
    rate_limit_per_minute: int
    rate_limit_burst: int
    max_content_length: int
    max_simulation_steps: int

    @property
    def accepts_messages(self) -> bool:
        """False when there is nowhere at all to put a message."""
        return self.message_store_writable

    @property
    def messages_are_durable(self) -> bool:
        return self.message_store_writable and not self.storage_ephemeral

    @property
    def contact_configured(self) -> bool:
        return bool(self.contact_email or self.contact_address)

    @property
    def sets_cookies(self) -> bool:
        """True only when something actually stores state in the browser."""
        return self.analytics_enabled


def _resolve_message_store() -> tuple[Path | None, bool]:
    """Pick a writable location for contact messages, or report that there is none.

    Order: an explicitly configured path, then the local instance directory.
    A temporary directory is deliberately NOT used as a silent fallback: on an
    ephemeral platform that would accept messages and then lose them, which is
    worse than declining to accept them at all.
    """
    configured = os.environ.get("AGGSIM_MESSAGE_STORE")
    candidates = [Path(configured)] if configured else [Path("instance") / "messages.jsonl"]

    for path in candidates:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8"):
                pass
            return path, True
        except OSError:
            continue
    return (Path(configured) if configured else None), False


def load_settings() -> Settings:
    store, writable = _resolve_message_store()

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
        message_store=store,
        message_store_writable=writable,
        storage_ephemeral=_flag("AGGSIM_STORAGE_EPHEMERAL", False),
    )
