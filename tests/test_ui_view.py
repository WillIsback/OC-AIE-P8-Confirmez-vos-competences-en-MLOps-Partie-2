"""Formatage de l'interface : nombres français, résultat, avertissements, erreurs (#40)."""

from __future__ import annotations

import pytest

from credit_scoring.ui.client import ApiError
from credit_scoring.ui.view import (
    BADGE_LABEL,
    DERIVED_LABEL,
    errors_markdown,
    explanation_html,
    fmt_number,
    fmt_percent,
    result_html,
    warnings_rows,
)

NNBSP = "\N{NARROW NO-BREAK SPACE}"
DASH = "\N{EN DASH}"  # espace fine insécable, séparateur de milliers


@pytest.mark.parametrize(
    ("value", "attendu"),
    [
        (514777.5, f"514{NNBSP}777,5"),
        (5_000_000.0, f"5{NNBSP}000{NNBSP}000"),
        (12, "12"),
        (0.25, "0,25"),
        (None, ""),
    ],
)
def test_fmt_number(value: float | int | None, attendu: str) -> None:
    assert fmt_number(value) == attendu


def test_fmt_percent() -> None:
    assert fmt_percent(0.6123) == f"61,2{NNBSP}%"


PREDICTION = {
    "prob_default": 0.6123,
    "decision": "refusé",
    "threshold": 0.5348,
    "warnings": [
        {
            "feature": "AMT_CREDIT",
            "value": 5_000_000.0,
            "min": 45_000.0,
            "max": 4_050_000.0,
            "importance_rank": 3,
            "importance_share": 0.031,
        }
    ],
}


def test_resultat_refuse() -> None:
    html = result_html(PREDICTION)
    assert "REFUSÉ" in html
    assert "decision-refuse" in html
    assert f"Probabilité de défaut : 61,2{NNBSP}% — seuil 53,5{NNBSP}%" in html
    assert "width:61.2%" in html  # barre de probabilité
    assert "left:53.5%" in html  # repère du seuil


def test_resultat_accorde() -> None:
    html = result_html({**PREDICTION, "prob_default": 0.2, "decision": "accordé"})
    assert "ACCORDÉ" in html
    assert "decision-accorde" in html


def test_lignes_d_avertissements() -> None:
    assert warnings_rows(PREDICTION) == [
        [
            "AMT_CREDIT",
            f"5{NNBSP}000{NNBSP}000",
            f"45{NNBSP}000 {DASH} 4{NNBSP}050{NNBSP}000",
            "3/122",
            f"3,1{NNBSP}%",
        ]
    ]


def test_avertissement_sans_importance() -> None:
    row = warnings_rows({"warnings": [{"feature": "X", "value": 1.0, "min": 0.0, "max": 0.5}]})
    assert row == [["X", "1", f"0 {DASH} 0,5", "", ""]]


def test_erreurs_422_en_puces() -> None:
    err = ApiError(
        422,
        [
            {"loc": ["body", "CNT_FAM_MEMBERS"], "msg": "Input should be >= 1", "input": 0},
            {"loc": ["body", "AMT_CREDIT"], "msg": "Field required"},
        ],
    )
    assert errors_markdown(err) == (
        "**Refusé par l'API (422)**\n\n"
        "- **CNT_FAM_MEMBERS** : Input should be >= 1 (reçu : 0)\n"
        "- **AMT_CREDIT** : Field required"
    )


def test_autre_erreur() -> None:
    assert errors_markdown(ApiError(500, "boom")) == "⚠️ API indisponible (statut 500)"


@pytest.mark.parametrize(
    ("value", "attendu"),
    [(1.004, "1,004"), (12.999, "12,999"), (0.0003, "0,0003"), (-0.0012, "-0,0012"), (2.5, "2,5")],
)
def test_petites_valeurs_et_decimales(value: float, attendu: str) -> None:
    assert fmt_number(value) == attendu


def test_valeur_recue_vide() -> None:
    err = ApiError(
        422, [{"loc": ["body", "AMT_CREDIT"], "msg": "Input should be a number", "input": None}]
    )
    assert "(reçu : vide)" in errors_markdown(err)
    assert "None" not in errors_markdown(err)


EXPLANATION = {
    "base_value": -2.3,
    "top": [
        {
            "feature": "CODE_GENDER",
            "value": "M",
            "contribution": 0.136,
            "sensitive": True,
            "derived": False,
        },
        {
            "feature": "autoFE_f_131",
            "value": 0.0426,
            "contribution": -0.087,
            "sensitive": False,
            "derived": True,
        },
        {
            "feature": "OWN_CAR_AGE",
            "value": None,
            "contribution": 0.01,
            "sensitive": False,
            "derived": False,
        },
    ],
    "others": -0.25,
}


def test_explication_une_barre_par_contribution() -> None:
    html = explanation_html(EXPLANATION)
    assert html.count('class="explain-bar') == 3
    assert html.count("push-refus") == 2
    assert html.count("push-accord") == 1
    assert "autres features" in html
    assert "\N{MINUS SIGN}0,25" in html


def test_explication_badge_critere_protege() -> None:
    html = explanation_html(EXPLANATION)
    assert BADGE_LABEL == "critère protégé (non-discrimination)"
    assert html.count(BADGE_LABEL) == 1
    assert 'title="sexe : critère protégé' in html  # info-bulle : la justification


def test_explication_combinaison_calculee() -> None:
    html = explanation_html(EXPLANATION)
    assert DERIVED_LABEL == "combinaison calculée"
    assert html.count(DERIVED_LABEL) == 1


def test_explication_plus_forte_barre_pleine_demi_largeur() -> None:
    html = explanation_html(EXPLANATION)
    assert "width:50.0%" in html  # |0,136| = maximum → demi-piste


def test_explication_valeurs_echappees() -> None:
    hostile = {
        "base_value": 0.0,
        "top": [
            {
                "feature": "<b>x</b>",
                "value": "<script>",
                "contribution": 0.1,
                "sensitive": False,
                "derived": False,
            }
        ],
        "others": 0.0,
    }
    html = explanation_html(hostile)
    assert "<script>" not in html and "<b>x</b>" not in html
    assert "&lt;script&gt;" in html


def test_contribution_minuscule_sans_signe_trompeur() -> None:
    tiny = {**EXPLANATION, "others": -0.0004}
    html = explanation_html(tiny)
    assert "\N{MINUS SIGN}0<" not in html and "+0<" not in html
    assert "≈\N{NARROW NO-BREAK SPACE}0" in html


def test_explication_absente() -> None:
    assert explanation_html(None) == ""
