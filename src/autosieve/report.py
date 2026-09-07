"""Rank scored listings and render them as a terminal table or an HTML page."""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime

from autosieve.benchmark import BenchmarkProvider
from autosieve.duediligence import DueDiligence, build_due_diligence
from autosieve.geo import distance_from
from autosieve.identity import resolve_identity
from autosieve.models import Analysis, Listing
from autosieve.scoring import DealScore, ScoreStatus, score_listing
from autosieve.storage import Store


@dataclass(frozen=True, slots=True)
class ReportRow:
    listing: Listing
    score: DealScore
    make: str | None
    model: str | None
    year: int | None
    notes: str | None
    due: DueDiligence

    @property
    def is_scored(self) -> bool:
        return self.score.is_scored


@dataclass
class Report:
    rows: list[ReportRow] = field(default_factory=list)
    generated_at: datetime | None = None
    benchmark_source: str = "seed"

    @property
    def scored(self) -> list[ReportRow]:
        return [r for r in self.rows if r.is_scored]

    @property
    def unscored(self) -> list[ReportRow]:
        return [r for r in self.rows if not r.is_scored]

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.rows:
            counts[row.score.status.value] = counts.get(row.score.status.value, 0) + 1
        return counts


def _row(listing: Listing, analysis: Analysis | None, score: DealScore) -> ReportRow:
    resolved = resolve_identity(listing, analysis)
    return ReportRow(
        listing=listing,
        score=score,
        make=resolved.make,
        model=resolved.model,
        year=resolved.year,
        notes=analysis.notes if analysis and analysis.notes else None,
        due=build_due_diligence(listing, analysis, kms=score.kms),
    )


def build_report(
    store: Store,
    provider: BenchmarkProvider,
    *,
    reference_year: int | None = None,
    origin: tuple[float, float] | None = None,
) -> Report:
    """Score every stored listing and rank scored ones best-first.

    ``origin`` enables distance-to-origin weighting in the score.
    """
    rows: list[ReportRow] = []
    for listing, record in store.iter_listings_with_analysis():
        analysis = record.analysis if record else None
        distance = distance_from(listing.location, origin) if origin is not None else None
        score = score_listing(
            listing, analysis, provider, reference_year=reference_year, distance_km=distance
        )
        rows.append(_row(listing, analysis, score))

    # Best deal first; confidence breaks ties. Unscored listings sink to the end.
    rows.sort(
        key=lambda r: (
            r.is_scored,
            r.score.score or 0.0,
            r.score.confidence,
        ),
        reverse=True,
    )
    return Report(rows=rows, generated_at=datetime.now().astimezone())


# ── Terminal ─────────────────────────────────────────────────────────────────


def _fmt_eur(value: int | None) -> str:
    return f"{value:,}".replace(",", ".") if value is not None else "-"


def _fmt_km(value: int | None) -> str:
    return f"{value:,}".replace(",", ".") if value is not None else "-"


def _fmt_dist(value: float | None) -> str:
    return f"{value:.0f}km" if value is not None else "-"


def render_terminal(report: Report, *, top: int = 20) -> str:
    lines: list[str] = []
    scored = report.scored[:top]
    if scored:
        lines.append(
            f"{'#':>2}  {'score':>5} {'conf':>4}  {'price':>8} {'market':>8}  "
            f"{'km':>7} {'dist':>6}  vehicle"
        )
        lines.append("-" * 84)
        for rank, row in enumerate(scored, start=1):
            s = row.score
            vehicle = " ".join(filter(None, [row.make, row.model, str(row.year or "")])).strip()
            flag = " [dealer]" if s.is_dealer else ""
            lines.append(
                f"{rank:>2}  {s.score:>5.2f} {s.confidence:>4.2f}  "
                f"{_fmt_eur(s.price_eur):>8} {_fmt_eur(s.benchmark_median):>8}  "
                f"{_fmt_km(s.kms):>7} {_fmt_dist(s.distance_km):>6}  {vehicle[:30]}{flag}"
            )
    else:
        lines.append("No listings could be scored yet.")

    counts = report.status_counts()
    scored_n = counts.get(ScoreStatus.SCORED.value, 0)
    lines.append("")
    lines.append(
        f"{scored_n} scored, "
        f"{counts.get(ScoreStatus.NO_BENCHMARK.value, 0)} no benchmark, "
        f"{counts.get(ScoreStatus.NO_PRICE.value, 0)} no/placeholder price, "
        f"{counts.get(ScoreStatus.NON_VEHICLE.value, 0)} non-vehicle"
    )
    return "\n".join(lines)


# ── HTML ─────────────────────────────────────────────────────────────────────


def _score_class(score: float) -> str:
    if score >= 1.15:
        return "great"
    if score >= 1.03:
        return "good"
    if score >= 0.95:
        return "fair"
    return "poor"


def render_html(report: Report) -> str:
    generated = report.generated_at.strftime("%Y-%m-%d %H:%M") if report.generated_at else ""
    body: list[str] = []
    for rank, row in enumerate(report.scored, start=1):
        s = row.score
        assert s.score is not None
        vehicle = html.escape(
            " ".join(filter(None, [row.make, row.model, str(row.year or "")])).strip() or "?"
        )
        title = html.escape(row.listing.title or "")
        url = html.escape(row.listing.url, quote=True)
        reasons = html.escape("; ".join(s.reasons)) if s.reasons else ""
        notes = html.escape(row.notes or "")
        dealer = '<span class="tag">dealer</span>' if s.is_dealer else ""
        checklist = "".join(
            f"<li>{html.escape(item.question)}"
            + (f" <em>{html.escape(item.cost_hint)}</em>" if item.cost_hint else "")
            + "</li>"
            for item in row.due.items
        )
        due_block = (
            f"<details class='due'><summary>Before you buy ({len(row.due.items)})</summary>"
            f"<ul>{checklist}</ul></details>"
            if checklist
            else ""
        )
        body.append(
            f"<tr class='{_score_class(s.score)}'>"
            f"<td class='rank'>{rank}</td>"
            f"<td class='score'>{s.score:.2f}</td>"
            f"<td class='conf'>{s.confidence:.2f}</td>"
            f"<td class='num'>{_fmt_eur(s.price_eur)} €</td>"
            f"<td class='num'>{_fmt_eur(s.benchmark_median)} €</td>"
            f"<td class='num'>{_fmt_km(s.kms)}</td>"
            f"<td><a href='{url}' target='_blank' rel='noopener'>{vehicle}</a>{dealer}"
            f"<div class='title'>{title}</div>"
            f"<div class='reasons'>{reasons}</div>"
            f"<div class='notes'>{notes}</div>{due_block}</td>"
            "</tr>"
        )

    counts = report.status_counts()
    summary = html.escape(
        f"{counts.get('scored', 0)} scored · "
        f"{counts.get('no_benchmark', 0)} no benchmark · "
        f"{counts.get('no_price', 0)} no/placeholder price · "
        f"{counts.get('non_vehicle', 0)} non-vehicle"
    )
    rows_html = "\n".join(body) or "<tr><td colspan='7'>No scored listings.</td></tr>"
    return _HTML_TEMPLATE.format(
        generated=html.escape(generated),
        summary=summary,
        rows=rows_html,
        source=html.escape(report.benchmark_source),
    )


_HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AutoSieve deals</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 15px/1.5 system-ui, sans-serif; margin: 0; padding: 1.5rem;
         background: #f6f7f9; color: #1a1a1a; }}
  @media (prefers-color-scheme: dark) {{ body {{ background:#16181c; color:#e7e9ee; }} }}
  h1 {{ font-size: 1.3rem; margin: 0 0 .25rem; }}
  .meta {{ color: #6b7280; font-size: .85rem; margin-bottom: 1rem; }}
  table {{ border-collapse: collapse; width: 100%; background: transparent; }}
  th, td {{ text-align: left; padding: .5rem .6rem; vertical-align: top;
           border-bottom: 1px solid #d7dae0; }}
  @media (prefers-color-scheme: dark) {{ th, td {{ border-color:#2a2e37; }} }}
  th {{ font-size: .75rem; text-transform: uppercase; letter-spacing: .04em; color: #6b7280; }}
  td.num, td.score, td.conf, td.rank {{ text-align: right; white-space: nowrap;
           font-variant-numeric: tabular-nums; }}
  td.score {{ font-weight: 700; }}
  tr.great td.score {{ color: #0a7d2e; }}
  tr.good  td.score {{ color: #2f8f3f; }}
  tr.fair  td.score {{ color: #b7791f; }}
  tr.poor  td.score {{ color: #b91c1c; }}
  .title {{ font-size: .85rem; color: #6b7280; }}
  .reasons {{ font-size: .78rem; color: #8a8f98; margin-top: .15rem; }}
  .notes {{ font-size: .8rem; margin-top: .2rem; }}
  .due {{ font-size: .8rem; margin-top: .35rem; }}
  .due summary {{ cursor: pointer; color: #6b7280; }}
  .due ul {{ margin: .3rem 0 0; padding-left: 1.1rem; }}
  .due li {{ margin: .15rem 0; }}
  .due em {{ color: #b7791f; font-style: normal; }}
  .tag {{ display:inline-block; margin-left:.4rem; padding:0 .4rem; border-radius:.6rem;
          font-size:.7rem; background:#b91c1c; color:#fff; vertical-align:middle; }}
  a {{ color: inherit; font-weight: 600; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
</style></head>
<body>
  <h1>AutoSieve deals</h1>
  <div class="meta">Generated {generated} · {summary}<br>
    benchmark source: {source} — seed values, verify before trusting</div>
  <table>
    <thead><tr>
      <th>#</th><th>Score</th><th>Conf</th><th>Price</th><th>Market</th><th>km</th><th>Vehicle</th>
    </tr></thead>
    <tbody>
{rows}
    </tbody>
  </table>
</body></html>
"""
