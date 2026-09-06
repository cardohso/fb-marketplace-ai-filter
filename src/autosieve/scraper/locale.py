"""Every user-interface string the scraper keys on, in one place.

The browser context is pinned to pt-PT, so Portuguese comes first. English
variants are kept because Facebook occasionally serves them regardless of the
locale header. When Facebook changes its copy, this is the only file to touch.

Observed listing-page structure (anonymous session, September 2026)::

    <h1>title</h1>
    "3600 €" or "GRÁTIS"
    "há 9 minutos"
    "Odivelas, Lisboa"
    Mensagem / Guardar / Partilhar
    "Descrição do vendedor"
    optional label/value pairs, e.g. "Estado" / "Usado - Como novo"
    the description, as one text node
    "Ver menos" (or "Ver mais" when collapsed)
    location again, Mensagem
    "As escolhas de hoje" and other listings with their own prices
"""

from __future__ import annotations

import re

from autosieve.parsing.normalize import fold

DESCRIPTION_HEADINGS: tuple[str, ...] = (
    "Descrição do vendedor",
    "Seller's description",
    "Descrição",
    "Description",
)
DETAILS_HEADINGS: tuple[str, ...] = (
    "Detalhes",
    "Details",
    "Sobre este veículo",
    "About this vehicle",
)
SEE_MORE: tuple[str, ...] = ("Ver mais", "See more")
SEE_LESS: tuple[str, ...] = ("Ver menos", "See less")
PRODUCT_PHOTO_ALT_PREFIXES: tuple[str, ...] = ("Foto de produto", "Product photo")
PROFILE_PHOTO_MARKERS: tuple[str, ...] = ("perfil", "profile")
COOKIE_DECLINE_LABELS: tuple[str, ...] = (
    "Recusar cookies opcionais",
    "Recusar",
    "Decline optional cookies",
    "Decline",
)
CLOSE_LABELS: tuple[str, ...] = ("Fechar", "Close")
LISTING_UNAVAILABLE_MARKERS: tuple[str, ...] = (
    "Este conteúdo não está disponível",
    "Esta página não está disponível",
    "This content isn't available",
    "This page isn't available",
    "O artigo já não está disponível",
    "This listing is no longer available",
)
DRIVEN_PREFIXES: tuple[str, ...] = ("Percorreu", "Conduzido", "Driven")

# Price line alternatives that mean "no price": folded (lowercase, no accents).
FREE_PRICE_LABELS_FOLDED: frozenset[str] = frozenset({"gratis", "free", "troca", "a combinar"})

# "há 9 minutos", "Publicado há 2 horas", "Listed 3 days ago": folded prefixes.
POSTED_AGO_PREFIXES_FOLDED: tuple[str, ...] = ("ha ", "publicado", "listed", "posted")

# Label lines that precede a value line inside the description block. Folded.
ATTRIBUTE_LABELS_FOLDED: frozenset[str] = frozenset(
    {
        "estado",
        "condicao",
        "condition",
        "marca",
        "make",
        "modelo",
        "model",
        "ano",
        "year",
        "quilometragem",
        "mileage",
        "combustivel",
        "fuel type",
        "transmissao",
        "transmission",
        "cor exterior",
        "exterior color",
        "cor interior",
        "interior color",
        "tipo de carroceria",
        "body style",
        "tipo de veiculo",
        "vehicle type",
    }
)

# Lines that end the seller's description.
DESCRIPTION_STOP_LABELS: frozenset[str] = frozenset(
    {
        *SEE_MORE,
        *SEE_LESS,
        "Mensagem",
        "Enviar mensagem",
        "Message",
        "Send message",
        "Guardar",
        "Save",
        "Partilhar",
        "Share",
        "As escolhas de hoje",
        "Seleções de hoje",
        "Today's picks",
        "Informações do vendedor",
        "Seller information",
        "Detalhes do vendedor",
        "Seller details",
    }
)
LOCATION_APPROXIMATE_MARKERS_FOLDED: tuple[str, ...] = (
    "localizacao e aproximada",
    "location is approximate",
)

# UI labels that show up as short spans and must never be mistaken for content.
UI_LABELS: frozenset[str] = frozenset(
    {
        *DESCRIPTION_STOP_LABELS,
        *DESCRIPTION_HEADINGS,
        *DETAILS_HEADINGS,
        "Condição",
        "Estado",
        "Condition",
    }
)

# Text that marks a span as sidebar/boilerplate rather than the seller's prose.
BOILERPLATE_KEYWORDS: tuple[str, ...] = (
    "cookie",
    "facebook",
    "publicidade",
    "anúncio",
    "centro de contas",
    "publicado",
    "localização",
    "enviar mensagem",
    "saiba mais",
    "seleções de hoje",
    "escolhas de hoje",
    "sponsored",
    "patrocinado",
)


def is_free_price(text: str) -> bool:
    return fold(text) in FREE_PRICE_LABELS_FOLDED


def is_posted_ago(text: str) -> bool:
    return fold(text).startswith(POSTED_AGO_PREFIXES_FOLDED)


def is_attribute_label(text: str) -> bool:
    return len(text) <= 25 and fold(text).rstrip(":") in ATTRIBUTE_LABELS_FOLDED


def is_location_footer(text: str) -> bool:
    folded = fold(text)
    return any(marker in folded for marker in LOCATION_APPROXIMATE_MARKERS_FOLDED)


def any_pattern(labels: tuple[str, ...], *, exact: bool = True) -> re.Pattern[str]:
    """A case-insensitive regex matching any of the labels, for Playwright locators."""
    alternatives = "|".join(re.escape(label) for label in labels)
    return re.compile(rf"^(?:{alternatives})$" if exact else alternatives, re.IGNORECASE)
