"""Écran de démonstration : gestionnaires appelés directement, sans lancer Gradio (#40)."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import gradio as gr
import httpx
import pytest
from fastapi.testclient import TestClient

from credit_scoring.api.app import app
from credit_scoring.api.features_schema import NULLABLE_FEATURES
from credit_scoring.model import get_model
from credit_scoring.ui import app as ui
from credit_scoring.ui.client import ApiClient, internal_client
from tests.conftest import API_KEY, DEMO_INVALID_ID, DEMO_NULLABLE_ID, DEMO_VALID_ID

NAMES = [f.name for f in ui.EDITABLE]
Ctx = tuple[ApiClient, dict[int, dict[str, Any]]]


@pytest.fixture
def ctx(api_artifacts: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Ctx]:
    monkeypatch.setenv("MODEL_DIR", str(api_artifacts))
    monkeypatch.setenv("API_KEY", API_KEY)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_model.cache_clear()
    with TestClient(app):
        yield internal_client(app), app.state.demo_clients
    get_model.cache_clear()


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def split(out: tuple[Any, ...]) -> tuple[dict[str, Any], str, list[list[str]], str]:
    """(valeurs des champs, html du résultat, lignes d'avertissements, markdown d'erreur)."""
    n = len(ui.EDITABLE)
    return dict(zip(NAMES, out[:n], strict=True)), out[n], out[n + 2], out[n + 3]


def chart(out: tuple[Any, ...]) -> str:
    """Html du graphique d'explication."""
    chart_html: str = out[len(ui.EDITABLE) + 1]
    return chart_html


def test_champs_lisibles_et_typés() -> None:
    assert 5 <= len(ui.EDITABLE) <= 8
    assert {"AMT_CREDIT", "CNT_FAM_MEMBERS", "HOUR_APPR_PROCESS_START"} <= set(NAMES)
    occupation = next(f for f in ui.EDITABLE if f.name == "OCCUPATION_TYPE")
    assert occupation.kind == "choice"
    assert "Laborers" in ui.choices(occupation)


def test_chargement_liste_triee(ctx: Ctx) -> None:
    _, clients = ctx
    update = ui.on_load(clients)
    assert update["choices"] == sorted(clients)
    assert update["value"] == min(clients)


def test_selection_score_immediat(ctx: Ctx) -> None:
    client, clients = ctx
    out = run(ui.on_select(client, clients, DEMO_VALID_ID))
    values, result, warnings, error = split(out)
    assert "decision-" in result
    assert "explain-bar" in chart(out)
    assert error == ""
    assert values["AMT_CREDIT"] == clients[DEMO_VALID_ID]["AMT_CREDIT"]
    assert warnings == []


def test_client_invalide_422_affiche(ctx: Ctx) -> None:
    client, clients = ctx
    out = run(ui.on_select(client, clients, DEMO_INVALID_ID))
    _, result, _, error = split(out)
    assert result == ""
    assert chart(out) == ""
    assert "422" in error


class Capture:
    """Faux client qui garde le corps envoyé."""

    def __init__(self) -> None:
        self.body: dict[str, Any] = {}

    async def explain(self, features: dict[str, Any]) -> dict[str, Any]:
        self.body = features
        return {"prob_default": 0.1, "decision": "accordé", "threshold": 0.5, "warnings": []}


def test_valeurs_nulles_renvoyees_nulles(ctx: Ctx) -> None:
    _, clients = ctx
    original = clients[DEMO_NULLABLE_ID]
    fake = Capture()
    values = [original[n] for n in NAMES]
    run(ui.on_score(fake, clients, DEMO_NULLABLE_ID, *values))  # type: ignore[arg-type]
    nulls = [k for k, v in original.items() if v is None]
    assert nulls and set(nulls) <= NULLABLE_FEATURES
    assert all(fake.body[k] is None for k in nulls)


def test_modification_avertissement(ctx: Ctx) -> None:
    client, clients = ctx
    values = {**{n: clients[DEMO_VALID_ID][n] for n in NAMES}, "AMT_CREDIT": 5_000_000.0}
    out = run(ui.on_score(client, clients, DEMO_VALID_ID, *values.values()))
    _, _, warnings, error = split(out)
    assert [w[0] for w in warnings] == ["AMT_CREDIT"]
    assert "explain-bar" in chart(out)
    assert error == ""


def test_modification_422(ctx: Ctx) -> None:
    client, clients = ctx
    values = {**{n: clients[DEMO_VALID_ID][n] for n in NAMES}, "CNT_FAM_MEMBERS": 0}
    _, result, warnings, error = split(
        run(ui.on_score(client, clients, DEMO_VALID_ID, *values.values()))
    )
    assert result == ""
    assert warnings == []
    assert "CNT_FAM_MEMBERS" in error


def test_champ_vide_non_nullable_422(ctx: Ctx) -> None:
    client, clients = ctx
    values = {**{n: clients[DEMO_VALID_ID][n] for n in NAMES}, "AMT_CREDIT": None}
    _, _, _, error = split(run(ui.on_score(client, clients, DEMO_VALID_ID, *values.values())))
    assert "AMT_CREDIT" in error


class Down:
    async def explain(self, features: dict[str, Any]) -> dict[str, Any]:
        raise httpx.ConnectError("injoignable")


def test_panne_api(ctx: Ctx) -> None:
    _, clients = ctx
    out = run(ui.on_select(Down(), clients, DEMO_VALID_ID))  # type: ignore[arg-type]
    _, result, _, error = split(out)
    assert result == ""
    assert chart(out) == ""
    assert "API indisponible" in error


def test_aucun_client_selectionne(ctx: Ctx) -> None:
    client, clients = ctx
    _, result, _, error = split(run(ui.on_select(client, clients, None)))
    assert result == ""
    assert "Sélectionnez" in error


def test_rétablir_valeurs_d_origine(ctx: Ctx) -> None:
    _, clients = ctx
    assert list(ui.on_reset(clients, DEMO_VALID_ID)) == [clients[DEMO_VALID_ID][n] for n in NAMES]


def test_hasard_dans_l_echantillon(ctx: Ctx) -> None:
    _, clients = ctx
    assert ui.random_id(clients, random.Random(0)) in clients


def test_build_ui_sans_api_gradio_publique() -> None:
    demo = ui.build_ui(lambda: None, dict)  # type: ignore[arg-type,return-value]
    assert isinstance(demo, gr.Blocks)
    fns = list(demo.fns.values())
    assert fns
    assert all(getattr(f, "api_visibility", None) == "private" for f in fns)


def test_score_et_retablir_sans_client(ctx: Ctx) -> None:
    client, clients = ctx
    values = [None] * len(ui.EDITABLE)
    *_, error = run(ui.on_score(client, clients, None, *values))
    assert "Sélectionnez" in error
    assert len(ui.on_reset(clients, None)) == len(ui.EDITABLE)


def test_evenements_relies_aux_gestionnaires(ctx: Ctx) -> None:
    client, clients = ctx
    demo = ui.build_ui(lambda: client, lambda: clients)
    by_name: dict[Any, Any] = {f.name: f.fn for f in demo.fns.values()}
    *_, error = run(by_name["select"](DEMO_VALID_ID))
    assert error == ""
    values = [clients[DEMO_VALID_ID][n] for n in NAMES]
    *_, error = run(by_name["score"](DEMO_VALID_ID, *values))
    assert error == ""


def test_champs_entiers_sans_arrondi() -> None:
    # 12,5 h doit atteindre l'API (422 int_from_float, règle de William), pas être arrondi.
    demo = ui.build_ui(lambda: None, dict)  # type: ignore[arg-type,return-value]
    numbers = [b for b in demo.blocks.values() if isinstance(b, gr.Number)]
    assert numbers
    assert all(n.precision is None for n in numbers)


def test_api_gradio_documentee_telle_qu_elle_est() -> None:
    # api_visibility="private" masque les endpoints de la doc Gradio sans les désactiver
    # (Gradio 6.32) : le pouvoir d'un appel direct reste celui de l'interface (décision D4).
    assert ui.PRIVATE == {"api_visibility": "private"}
    assert "non documentés" in (ui.__doc__ or "")
