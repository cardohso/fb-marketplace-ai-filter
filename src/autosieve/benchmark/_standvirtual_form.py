"""Playwright form-filling for the Standvirtual Avaliador.

Kept apart from the provider because it is browser- and site-specific: it cannot
be unit-tested and it will break when Standvirtual changes its markup. Ported
from the project's original ``benchmarker.py``; the selectors and cascading
order are preserved.
"""

from __future__ import annotations

import logging
from typing import Any

from autosieve.benchmark.standvirtual import AVALIADOR_URL, Valuation, parse_valuation
from autosieve.parsing.normalize import fold

log = logging.getLogger(__name__)

SHORT_WAIT_MS = 300
STEP_WAIT_MS = 800
SETTLE_MS = 2000


def _dismiss_cookies(page: Any) -> None:
    try:
        button = page.locator('button:has-text("Aceitar"), button:has-text("Accept")')
        if button.count() > 0:
            button.first.click()
            page.wait_for_timeout(1000)
    except Exception:
        log.debug("no cookie banner on Standvirtual", exc_info=True)


def _fill_dropdown(page: Any, label_text: str, value: str | None, timeout: int = 5000) -> bool:
    """Fill a searchable Standvirtual dropdown by its label. Fuzzy-matches options."""
    if not value:
        return False
    try:
        label = page.locator(f'label:has-text("{label_text}")')
        if label.count() == 0:
            log.warning("Standvirtual label %r not found", label_text)
            return False
        container = label.locator("xpath=following-sibling::div").first
        inp = container.locator("input").first
        inp.wait_for(state="attached", timeout=timeout)
        if inp.is_disabled():
            page.wait_for_timeout(1000)
            if inp.is_disabled():
                log.warning("Standvirtual input for %r is disabled", label_text)
                return False
        inp.click()
        page.wait_for_timeout(SHORT_WAIT_MS)
        inp.fill(value)
        page.wait_for_timeout(STEP_WAIT_MS)

        # Compare accent- and case-folded, so "Serie 3" matches "Série 3".
        wanted = fold(value)
        visible = [o for o in page.locator('div[role="option"]').all() if o.is_visible()]
        for option in visible:  # exact match first
            if fold(option.inner_text()) == wanted:
                option.click()
                page.wait_for_timeout(SHORT_WAIT_MS)
                return True
        for option in visible:  # then fuzzy
            text = fold(option.inner_text())
            if wanted in text or text in wanted:
                option.click()
                page.wait_for_timeout(SHORT_WAIT_MS)
                return True
        if visible:
            visible[0].click()
            page.wait_for_timeout(SHORT_WAIT_MS)
            return True
        inp.press("Escape")
        return False
    except Exception:
        log.warning("failed to fill Standvirtual dropdown %r", label_text, exc_info=True)
        return False


def _select_first_option(page: Any, input_name: str) -> bool:
    try:
        inp = page.locator(f'input[name="{input_name}"]')
        if inp.count() == 0 or inp.is_disabled():
            return False
        inp.click()
        page.wait_for_timeout(500)
        for option in page.locator('div[role="option"]').all():
            if option.is_visible():
                option.click()
                page.wait_for_timeout(SHORT_WAIT_MS)
                return True
        inp.press("Escape")
        return False
    except Exception:
        log.warning("failed to select first option for %r", input_name, exc_info=True)
        return False


def fill_valuation_form(
    page: Any,
    *,
    make: str,
    model: str,
    year: int,
    fuel: str | None,
    gearbox: str | None,
    kms: int,
) -> Valuation | None:
    """Drive the two-step Avaliador form and return the parsed price range."""
    page.goto(AVALIADOR_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(SETTLE_MS)
    _dismiss_cookies(page)

    # Step 1: year and brand, then continue.
    _fill_dropdown(page, "Ano (obrigatório)", str(year))
    page.wait_for_timeout(500)
    _fill_dropdown(page, "Marca (obrigatório)", make)
    page.wait_for_timeout(500)
    continuar = page.locator('button:has-text("Continuar")')
    if continuar.count() == 0:
        log.warning("Standvirtual 'Continuar' not found")
        return None
    continuar.first.click()
    page.wait_for_timeout(SETTLE_MS)

    # Step 2: cascading model -> fuel -> kms -> power -> capacity -> gearbox.
    _fill_dropdown(page, "Modelo (obrigatório)", model)
    page.wait_for_timeout(1000)
    _fill_dropdown(page, "Combustível (obrigatório)", fuel)
    page.wait_for_timeout(500)
    try:
        page.fill('input[name="mileage"]', str(kms))
        page.wait_for_timeout(SHORT_WAIT_MS)
    except Exception:
        log.warning("failed to fill Standvirtual mileage", exc_info=True)
    _select_first_option(page, "engine_power")
    page.wait_for_timeout(500)
    _select_first_option(page, "engine_capacity")
    page.wait_for_timeout(500)
    _fill_dropdown(page, "Tipo de Caixa (obrigatório)", gearbox or "Manual")
    page.wait_for_timeout(500)
    page.keyboard.press("Escape")
    page.wait_for_timeout(SHORT_WAIT_MS)

    try:
        particular = page.locator('button:has-text("Particular")')
        if particular.count() > 0:
            particular.first.click(force=True)
            page.wait_for_timeout(SHORT_WAIT_MS)
    except Exception:
        log.debug("no 'Particular' seller toggle", exc_info=True)

    submit = page.locator('button:has-text("Obtenha uma avaliação")')
    if submit.count() == 0:
        log.warning("Standvirtual submit button not found")
        return None
    submit.first.click()
    page.wait_for_timeout(5000)

    valuation = parse_valuation(page.inner_text("body"))
    if valuation is None:
        log.warning("Standvirtual price range not found for %s %s %s", make, model, year)
    return valuation
