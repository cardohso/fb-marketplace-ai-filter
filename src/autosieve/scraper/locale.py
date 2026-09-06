"""Every user-interface string the scraper keys on, in one place.

The browser context is pinned to pt-PT, so Portuguese comes first. English
variants are kept because Facebook occasionally serves them regardless of the
locale header. When Facebook changes its copy, this is the only file to touch.
"""

from __future__ import annotations

import re

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

# UI labels that show up as short spans inside the details/description area and
# must never be mistaken for content.
UI_LABELS: frozenset[str] = frozenset(
    {
        *SEE_MORE,
        *SEE_LESS,
        *DESCRIPTION_HEADINGS,
        *DETAILS_HEADINGS,
        "Condição",
        "Estado",
        "Condition",
        "Enviar mensagem",
        "Send message",
        "Guardar",
        "Save",
        "Partilhar",
        "Share",
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
    "sponsored",
    "patrocinado",
)


def any_pattern(labels: tuple[str, ...], *, exact: bool = True) -> re.Pattern[str]:
    """A case-insensitive regex matching any of the labels, for Playwright locators."""
    alternatives = "|".join(re.escape(label) for label in labels)
    return re.compile(rf"^(?:{alternatives})$" if exact else alternatives, re.IGNORECASE)
