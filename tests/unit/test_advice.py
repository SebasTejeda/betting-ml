import re
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from betting_ml.config import load_advice
from betting_ml.domain.advice import (
    ForbiddenLanguageError,
    MatchContext,
    SelectionView,
    build_advice,
    check_language,
    price_comment,
    reasons_for,
    render,
    rule_group,
)

SETTINGS = load_advice().to_settings()
STRONG_HOME = {
    "n": 6, "goals_for_avg": 2.4, "goals_against_avg": 0.8, "xg_for_avg": 2.2, "xg_against_avg": 0.9,
    "over25_pct": 0.67, "btts_pct": 0.5, "scored_2plus": 5, "failed_to_score": 0, "clean_sheets": 2,
    "streak": "WWDWWW", "venue": "home", "fallback_to_all": False,
}  # fmt: skip
LEAKY_AWAY = {
    "n": 6, "goals_for_avg": 1.2, "goals_against_avg": 1.7, "xg_for_avg": None, "xg_against_avg": None,
    "over25_pct": 0.5, "btts_pct": 0.5, "scored_2plus": 1, "failed_to_score": 2, "clean_sheets": 1,
    "streak": "LDWLLD", "venue": "away", "fallback_to_all": False,
}  # fmt: skip
CTX = MatchContext("Real Madrid", "RB Leipzig", 2.05, 1.12, STRONG_HOME, LEAKY_AWAY)


def _view(**kw: object) -> SelectionView:
    base = dict(
        market="team_totals", selection="home_over", line=1.5, label="Real Madrid más de 1.5 goles",
        probability=0.642, fair_odds=1 / 0.642, best_odds=1.95, bookmaker="betsson",
        ev=0.642 * 1.95 - 1, verdict="valor", confidence="media",
    )  # fmt: skip
    base.update(kw)
    return SelectionView(**base)  # type: ignore[arg-type]


def test_rule_groups() -> None:
    assert rule_group("team_totals", "away_under") == ("team_under", "away")
    assert rule_group("totals", "over") == ("totals_over", None)
    assert rule_group("h2h", "away") == ("team_win", "away")
    assert rule_group("draw_no_bet", "home") == ("team_win", "home")
    assert rule_group("double_chance", "X2") == ("team_win", "away")
    assert rule_group("double_chance", "12") == ("", None)
    assert rule_group("h2h", "draw") == ("draw", None)
    assert rule_group("correct_score", "2-1") == ("", None)


def test_reasons_match_the_spec_example_and_are_traceable() -> None:
    reasons = reasons_for(_view(), CTX, SETTINGS)
    texts = [r.text for r in reasons]
    assert "El modelo espera 2.0 goles de Real Madrid en este partido." in texts
    assert "Real Madrid marcó 2 o más en 5 de sus últimos 6 partidos de local." in texts
    assert "RB Leipzig recibe 1.7 goles por partido de visita en sus últimos 6." in texts
    for reason in reasons:
        # Every data number in the text comes from the evidence: re-rendering the template with
        # the evidence alone gives the same text (the template only adds fixed wording such as
        # "2 o más").
        assert render(reason.template, reason.evidence) == reason.text
        data_numbers = re.findall(r"\d+(?:\.\d+)?", re.sub(r"\{[^}]*\}", "", reason.template))
        assert set(data_numbers) <= {"2", "2.5"}


def test_at_most_four_reasons_with_at_least_one_for_and_against_shown() -> None:
    against_ctx = replace(CTX, away_form={**LEAKY_AWAY, "clean_sheets": 4}, cross_league=True)
    reasons = reasons_for(_view(), against_ctx, SETTINGS)
    assert len(reasons) <= 4
    stances = [r.stance for r in reasons]
    assert "for" in stances and "against" in stances and stances[-1] == "context"
    assert "Partido entre ligas" in reasons[-1].text


def test_missing_data_does_not_fire_rules() -> None:
    no_form = replace(CTX, home_form={"n": 0, "venue": "home"}, away_form={"n": 0, "venue": "away"})
    reasons = reasons_for(_view(), no_form, SETTINGS)
    assert [r.text for r in reasons] == [
        "El modelo espera 2.0 goles de Real Madrid en este partido."
    ]


@pytest.mark.parametrize(
    ("view", "expected"),
    [
        (
            _view(
                market="double_chance",
                selection="1X",
                line=None,
                label="Real Madrid o empate",
                probability=0.821,
                fair_odds=1.22,
                best_odds=1.15,
                ev=0.821 * 1.15 - 1,
                verdict="evitar",
            ),
            "Muy probable (82 %), pero la cuota 1.15 paga menos de lo justo (1.22): EV -5.6 %. No conviene.",
        ),
        (
            _view(best_odds=None, ev=None, verdict="sin_cuota"),
            "Probable (64 %). Sin cuota disponible: la cuota justa es 1.56; solo tendría valor si te pagan más que eso.",
        ),
        (
            _view(probability=0.5, fair_odds=2.0, best_odds=2.02, ev=0.01, verdict="justo"),
            "Posible (50 %) y la cuota 2.02 está cerca de lo justo (2.00): EV +1.0 %. Sin ventaja clara.",
        ),
    ],
)
def test_price_comment(view: SelectionView, expected: str) -> None:
    assert price_comment(view, SETTINGS) == expected


def test_value_comment_is_labelled_experimental_and_high_ev_warned() -> None:
    advice_settings = replace(SETTINGS, best_options_enabled=True)
    view = _view()  # EV +25 %
    advice = build_advice([view], CTX, advice_settings)
    item = advice.best_options[0]
    assert "EXPERIMENTAL — solo papel" in item.price_comment
    assert any("EV inusualmente alto" in w for w in item.warnings)


def test_best_options_disabled_by_default_most_likely_honest() -> None:
    views = [
        _view(),
        _view(market="double_chance", selection="1X", line=None, label="Real Madrid o empate",
              probability=0.821, fair_odds=1.22, best_odds=1.15, ev=-0.056, verdict="evitar"),
        _view(market="double_chance", selection="12", line=None, label="Real Madrid o RB Leipzig",
              probability=0.80, fair_odds=1.25, best_odds=1.2, ev=-0.04, verdict="evitar"),
        _view(market="totals", selection="over", line=0.5, label="Más de 0.5 goles", probability=0.97,
              fair_odds=1.03, best_odds=1.02, ev=-0.01, verdict="evitar"),
        _view(market="totals", selection="over", line=4.5, label="Más de 4.5 goles", probability=0.9,
              fair_odds=1.11, confidence="baja"),
    ]  # fmt: skip
    advice = build_advice(views, CTX, SETTINGS)
    assert advice.best_options == [] and advice.no_value_message is None
    assert advice.best_options_note and "desactivados" in advice.best_options_note
    labels = [i.selection.label for i in advice.most_likely]
    # Highest probability first, one per market, no trivial (>95 %) and no "baja" market.
    assert labels == ["Real Madrid o empate", "Real Madrid más de 1.5 goles"]
    assert advice.most_likely[0].price_comment.endswith("No conviene.")


def test_no_value_message_when_enabled_and_nothing_qualifies() -> None:
    settings = replace(SETTINGS, best_options_enabled=True)
    advice = build_advice([_view(verdict="evitar", ev=-0.05)], CTX, settings)
    assert advice.best_options == []
    assert (
        advice.no_value_message
        == "Hoy no hay apuestas con valor en este partido. No apostar también es una decisión."
    )


def test_value_without_supporting_reasons_says_price_only() -> None:
    settings = replace(SETTINGS, best_options_enabled=True)
    quiet = replace(
        CTX,
        lambda_home=1.2,
        home_form={"n": 0, "venue": "home"},
        away_form={"n": 0, "venue": "away"},
    )
    item = build_advice([_view()], quiet, settings).best_options[0]
    assert item.reasons[-1].text == "El valor viene del precio, no de una tendencia clara."


@pytest.mark.parametrize(
    "text", ["Es una apuesta segura", "Fija para hoy", "Ganancia garantizada", "Esto no falla"]
)
def test_forbidden_language(text: str) -> None:
    with pytest.raises(ForbiddenLanguageError):
        check_language(text, SETTINGS.forbidden_words)


def test_every_configured_text_is_clean() -> None:
    for message in SETTINGS.messages.values():
        check_language(message, SETTINGS.forbidden_words)
    check_language(SETTINGS.best_options_note, SETTINGS.forbidden_words)
    assert check_language(
        "Asegúrate de verificar la cuota", SETTINGS.forbidden_words
    )  # not "segura"


def test_advice_yaml_rejects_forbidden_rule_text(tmp_path: Path) -> None:
    body = (Path(__file__).resolve().parents[2] / "configs" / "advice.yaml").read_text(
        encoding="utf-8"
    )
    bad = body.replace(
        "El modelo espera {lambda_team:.1f} goles", "Gol seguro: {lambda_team:.1f} goles", 1
    )
    path = tmp_path / "advice.yaml"
    path.write_text(bad, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_advice(path)
