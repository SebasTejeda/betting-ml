"""Advice engine (spec 003, US4 · plan §7): deterministic rules → reasons with evidence.

Every reason is rendered from a template with exactly the values stored in its ``evidence``,
so every number shown is traceable (`render(reason.template, reason.evidence) == reason.text`).
No certainty language (principle XII): every text goes through `check_language`.
"""

from __future__ import annotations

import operator
import string
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from betting_ml.domain.markets import Market

Stance = Literal["for", "against", "context"]
OPS: dict[str, Callable[[float, float], bool]] = {
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
}
FORM_FIELDS = (
    "n",
    "goals_for_avg",
    "goals_against_avg",
    "xg_for_avg",
    "xg_against_avg",
    "over25_pct",
    "btts_pct",
    "scored_2plus",
    "failed_to_score",
    "clean_sheets",
    "wins",
)


class ForbiddenLanguageError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    metric: str
    op: str
    value: float
    stance: Stance
    text: str


@dataclass(frozen=True)
class AdviceSettings:
    rules: Mapping[str, Sequence[Rule]]
    messages: Mapping[str, str]
    forbidden_words: Sequence[str]
    best_options_enabled: bool = False
    best_options_max: int = 3
    best_options_note: str = ""
    most_likely_max: int = 3
    exclude_above: float = 0.95
    one_per_market: bool = True
    max_reasons: int = 4
    min_reasons_for: int = 1
    ev_warning: float = 0.15


@dataclass(frozen=True)
class Reason:
    stance: Stance
    text: str
    evidence: dict[str, Any]
    template: str = field(repr=False, compare=False, default="")


@dataclass(frozen=True)
class SelectionView:
    """One row of the market table (input of the engine)."""

    market: str
    selection: str
    line: float | None
    label: str
    probability: float
    fair_odds: float
    best_odds: float | None = None
    bookmaker: str | None = None
    ev: float | None = None
    verdict: str = "sin_cuota"  # valor | justo | evitar | sin_cuota
    confidence: str = "media"  # alta | media | baja
    experimental: bool = True


@dataclass(frozen=True)
class MatchContext:
    home_team: str
    away_team: str
    lambda_home: float
    lambda_away: float
    home_form: Mapping[str, Any]  # venue summary of the home team (team_form.FormSummary)
    away_form: Mapping[str, Any]
    cross_league: bool = False


@dataclass(frozen=True)
class AdviceItem:
    selection: SelectionView
    reasons: list[Reason]
    price_comment: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Advice:
    best_options: list[AdviceItem]
    most_likely: list[AdviceItem]
    no_value_message: str | None
    best_options_note: str | None


# ------------------------------------------------------------------------------ language


def check_language(text: str, forbidden: Sequence[str]) -> str:
    lowered = text.lower()
    for word in forbidden:
        w = word.lower()
        if " " in w or not w.isalpha():
            hit = w in lowered
        else:
            hit = w in {t.strip(".,;:!?()¿¡\"'") for t in lowered.split()}
        if hit:
            raise ForbiddenLanguageError(f"certainty language {word!r} in: {text}")
    return text


def render(template: str, values: Mapping[str, Any]) -> str:
    return template.format(**values)


def template_fields(template: str) -> list[str]:
    return [name for _, name, _, _ in string.Formatter().parse(template) if name]


# ------------------------------------------------------------------------------ metrics


def rule_group(market: str, selection: str) -> tuple[str, str | None]:
    """Rule group and the team the selection is about (``home``/``away``/None)."""
    mk = Market(market)
    if mk is Market.TEAM_TOTALS:
        team, side = selection.split("_")
        return ("team_over" if side == "over" else "team_under"), team
    if mk is Market.TOTALS:
        return ("totals_over" if selection == "over" else "totals_under"), None
    if mk is Market.BTTS:
        return ("btts_yes" if selection == "yes" else "btts_no"), None
    if mk in (Market.H2H, Market.DRAW_NO_BET, Market.EUROPEAN_HANDICAP):
        if selection == "draw":
            return "draw", None
        return "team_win", selection
    if mk is Market.DOUBLE_CHANCE:
        dc_team: str | None = {"1X": "home", "X2": "away"}.get(selection)
        return ("team_win", dc_team) if dc_team else ("", None)  # "12": no specific rules
    return "", None


def _form_values(prefix: str, form: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in FORM_FIELDS:
        value = form.get(key)
        if value is None and key == "wins":
            streak = str(form.get("streak") or "")
            value = streak.count("W") if streak else None
        if value is not None and key.endswith("_pct"):
            value = 100.0 * float(value)
        out[f"{prefix}_{key}"] = value
    venue = form.get("venue")
    out[f"{prefix}_venue_text"] = (
        ""
        if form.get("fallback_to_all")
        else {"home": " de local", "away": " de visita"}.get(str(venue), "")
    )
    return out


def selection_metrics(view: SelectionView, ctx: MatchContext) -> dict[str, Any]:
    _, team_side = rule_group(view.market, view.selection)
    team_side = team_side or "home"
    opp_side = "away" if team_side == "home" else "home"
    names = {"home": ctx.home_team, "away": ctx.away_team}
    lambdas = {"home": ctx.lambda_home, "away": ctx.lambda_away}
    forms = {"home": ctx.home_form, "away": ctx.away_form}
    values: dict[str, Any] = {
        "home": ctx.home_team,
        "away": ctx.away_team,
        "team": names[team_side],
        "opp": names[opp_side],
        "lambda_home": ctx.lambda_home,
        "lambda_away": ctx.lambda_away,
        "lambda_total": ctx.lambda_home + ctx.lambda_away,
        "lambda_team": lambdas[team_side],
        "lambda_opp": lambdas[opp_side],
        "lambda_diff": lambdas[team_side] - lambdas[opp_side],
        "lambda_gap": abs(ctx.lambda_home - ctx.lambda_away),
        "lambda_min": min(ctx.lambda_home, ctx.lambda_away),
    }
    for side in ("home", "away"):
        values.update(_form_values(side, forms[side]))
    values.update(_form_values("team", forms[team_side]))
    values.update(_form_values("opp", forms[opp_side]))
    return values


# ------------------------------------------------------------------------------ reasons


def reasons_for(view: SelectionView, ctx: MatchContext, settings: AdviceSettings) -> list[Reason]:
    group, _ = rule_group(view.market, view.selection)
    values = selection_metrics(view, ctx)
    fired: list[Reason] = []
    for rule in settings.rules.get(group, ()):
        metric = values.get(rule.metric)
        if metric is None or not OPS[rule.op](float(metric), rule.value):
            continue
        fields = template_fields(rule.text)
        if any(values.get(f) is None for f in fields):
            continue  # a number the text needs is missing ("sin dato"): the rule does not fire
        evidence = {f: values[f] for f in fields}
        text = check_language(render(rule.text, evidence), settings.forbidden_words)
        fired.append(Reason(rule.stance, text, evidence, rule.text))
    supporting = [r for r in fired if r.stance == "for"]
    against = [r for r in fired if r.stance == "against"]
    context: list[Reason] = []
    if ctx.cross_league:
        text = settings.messages["cross_league"]
        context.append(
            Reason(
                "context",
                check_language(text, settings.forbidden_words),
                {"cross_league": True},
                text,
            )
        )
    room = settings.max_reasons - len(context)
    chosen = supporting[: max(room - min(len(against), 1), settings.min_reasons_for)]
    chosen += against[: max(room - len(chosen), 0)]
    return (chosen + context)[: settings.max_reasons]


# ------------------------------------------------------------------------------ price comment


def _pct(p: float) -> str:
    return f"{100 * p:.0f} %"


def _qualifier(p: float) -> str:
    if p >= 0.75:
        return "Muy probable"
    if p >= 0.55:
        return "Probable"
    return "Posible"


def price_comment(view: SelectionView, settings: AdviceSettings) -> str:
    """Probability + price + verdict in one sentence (most likely is never "best")."""
    head = f"{_qualifier(view.probability)} ({_pct(view.probability)})"
    if view.best_odds is None or view.ev is None:
        text = (
            f"{head}. Sin cuota disponible: la cuota justa es {view.fair_odds:.2f}; "
            "solo tendría valor si te pagan más que eso."
        )
    elif view.verdict == "evitar":
        text = (
            f"{head}, pero la cuota {view.best_odds:.2f} paga menos de lo justo "
            f"({view.fair_odds:.2f}): EV {100 * view.ev:+.1f} %. No conviene."
        )
    elif view.verdict == "justo":
        text = (
            f"{head} y la cuota {view.best_odds:.2f} está cerca de lo justo "
            f"({view.fair_odds:.2f}): EV {100 * view.ev:+.1f} %. Sin ventaja clara."
        )
    else:
        text = (
            f"{head} y la cuota {view.best_odds:.2f} paga más de lo justo "
            f"({view.fair_odds:.2f}): EV {100 * view.ev:+.1f} %. {settings.messages['experimental']}."
        )
    return check_language(text, settings.forbidden_words)


def _warnings(view: SelectionView, settings: AdviceSettings) -> list[str]:
    out = []
    if view.ev is not None and view.ev > settings.ev_warning:
        out.append(settings.messages["ev_warning"])
    if view.confidence == "baja":
        out.append(settings.messages["low_confidence"])
    return out


# ------------------------------------------------------------------------------ engine


def build_advice(
    views: Sequence[SelectionView], ctx: MatchContext, settings: AdviceSettings
) -> Advice:
    usable = [v for v in views if v.confidence in ("alta", "media")]

    def item(view: SelectionView) -> AdviceItem:
        reasons = reasons_for(view, ctx, settings)
        if not any(r.stance == "for" for r in reasons) and view.verdict == "valor":
            msg = settings.messages["price_only"]
            reasons = [*reasons, Reason("context", msg, {}, msg)]
        return AdviceItem(view, reasons, price_comment(view, settings), _warnings(view, settings))

    best: list[AdviceItem] = []
    no_value: str | None = None
    note: str | None = None
    if settings.best_options_enabled:
        candidates = sorted(
            (v for v in usable if v.verdict == "valor" and v.ev is not None),
            key=lambda v: v.ev or 0.0,
            reverse=True,
        )
        best = [item(v) for v in candidates[: settings.best_options_max]]
        if not best:
            no_value = settings.messages["no_value"]
    else:
        note = settings.best_options_note.strip() or None

    likely: list[AdviceItem] = []
    seen: set[str] = set()
    for view in sorted(usable, key=lambda v: v.probability, reverse=True):
        if view.probability > settings.exclude_above:
            continue
        if settings.one_per_market and view.market in seen:
            continue
        likely.append(item(view))
        seen.add(view.market)
        if len(likely) >= settings.most_likely_max:
            break
    return Advice(best, likely, no_value, note)
