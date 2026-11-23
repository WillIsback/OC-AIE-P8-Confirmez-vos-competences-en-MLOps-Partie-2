"""Onglet « Monitoring » (#18) : la production d'un coup d'œil, lue dans Neon.

Indicateurs opérationnels en direct (`monitoring.metrics` sur `prediction_logs`) et dernier
résumé de dérive écrit par le job planifié (`drift_reports`, #17). Lecture seule, agrégats
seulement. Gestionnaire testable sans Gradio ; une base absente ou injoignable s'affiche
en message et ne casse jamais l'onglet de scoring.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
from typing import Any

import pandas as pd

from credit_scoring.monitoring import metrics
from credit_scoring.monitoring.thresholds import THRESHOLDS
from credit_scoring.ui.view import fmt_number, fmt_percent

WINDOWS: dict[str, timedelta] = {
    "24 heures": timedelta(hours=24),
    "7 jours": timedelta(days=7),
    "30 jours": timedelta(days=30),
}
SOURCES: dict[str, str | None] = {
    "Production (api)": "api",
    "Démo (ui-demo)": "ui-demo",
    "Tout": None,
}
DEFAULT_SOURCE = "Production (api)"
NO_DATABASE = "⚠️ Base de production non configurée (`DATABASE_URL`) : aucun indicateur."
UNREACHABLE = "⚠️ Base de production injoignable ({kind}) : réessayez dans un instant."
NO_DRIFT = (
    '<div class="drift"><p>Aucune analyse de dérive pour l\'instant : le job planifié '
    "<code>drift-analysis</code> tourne chaque jour à 04:00 UTC.</p></div>"
)
DASH = "—"

Outputs = tuple[str, pd.DataFrame, pd.DataFrame, pd.DataFrame, str, str]


def _empty() -> Outputs:
    hist = pd.DataFrame({"bin": [], "count": []})
    hourly = pd.DataFrame({"hour": [], "n": [], "latency_p95": []})
    errors = pd.DataFrame({"error_type": [], "count": []})
    return "", hist, hourly, errors, "", ""


def _ms(value: float | None) -> str:
    return DASH if value is None else f"{fmt_number(round(value, 1))}\N{NARROW NO-BREAK SPACE}ms"


def _share(value: float | None) -> str:
    return DASH if value is None else fmt_percent(value)


def _tile(label: str, value: str, alert: bool = False, hint: str = "") -> str:
    css = "tile tile-alert" if alert else "tile"
    title = f' title="{escape(hint)}"' if hint else ""
    return (
        f'<div class="{css}"{title}><div class="tile-value">{value}</div>'
        f'<div class="tile-label">{escape(label)}</div></div>'
    )


def tiles_html(s: dict[str, Any]) -> str:
    """Tuiles : volume, acceptation, erreurs, latence et inférence ; alerte au-delà du seuil."""
    error_alert = s["error_rate"] is not None and s["error_rate"] > THRESHOLDS["error_rate_alert"]
    p95 = s["latency_p95"]
    latency_alert = p95 is not None and p95 > THRESHOLDS["latency_p95_ms_alert"]
    tiles = [
        _tile("appels", fmt_number(s["n"])),
        _tile("taux d'acceptation", _share(s["acceptance_rate"])),
        _tile(
            "taux d'erreur",
            _share(s["error_rate"]),
            error_alert,
            f"seuil d'alerte : {fmt_percent(THRESHOLDS['error_rate_alert'])}",
        ),
        _tile("latence p50", _ms(s["latency_p50"])),
        _tile(
            "latence p95",
            _ms(p95),
            latency_alert,
            f"seuil d'alerte : {_ms(THRESHOLDS['latency_p95_ms_alert'])}",
        ),
        _tile("inférence p50", _ms(s["inference_p50"])),
        _tile("inférence p95", _ms(s["inference_p95"])),
    ]
    return '<div class="tiles">' + "".join(tiles) + "</div>"


def drift_html(report: dict[str, Any] | None) -> str:
    """Dernier rapport de dérive : part en dérive contre le seuil, score, features en dérive."""
    if report is None:
        return NO_DRIFT
    end = pd.Timestamp(report["window_end"])
    days = (end - pd.Timestamp(report["window_start"])).days
    head = (
        f'<p class="subtitle">Analyse du {end:%d/%m/%Y %H:%M} UTC · {days} jours · '
        f"{fmt_number(report['n_current'])} appels contre "
        f"{fmt_number(report['n_reference'])} de référence · "
        f"{escape(str(report['model_version']))}</p>"
    )
    if report["insufficient"]:
        return (
            f'<div class="drift">{head}<p>Échantillon insuffisant : '
            f"{fmt_number(report['n_current'])} appels réussis dans la fenêtre.</p></div>"
        )
    share = report["share_drifted"]
    limit = THRESHOLDS["drift_share_alert"]
    score = report["score_drift_stat"]
    score_limit = THRESHOLDS["score_drift_alert"]
    tiles = (
        '<div class="tiles">'
        + _tile(
            f"features en dérive ({report['n_drifted']})",
            _share(share),
            share is not None and share > limit,
            f"seuil d'alerte : {fmt_percent(limit)}",
        )
        + _tile(
            "dérive du score",
            DASH if score is None else fmt_number(round(score, 3)),
            score is not None and score > score_limit,
            f"distance de Wasserstein normalisée ; seuil : {fmt_number(score_limit)}",
        )
        + "</div>"
    )
    drifted = [f for f in (report["details"] or {}).get("features", []) if f.get("drifted")]
    rows = "".join(
        f"<tr><td><code>{escape(str(f['name']))}</code></td><td>{escape(str(f['method']))}</td>"
        f"<td>{fmt_number(round(float(f['stat']), 3))}</td></tr>"
        for f in drifted[:10]
    )
    table = (
        '<table class="drift-table"><tr><th>Feature en dérive</th><th>Test</th>'
        f"<th>Statistique</th></tr>{rows}</table>"
        if rows
        else "<p>Aucune feature en dérive.</p>"
    )
    return f'<div class="drift">{head}{tiles}{table}</div>'


def on_refresh(
    engine: Any, window_label: str, source_label: str, now: datetime | None = None
) -> Outputs:
    """Tuiles, histogramme des scores, série horaire, erreurs, bloc dérive, message."""
    if engine is None:
        *rest, _ = _empty()
        return (*rest, NO_DATABASE)  # type: ignore[return-value]
    try:
        logs = metrics.load_logs(engine, WINDOWS[window_label], SOURCES[source_label], now=now)
        report = metrics.latest_drift(engine)
    except Exception as exc:  # base injoignable : affichée, jamais levée
        *rest, _ = _empty()
        return (*rest, UNREACHABLE.format(kind=type(exc).__name__))  # type: ignore[return-value]
    hist = metrics.score_histogram(logs)
    hist["bin"] = hist["bin"].map(lambda b: f"{b:.2f}")
    return (
        tiles_html(metrics.summary(logs)),
        hist,
        metrics.hourly(logs),
        metrics.errors_by_type(logs),
        drift_html(report),
        "",
    )
