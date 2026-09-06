"""Drive a real Chromium through Facebook Marketplace and hand back raw HTML.

Everything here is deliberately thin: navigate, dismiss dialogs, wait for the
element we need, return ``page.content()``. Parsing lives in
:mod:`autosieve.scraper.page_parser` where it can be tested without a browser.

Waits are condition-based. A fixed ``wait_for_timeout`` is only used as a
short settle after a click, never as a substitute for waiting on an element.
"""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Self

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from autosieve.config import Settings
from autosieve.parsing.urls import canonical_listing_url, extract_listing_id
from autosieve.scraper import locale
from autosieve.scraper.errors import LoginWallError, ScrapeError

log = logging.getLogger(__name__)

ITEM_LINK_SELECTOR = "a[href*='/marketplace/item/']"
CLOSE_BUTTON_SELECTOR = ", ".join(f"div[aria-label='{label}']" for label in locale.CLOSE_LABELS)
MAX_SCROLLS = 8
CLICK_TIMEOUT_MS = 2_500
SETTLE_MS = 400


class MarketplaceBrowser:
    """A context-managed Playwright session pointed at Marketplace.

    Usage::

        with MarketplaceBrowser(settings) as browser:
            ids = browser.collect_listing_ids(limit=20)
            html = browser.fetch_listing_html(ids[0])
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    # ── lifecycle ────────────────────────────────────────────────────────────

    def __enter__(self) -> Self:
        self._playwright = sync_playwright().start()
        launch_options: dict[str, object] = {"headless": self._settings.headless}
        if self._settings.browser_channel:
            # Drive a system-installed Chrome/Edge instead of the bundled Chromium.
            launch_options["channel"] = self._settings.browser_channel
        self._browser = self._playwright.chromium.launch(**launch_options)  # type: ignore[arg-type]
        context_options: dict[str, object] = {"locale": "pt-PT"}
        state = self._settings.fb_state_path
        if state is not None and state.exists():
            # Reuse a saved login so gated seller descriptions load.
            context_options["storage_state"] = str(state)
            log.info("Using saved Facebook session: %s", state)
        else:
            log.warning(
                "No saved Facebook session; seller descriptions may be hidden. "
                "Run `autosieve login` to sign in once."
            )
        geo = self._settings.geolocation
        if geo is not None:
            context_options["geolocation"] = {"latitude": geo[0], "longitude": geo[1]}
            context_options["permissions"] = ["geolocation"]
        self._context = self._browser.new_context(**context_options)  # type: ignore[arg-type]
        self._context.set_default_timeout(self._settings.page_timeout_ms)
        self._page = self._context.new_page()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer is not None:
                    closer.close()
            except PlaywrightError:  # already gone; nothing to clean up
                log.debug("ignoring error while closing browser resources", exc_info=True)
        if self._playwright is not None:
            self._playwright.stop()

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("MarketplaceBrowser must be used as a context manager")
        return self._page

    # ── navigation ───────────────────────────────────────────────────────────

    def open_marketplace(self) -> None:
        """Load the vehicles feed for the configured city and get past the dialogs."""
        url = self._settings.marketplace_url
        log.info("Opening %s", url)
        self.page.goto(url, wait_until="domcontentloaded")
        self._raise_if_login_wall()
        self._dismiss_cookies()
        self._dismiss_overlay()
        try:
            self.page.wait_for_selector(ITEM_LINK_SELECTOR, timeout=self._settings.page_timeout_ms)
        except PlaywrightTimeoutError as exc:
            self._raise_if_login_wall()
            raise ScrapeError("no listings rendered on the Marketplace feed") from exc

    def collect_listing_ids(self, limit: int) -> list[str]:
        """Unique item ids from the feed, scrolling to load more until ``limit`` is met."""
        ids: list[str] = []
        seen: set[str] = set()
        for _ in range(MAX_SCROLLS + 1):
            for anchor in self.page.query_selector_all(ITEM_LINK_SELECTOR):
                href = anchor.get_attribute("href") or ""
                listing_id = extract_listing_id(href)
                if listing_id and listing_id not in seen:
                    seen.add(listing_id)
                    ids.append(listing_id)
                    if len(ids) >= limit:
                        return ids
            before = len(ids)
            self.page.mouse.wheel(0, 2_500)
            self.page.wait_for_timeout(SETTLE_MS * 3)
            if len(ids) == before and self._no_new_links():
                break
        return ids

    def _no_new_links(self) -> bool:
        try:
            self.page.wait_for_function(
                "(n) => document.querySelectorAll(\"a[href*='/marketplace/item/']\").length > n",
                arg=len(self.page.query_selector_all(ITEM_LINK_SELECTOR)),
                timeout=CLICK_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError:
            return True
        return False

    def fetch_listing_html(self, listing_id: str) -> str:
        """Open one listing, expand its description, and return the page HTML.

        Never raises for a missing title: the parser decides whether the page
        is an unavailable listing or just an unexpected layout.
        """
        url = canonical_listing_url(listing_id)
        self.page.goto(url, wait_until="domcontentloaded")
        self._raise_if_login_wall()
        self._dismiss_overlay()
        try:
            self.page.wait_for_selector("h1", timeout=self._settings.listing_timeout_ms)
        except PlaywrightTimeoutError:
            log.debug("no <h1> on listing %s within timeout", listing_id)
        self._expand_see_more()
        return self.page.content()

    # ── dialogs ──────────────────────────────────────────────────────────────

    def _raise_if_login_wall(self) -> None:
        if "/login" in self.page.url or "/checkpoint" in self.page.url:
            raise LoginWallError(f"Facebook redirected to {self.page.url}")

    def _dismiss_cookies(self) -> None:
        button = self.page.get_by_role(
            "button", name=locale.any_pattern(locale.COOKIE_DECLINE_LABELS, exact=False)
        ).first
        try:
            button.click(timeout=self._settings.listing_timeout_ms)
            self.page.wait_for_timeout(SETTLE_MS)
            log.debug("declined optional cookies")
        except PlaywrightTimeoutError:
            log.debug("no cookie banner")

    def _dismiss_overlay(self) -> None:
        try:
            self.page.locator(CLOSE_BUTTON_SELECTOR).first.click(timeout=CLICK_TIMEOUT_MS)
            self.page.wait_for_timeout(SETTLE_MS)
            log.debug("closed overlay")
        except PlaywrightTimeoutError:
            pass

    def _expand_see_more(self) -> None:
        buttons = self.page.get_by_text(locale.any_pattern(locale.SEE_MORE))
        try:
            count = min(buttons.count(), 3)
        except PlaywrightError:
            return
        for index in range(count):
            try:
                buttons.nth(index).click(timeout=CLICK_TIMEOUT_MS)
            except PlaywrightError:
                continue
        if count:
            self.page.wait_for_timeout(SETTLE_MS)
