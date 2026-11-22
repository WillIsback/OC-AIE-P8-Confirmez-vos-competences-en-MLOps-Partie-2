"""Interface Gradio de démonstration (#40), montée à la racine de l'API.

Importer ce paquet exige Gradio (extra `ui`) : l'image Docker, sans l'extra, garde la page
HTML de l'API à `/` (`api.app.install_home`).
"""

from __future__ import annotations

import gradio as gr
from fastapi import FastAPI


def mount_ui(app: FastAPI) -> None:
    """Monte l'écran à `/` ; les routes de l'API, déclarées avant, gardent la priorité.

    Appel par attribut (`gr.mount_gradio_app`) : sur un Space ZeroGPU, le paquet `spaces`
    remplace cet attribut pour ajouter son middleware (« startup report »).
    """
    from credit_scoring.ui.app import MOUNT_OPTIONS, build_ui
    from credit_scoring.ui.client import internal_client

    demo = build_ui(lambda: internal_client(app), lambda: app.state.demo_clients)
    gr.mount_gradio_app(app, demo, path="/", **MOUNT_OPTIONS)
