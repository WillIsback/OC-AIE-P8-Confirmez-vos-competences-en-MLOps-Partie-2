"""Écran de démonstration : un client de démo, son score, et le contrat de l'API à l'œuvre.

Les gestionnaires sont des fonctions de module (client et clients en premiers arguments),
testables sans lancer Gradio. Chaque score passe par la vraie route `/predict/explain`
(client interne, `X-Client: ui-demo`), qui renvoie aussi l'explication locale (#44) ; les
valeurs de départ viennent de l'échantillon de démo.
Adapté de l'interface de P5 : pas de connexion (Space de démonstration, clé côté serveur).

Les événements sont en `api_visibility="private"` : endpoints non documentés (ni page
« Use via API », ni clients Gradio). En Gradio 6.32, ils restent appelables par
`/gradio_api/…` ; un appel direct n'a que le pouvoir de l'interface (clients de démo, six
champs validés par l'API), ce qui est la décision D4 : la démonstration est publique.
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
from credit_scoring.ui.view import errors_markdown, explanation_html, result_html, warnings_rows

TITLE = "Scoring crédit — Prêt à Dépenser"
SELECT_PROMPT = "⚠️ Sélectionnez un client."
DOWN = "⚠️ API indisponible"
AUTOFE_NOTE = (
    "Les features `autoFE_f_*` (les plus importantes) ne sont **pas** recalculées : modifier "
    "une valeur sert à éprouver le contrat de l'API (avertissement, refus 422), pas à mesurer "
    "la sensibilité du score."
)
PRIVATE: dict[str, Any] = {"api_visibility": "private"}  # non documentés (voir en tête)


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


Outcome = tuple[str, str, list[list[str]], str]  # résultat, graphique, avertissements, erreur


def _outcome(prediction: dict[str, Any]) -> Outcome:
    chart = explanation_html(prediction.get("explanation"))
    return result_html(prediction), chart, warnings_rows(prediction), ""


def _failure(exc: Exception) -> Outcome:
    message = errors_markdown(exc) if isinstance(exc, ApiError) else DOWN
    return "", "", [], message


async def _explained(client: ApiClient, body: dict[str, Any]) -> Outcome:
    try:
        return _outcome(await client.explain(body))
    except Exception as exc:  # erreur de l'API ou transport : affichée, jamais levée
        return _failure(exc)


def on_load(clients: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Liste des identifiants (chargée après le lifespan), premier sélectionné."""
    ids = sorted(clients)
    return gr.update(choices=ids, value=ids[0] if ids else None)


async def on_select(
    client: ApiClient, clients: dict[int, dict[str, Any]], sk_id_curr: int | None
) -> tuple[Any, ...]:
    """Valeurs de départ du client, son score et son explication (`POST /predict/explain`)."""
    if sk_id_curr is None or int(sk_id_curr) not in clients:
        return (*[gr.update() for _ in EDITABLE], "", "", [], SELECT_PROMPT)
    sk_id = int(sk_id_curr)
    return (*_values(clients[sk_id]), *await _explained(client, clients[sk_id]))


async def on_score(
    client: ApiClient, clients: dict[int, dict[str, Any]], sk_id_curr: int | None, *values: Any
) -> tuple[Any, ...]:
    """Client complet + valeurs modifiées, envoyé à `POST /predict/explain` (rien n'est bloqué)."""
    if sk_id_curr is None or int(sk_id_curr) not in clients:
        return (*values, "", "", [], SELECT_PROMPT)
    body = {
        **clients[int(sk_id_curr)],
        **{f.name: v for f, v in zip(EDITABLE, values, strict=True)},
    }
    return (*values, *await _explained(client, body))


def on_reset(clients: dict[int, dict[str, Any]], sk_id_curr: int | None) -> tuple[Any, ...]:
    if sk_id_curr is None or int(sk_id_curr) not in clients:
        return tuple(gr.update() for _ in EDITABLE)
    return tuple(_values(clients[int(sk_id_curr)]))


def random_id(clients: dict[int, dict[str, Any]], rng: random.Random) -> int:
    return rng.choice(sorted(clients))


def _component(field: Field) -> Any:
    if field.kind == "choice":
        return gr.Dropdown(choices(field), label=field.label, info=field.info or None)
    # Pas de `precision=0` pour les entiers : Gradio arrondirait 12,5 en 12 sans le dire ;
    # c'est l'API qui refuse un décimal (422 int_from_float), et l'interface l'affiche.
    return gr.Number(label=field.label, info=field.info or None)


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
.explain { font-size: .88rem; }
.explain-head { font-weight: 600; margin-bottom: 2px; }
.explain-legend { color: #64748b; margin-top: 0; }
.legend-refus { color: #b42318; } .legend-accord { color: #15803d; }
.explain-row { display: grid; grid-template-columns: minmax(0, 1.3fr) 1fr 4.5em;
  gap: 8px; align-items: center; padding: 3px 0; border-bottom: 1px solid #f1f5f9; }
.explain-name { overflow-wrap: anywhere; }
.explain-value { color: #64748b; margin-left: 6px; }
.explain-track { position: relative; height: 10px; background: #f1f5f9; border-radius: 5px; }
.explain-track::after { content: ""; position: absolute; left: 50%; top: -3px; width: 1px;
  height: 16px; background: #94a3b8; }
.explain-bar { position: absolute; top: 0; height: 100%; border-radius: 5px; }
.explain-bar.push-refus { background: #ef4444; }
.explain-bar.push-accord { background: #22c55e; }
.explain-num { text-align: right; font-variant-numeric: tabular-nums; }
.explain-others { color: #64748b; font-style: italic; }
.badge-sensitive { display: inline-block; margin-left: 4px; padding: 0 6px; border-radius: 9px;
  background: #fef3c7; color: #92400e; border: 1px solid #f59e0b; font-size: .75rem;
  cursor: help; }
.derived { margin-left: 4px; color: #64748b; font-size: .75rem; font-style: italic; }
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
    # Rendu côté client : sur un Space, GRADIO_SSR_MODE=true lancerait au montage un serveur
    # Node sur le premier port libre à partir de 7860, avant uvicorn (Errno 98, #42).
    "ssr_mode": False,
}


def build_ui(
    client_factory: Callable[[], ApiClient],
    clients_provider: Callable[[], dict[int, dict[str, Any]]],
) -> gr.Blocks:
    client = client_factory()
    rng = random.Random()

    with gr.Blocks(title=TITLE) as demo:
        gr.Markdown(f"# {TITLE}")
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
                    lucky = gr.Button("Client au hasard", scale=1)
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
                chart = gr.HTML()
                warnings = gr.Dataframe(
                    headers=["Feature", "Valeur", "Bornes (train)", "Rang", "Part"],
                    column_widths=["26%", "18%", "30%", "13%", "13%"],
                    label="Avertissements (hors des bornes du jeu d'entraînement)",
                    interactive=False,
                    wrap=True,
                )

        outputs = [*fields, result, chart, warnings, error]

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
