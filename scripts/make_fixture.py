"""Reduce a saved Marketplace page into a small, committable parser fixture.

    uv run python scripts/make_fixture.py debug_html/1399097965553501.html \
        tests/fixtures/live_moto_honda_hornet.html

The parser only looks at visible text (in document order), ``<h1>``, and
``<img alt src>``. Everything else is removed: scripts, styles, SVG, tracking
attributes, signed query strings on image URLs, and empty wrappers. The script
verifies that the reduced page yields exactly the same text lines as the
original, so a fixture is a faithful stand-in for the live page.

Review the output before committing it. Facebook pages carry other users'
listings in the sidebar and may carry a seller name; strip anything you would
not want in a public repository.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup, Comment, Tag

DROP_TAGS = (
    "script",
    "style",
    "svg",
    "noscript",
    "link",
    "meta",
    "iframe",
    "video",
    "audio",
    "source",
    "template",
    "canvas",
    "input",
    "head",
)
KEEP_ATTRS: dict[str, frozenset[str]] = {
    "img": frozenset({"alt", "src"}),
    "a": frozenset({"href", "role", "aria-label"}),
}
DEFAULT_KEEP = frozenset({"role", "aria-label"})
TEXT_TAGS = ("h1", "h2", "span", "div", "a")


def leaf_lines(soup: BeautifulSoup) -> list[str]:
    """Same walk as autosieve.scraper.page_parser._leaf_lines."""
    texts: list[str] = []
    for el in soup.find_all(TEXT_TAGS):
        if el.find(True) is not None:
            continue
        text = el.get_text(" ", strip=True)
        if text and (not texts or texts[-1] != text):
            texts.append(text)
    return texts


def strip_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def reduce_page(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(DROP_TAGS):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()

    for tag in soup.find_all(True):
        keep = KEEP_ATTRS.get(tag.name, DEFAULT_KEEP)
        for attr in list(tag.attrs):
            if attr not in keep:
                del tag.attrs[attr]
        if tag.name == "img" and isinstance(tag.get("src"), str):
            tag["src"] = strip_query(str(tag["src"]))

    # Drop elements that contribute neither text nor an image, until stable.
    changed = True
    while changed:
        changed = False
        for tag in soup.find_all(True):
            if tag.name in ("img", "html", "body"):
                continue
            if not tag.get_text(strip=True) and tag.find("img") is None:
                tag.decompose()
                changed = True

    # Unwrap attribute-less single-child wrappers; leaf text and order are unchanged.
    changed = True
    while changed:
        changed = False
        for tag in soup.find_all(("div", "span")):
            inside_title = tag.parent is not None and tag.parent.name == "h1"
            if tag.attrs or (tag.name == "span" and inside_title):
                continue
            children = [c for c in tag.children if isinstance(c, Tag) or str(c).strip()]
            if len(children) == 1 and isinstance(children[0], Tag) and children[0].name == "div":
                tag.unwrap()
                changed = True
    return soup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source", type=Path, help="page saved by autosieve scrape --debug-html")
    parser.add_argument("target", type=Path, help="fixture path under tests/fixtures/")
    args = parser.parse_args(argv)

    html = args.source.read_text(encoding="utf-8")
    before = leaf_lines(BeautifulSoup(html, "html.parser"))
    reduced = reduce_page(html)
    output = str(reduced)
    after = leaf_lines(BeautifulSoup(output, "html.parser"))

    if before != after:
        for index, (a, b) in enumerate(zip(before, after, strict=False)):
            if a != b:
                print(f"first divergence at line {index}: {a!r} != {b!r}", file=sys.stderr)
                break
        print(
            f"reduced page is not faithful ({len(before)} vs {len(after)} lines)", file=sys.stderr
        )
        return 1

    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_text(output, encoding="utf-8")
    print(
        f"{args.source.name}: {len(html) / 1024:.0f} KB -> {len(output) / 1024:.0f} KB, "
        f"{len(after)} text lines preserved -> {args.target}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
