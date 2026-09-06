"""One-time Facebook login that saves a reusable session.

Facebook hides seller descriptions from logged-out users, so a saved session
makes the scraper far more useful. This opens a visible browser, waits for you
to sign in by hand, and saves only the resulting cookies (Playwright
storage_state). Your credentials are typed into Facebook directly and never
seen or stored by AutoSieve.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import sync_playwright

from autosieve.config import Settings

log = logging.getLogger(__name__)

LOGIN_URL = "https://www.facebook.com/login"
_PROMPT = (
    "\n" + "=" * 64 + "\n  Log into Facebook in the browser window that just opened.\n"
    "  When you can see your feed, come back here and press Enter\n"
    "  to save the session.\n" + "=" * 64 + "\n"
)


def save_session(
    settings: Settings,
    *,
    wait_for_user: Callable[[str], object] = input,
) -> Path:
    """Open a visible browser, let the user log in, and save the session state.

    Returns the path the session was written to. ``wait_for_user`` is injected
    so tests do not block on real stdin.
    """
    target = settings.fb_state_path or Path("fb_state.json")
    with sync_playwright() as playwright:
        launch_options: dict[str, object] = {"headless": False}
        if settings.browser_channel:
            launch_options["channel"] = settings.browser_channel
        browser = playwright.chromium.launch(**launch_options)  # type: ignore[arg-type]
        try:
            context = browser.new_context(locale="pt-PT")
            page = context.new_page()
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            wait_for_user(_PROMPT + "Press Enter once logged in... ")
            target.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(target))
        finally:
            browser.close()
    log.info("Saved Facebook session to %s", target)
    return target
