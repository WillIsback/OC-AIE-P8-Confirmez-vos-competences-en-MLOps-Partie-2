"""Formatage de l'interface : nombres français, résultat, avertissements, erreurs (#40)."""

from __future__ import annotations

import pytest

from credit_scoring.ui.client import ApiError
from credit_scoring.ui.view import (
    errors_markdown,
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
