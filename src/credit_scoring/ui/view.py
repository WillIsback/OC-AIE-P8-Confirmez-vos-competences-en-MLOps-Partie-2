"""Formatage pur de l'interface (sans Gradio) : nombres français, résultat, erreurs."""

from __future__ import annotations

from html import escape
from typing import Any

from credit_scoring.api.fairness import SENSITIVE_FEATURES
from credit_scoring.api.features_schema import FEATURE_ORDER
from credit_scoring.ui.client import ApiError

NNBSP = "\N{NARROW NO-BREAK SPACE}"  # espace fine insécable : séparateur de milliers et avant « % »
DASH = "\N{EN DASH}"
N_FEATURES = len(FEATURE_ORDER)
MINUS = "\N{MINUS SIGN}"
BADGE_LABEL = "critère protégé (non-discrimination)"
DERIVED_LABEL = "combinaison calculée"


def fmt_number(value: float | int | None) -> str:
    """`514777.5` → `514 777,5` ; entier sans décimale ; `None` → chaîne vide."""
    if value is None:
        return ""
    if float(value).is_integer():
        text = f"{int(value):,}"
    else:  # 6 décimales au plus, sans zéros finaux : 1.004 → 1,004 ; 0.0003 → 0,0003
        text = f"{value:,.6f}".rstrip("0").rstrip(".")
    return text.replace(",", NNBSP).replace(".", ",")


def fmt_percent(share: float) -> str:
    return f"{share * 100:.1f}".replace(".", ",") + f"{NNBSP}%"


def result_html(prediction: dict[str, Any]) -> str:
    """Décision colorée, probabilité et barre avec le repère du seuil métier."""
    prob, threshold = prediction["prob_default"], prediction["threshold"]
    refused = prediction["decision"] == "refusé"
    css = "decision-refuse" if refused else "decision-accorde"
    return (
        f'<div class="result"><div class="decision {css}">'
        f"{escape(prediction['decision'].upper())}</div>"
        f"<p>Probabilité de défaut : {fmt_percent(prob)} — seuil {fmt_percent(threshold)}</p>"
        f'<div class="bar"><div class="fill {css}" style="width:{prob * 100:.1f}%"></div>'
        f'<div class="threshold" style="left:{threshold * 100:.1f}%"></div></div></div>'
    )


def warnings_rows(prediction: dict[str, Any]) -> list[list[str]]:
    """Colonnes : feature, valeur, bornes du train, rang d'importance, part du gain."""
    rows = []
    for w in prediction.get("warnings", []):
        rank, share = w.get("importance_rank"), w.get("importance_share")
        rows.append(
            [
                w["feature"],
                fmt_number(w["value"]),
                f"{fmt_number(w['min'])} {DASH} {fmt_number(w['max'])}",
                f"{rank}/{N_FEATURES}" if rank is not None else "",
                fmt_percent(share) if share is not None else "",
            ]
        )
    return rows


def errors_markdown(err: ApiError) -> str:
    """422 : une puce par champ refusé, avec la valeur reçue ; sinon un bandeau générique."""
    if err.status != 422 or not isinstance(err.details, list):
        return f"⚠️ API indisponible (statut {err.status})"
    lines = []
    for e in err.details:
        field = e["loc"][-1] if e.get("loc") else "?"
        value = e.get("input")
        received = "" if "input" not in e else f" (reçu : {'vide' if value is None else value})"
        lines.append(f"- **{field}** : {e.get('msg', '')}{received}")
    return "**Refusé par l'API (422)**\n\n" + "\n".join(lines)


def _signed(value: float) -> str:
    if abs(value) < 0.0005:  # arrondi à 0,000 : pas de signe trompeur devant 0
        return f"≈{NNBSP}0"
    text = fmt_number(round(abs(value), 3))
    return f"{MINUS}{text}" if value < 0 else f"+{text}"


def _shown(value: float | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return escape(value)
    return fmt_number(value)


def _bar(contribution: float, scale: float) -> str:
    """Barre centrée sur zéro : à droite (rouge) vers le refus, à gauche (vert) vers l'accord."""
    width = abs(contribution) / scale * 50 if scale else 0.0
    css, left = ("push-refus", 50.0) if contribution > 0 else ("push-accord", 50.0 - width)
    return (
        f'<div class="explain-track"><div class="explain-bar {css}" '
        f'style="left:{left:.1f}%;width:{width:.1f}%"></div></div>'
    )


def explanation_html(explanation: dict[str, Any] | None) -> str:
    """Graphique des contributions SHAP du client : barres, badge, mention des autoFE."""
    if not explanation:
        return ""
    top = explanation["top"]
    others = float(explanation["others"])
    scale = max((abs(c["contribution"]) for c in top), default=0.0)
    rows = []
    for c in top:
        name = escape(c["feature"])
        tags = ""
        if c.get("sensitive"):
            reason = escape(SENSITIVE_FEATURES.get(c["feature"], BADGE_LABEL))
            tags += f' <span class="badge-sensitive" title="{reason}">{BADGE_LABEL}</span>'
        if c.get("derived"):
            tags += f' <span class="derived">{DERIVED_LABEL}</span>'
        rows.append(
            f'<div class="explain-row"><div class="explain-name"><code>{name}</code>{tags}'
            f'<span class="explain-value">{_shown(c.get("value"))}</span></div>'
            f"{_bar(float(c['contribution']), scale)}"
            f'<span class="explain-num">{_signed(float(c["contribution"]))}</span></div>'
        )
    rows.append(
        '<div class="explain-row explain-others"><div class="explain-name">autres features</div>'
        f'<div class="explain-track"></div><span class="explain-num">{_signed(others)}</span></div>'
    )
    return (
        '<div class="explain"><p class="explain-head">Ce qui a pesé pour ce client '
        "(contributions SHAP, en log-odds)</p>"
        '<p class="explain-legend"><span class="legend-refus">▶ vers le refus</span> · '
        '<span class="legend-accord">◀ vers l\'accord</span></p>' + "".join(rows) + "</div>"
    )
