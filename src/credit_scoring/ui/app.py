"""Écran de démonstration : un client de démo, son score, et le contrat de l'API à l'œuvre.

Les gestionnaires sont des fonctions de module (client et clients en premiers arguments),
testables sans lancer Gradio. Chaque score passe par la vraie route `/predict` (client
interne, `X-Client: ui-demo`) ; les valeurs de départ viennent de l'échantillon de démo.
Adapté de l'interface de P5 : pas de connexion (Space de démonstration, clé côté serveur).
"""

from __future__ import annotations

import os
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, get_args

# Avant l'import de gradio : ni statistiques d'usage ni appel à api.gradio.app.
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

import gradio as gr

from credit_scoring import __version__
from credit_scoring.api.features_schema import GeneratedFeatures
from credit_scoring.ui.client import ApiClient, ApiError
from credit_scoring.ui.view import errors_markdown, result_html, warnings_rows

TITLE = "Scoring crédit — Prêt à Dépenser"
SELECT_PROMPT = "⚠️ Sélectionnez un client."
DOWN = "⚠️ API indisponible"
AUTOFE_NOTE = (
    "Les features `autoFE_f_*` (les plus importantes) ne sont **pas** recalculées : modifier "
    "une valeur sert à éprouver le contrat de l'API (avertissement, refus 422), pas à mesurer "
    "la sensibilité du score."
)
PRIVATE: dict[str, Any] = {"api_visibility": "private"}  # pas d'API Gradio publique


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: Literal["float", "int", "choice"]
    info: str = ""


EDITABLE: tuple[Field, ...] = (
    Field("AMT_CREDIT", "Montant du crédit", "float", "> 0 ; au-delà de 4 050 000 : avertissement"),
    Field("CNT_FAM_MEMBERS", "Membres du foyer", "int", "≥ 1 (demandeur compris)"),
    Field("HOUR_APPR_PROCESS_START", "Heure de la demande", "int", "entier de 0 à 23"),
    Field("OCCUPATION_TYPE", "Profession", "choice"),
    Field("FLAG_EMAIL", "E-mail fourni", "int", "0 ou 1"),
    Field("OWN_CAR_AGE", "Âge du véhicule (années)", "float", "≥ 0"),
)


def choices(field: Field) -> list[str]:
    """Catégories admises par l'API (annotation `Literal` du schéma généré)."""
    return [str(v) for v in get_args(GeneratedFeatures.model_fields[field.name].annotation)]


def _values(client: dict[str, Any]) -> list[Any]:
    return [client.get(f.name) for f in EDITABLE]


def _outcome(prediction: dict[str, Any]) -> tuple[str, list[list[str]], str]:
    return result_html(prediction), warnings_rows(prediction), ""


def _failure(exc: Exception) -> tuple[str, list[list[str]], str]:
    message = errors_markdown(exc) if isinstance(exc, ApiError) else DOWN
    return "", [], message


def on_load(clients: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Liste des identifiants (chargée après le lifespan), premier sélectionné."""
    ids = sorted(clients)
    return gr.update(choices=ids, value=ids[0] if ids else None)


async def on_select(
    client: ApiClient, clients: dict[int, dict[str, Any]], sk_id_curr: int | None
) -> tuple[Any, ...]:
    """Valeurs de départ du client, et son score par `POST /predict/{sk_id_curr}`."""
    if sk_id_curr is None or int(sk_id_curr) not in clients:
        return (*[gr.update() for _ in EDITABLE], "", [], SELECT_PROMPT)
    sk_id = int(sk_id_curr)
    try:
        outcome = _outcome(await client.predict_demo(sk_id))
    except Exception as exc:  # erreur de l'API ou transport : affichée, jamais levée
        outcome = _failure(exc)
    return (*_values(clients[sk_id]), *outcome)


async def on_score(
    client: ApiClient, clients: dict[int, dict[str, Any]], sk_id_curr: int | None, *values: Any
) -> tuple[Any, ...]:
    """Client complet + valeurs modifiées, envoyé à `POST /predict` (rien n'est bloqué ici)."""
    if sk_id_curr is None or int(sk_id_curr) not in clients:
        return (*values, "", [], SELECT_PROMPT)
    body = {
        **clients[int(sk_id_curr)],
        **{f.name: v for f, v in zip(EDITABLE, values, strict=True)},
    }
    try:
        outcome = _outcome(await client.predict(body))
    except Exception as exc:
        outcome = _failure(exc)
    return (*values, *outcome)


def on_reset(clients: dict[int, dict[str, Any]], sk_id_curr: int | None) -> tuple[Any, ...]:
    if sk_id_curr is None or int(sk_id_curr) not in clients:
        return tuple(gr.update() for _ in EDITABLE)
    return tuple(_values(clients[int(sk_id_curr)]))


def random_id(clients: dict[int, dict[str, Any]], rng: random.Random) -> int:
    return rng.choice(sorted(clients))


def _component(field: Field) -> Any:
    if field.kind == "choice":
        return gr.Dropdown(choices(field), label=field.label, info=field.info or None)
    return gr.Number(
        label=field.label,
        info=field.info or None,
        precision=0 if field.kind == "int" else None,
    )


THEME = gr.themes.Base(
    primary_hue="blue",
    neutral_hue="slate",
    radius_size="sm",
    font=["Inter", "system-ui", "sans-serif"],
).set(block_shadow="none", button_primary_shadow="none", block_border_width="1px")
CSS = """
.gradio-container { max-width: 1180px !important; margin: auto; }
.subtitle { color: #64748b; }
.result .decision { font-size: 1.6rem; font-weight: 700; letter-spacing: .04em; }
.decision.decision-accorde { color: #15803d; }
.decision.decision-refuse { color: #b42318; }
.result .bar { position: relative; height: 12px; background: #e2e8f0; border-radius: 6px; }
.result .fill { height: 100%; border-radius: 6px; }
.fill.decision-accorde { background: #22c55e; }
.fill.decision-refuse { background: #ef4444; }
.result .threshold { position: absolute; top: -4px; width: 2px; height: 20px; background: #0f172a; }
"""
FORCE_LIGHT = """
() => {
  const url = new URL(window.location.href);
  if (url.searchParams.get("__theme") !== "light") {
    url.searchParams.set("__theme", "light");
    window.location.replace(url.href);
  }
}
"""
# Options de montage (gr.mount_gradio_app) : thème clair forcé, sans pied de page Gradio,
# sans historique des entrées dans le navigateur.
MOUNT_OPTIONS: dict[str, Any] = {
    "theme": THEME,
    "css": CSS,
    "js": FORCE_LIGHT,
    "footer_links": [],
    "run_history": False,
}


def build_ui(
    client_factory: Callable[[], ApiClient],
    clients_provider: Callable[[], dict[int, dict[str, Any]]],
) -> gr.Blocks:
    client = client_factory()
    rng = random.Random()

    with gr.Blocks(title=TITLE) as demo:
        gr.Markdown(f"# 🏦 {TITLE}")
        gr.Markdown(
            f"Démonstration sur 1 000 clients du jeu de test · API v{__version__} · "
            "[documentation de l'API](/docs)",
            elem_classes="subtitle",
        )
        with gr.Row(equal_height=False):
            with gr.Column(scale=5):
                gr.Markdown("### Client")
                with gr.Row():
                    sk_id = gr.Dropdown(label="SK_ID_CURR", choices=[], filterable=True, scale=3)
                    lucky = gr.Button("🎲 Client au hasard", scale=1)
                gr.Markdown("### Valeurs modifiables")
                fields = [_component(f) for f in EDITABLE]
                gr.Markdown(AUTOFE_NOTE, elem_classes="subtitle")
                with gr.Row():
                    score_btn = gr.Button("Scorer le client", variant="primary")
                    reset_btn = gr.Button("Rétablir")
            with gr.Column(scale=4):
                gr.Markdown("### Résultat")
                error = gr.Markdown()
                result = gr.HTML()
                warnings = gr.Dataframe(
                    headers=["Feature", "Valeur", "Bornes du train", "Rang", "Part du gain"],
                    label="Avertissements (hors des bornes du jeu d'entraînement)",
                    interactive=False,
                    wrap=True,
                )

        outputs = [*fields, result, warnings, error]

        async def select(sk: int | None) -> tuple[Any, ...]:
            return await on_select(client, clients_provider(), sk)

        async def score(sk: int | None, *values: Any) -> tuple[Any, ...]:
            return await on_score(client, clients_provider(), sk, *values)

        demo.load(lambda: on_load(clients_provider()), None, sk_id, **PRIVATE).then(
            select, sk_id, outputs, **PRIVATE
        )
        sk_id.input(select, sk_id, outputs, **PRIVATE)
        lucky.click(lambda: random_id(clients_provider(), rng), None, sk_id, **PRIVATE).then(
            select, sk_id, outputs, **PRIVATE
        )
        score_btn.click(score, [sk_id, *fields], outputs, **PRIVATE)
        reset_btn.click(lambda sk: on_reset(clients_provider(), sk), sk_id, fields, **PRIVATE)

    blocks: gr.Blocks = demo
    return blocks
