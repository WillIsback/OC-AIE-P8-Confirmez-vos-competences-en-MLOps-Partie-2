"""Écriture des journaux de production en tâche de fond (ADR-004).

Chaque enregistrement part sur deux sorties : une ligne JSON sur le logger
`credit_scoring.production` (toujours), et une file vers la base, vidée par un thread qui
insère par lots. Une base absente, lente ou en panne, ou une file pleine, ne bloquent ni ne
font échouer la requête : l'enregistrement est abandonné et compté (`dropped`), la ligne
JSON reste.
"""

from __future__ import annotations

import json
import logging
import queue
import sys
import threading
from typing import Any

import sqlalchemy as sa

from credit_scoring.monitoring.schema import prediction_logs

LOGGER_NAME = "credit_scoring.production"
log = logging.getLogger(LOGGER_NAME)
if not log.handlers:  # pragma: no branch - garde de réimport
    # Une ligne JSON brute par appel sur stdout, quelle que soit la configuration du logging
    # de l'hôte (uvicorn laisse la racine en WARNING) : collectable par les logs du Space.
    _stdout = logging.StreamHandler(sys.stdout)
    _stdout.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_stdout)
    log.setLevel(logging.INFO)
    log.propagate = False
_errors = logging.getLogger(__name__)
_STOP = object()


class ProductionLogWriter:
    def __init__(self, engine: sa.Engine | None, maxsize: int = 10_000, batch: int = 100) -> None:
        self.engine = engine
        self.batch = batch
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=maxsize)
        self._thread: threading.Thread | None = None
        self._dropped = 0
        self._lock = threading.Lock()

    @property
    def database(self) -> bool:
        return self.engine is not None

    @property
    def dropped(self) -> int:
        return self._dropped

    def _drop(self, n: int = 1) -> None:
        with self._lock:
            self._dropped += n

    def start(self) -> None:
        if self.engine is not None and self._thread is None:
            self._thread = threading.Thread(
                target=self._run, args=(self.engine,), name="prediction-logs", daemon=True
            )
            self._thread.start()

    def submit(self, record: dict[str, Any]) -> None:
        """Ligne JSON + mise en file ; ne bloque jamais et ne lève jamais."""
        log.info(json.dumps(record, default=str, ensure_ascii=False))
        if self.engine is None:
            return
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            self._drop()

    def stop(self, timeout: float = 5.0) -> None:
        """Vide la file puis arrête le thread, en au plus deux fois `timeout` secondes.

        Si la base ne répond plus, les lignes restées en file sont comptées comme perdues :
        l'arrêt du service n'attend jamais une base bloquée.
        """
        if self._thread is None:
            return
        try:
            self._queue.put(_STOP, timeout=timeout)
        except queue.Full:
            self._drop(self._discard_pending())
            self._queue.put_nowait(_STOP)
        self._thread.join(timeout)
        if self._thread.is_alive():
            self._drop(self._discard_pending())
        self._thread = None

    def _discard_pending(self) -> int:
        n = 0
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return n
            n += item is not _STOP

    def _run(self, engine: sa.Engine) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            records = [item]
            while len(records) < self.batch:
                try:
                    nxt = self._queue.get_nowait()
                except queue.Empty:
                    break
                if nxt is _STOP:
                    self._insert(engine, records)
                    return
                records.append(nxt)
            self._insert(engine, records)

    def _insert(self, engine: sa.Engine, records: list[dict[str, Any]]) -> None:
        try:
            with engine.begin() as conn:
                conn.execute(sa.insert(prediction_logs), records)
            return
        except sa.exc.DBAPIError as exc:
            # Une ligne refusée (contrainte, valeur) annule tout le lot : on rejoue ligne à
            # ligne pour ne perdre qu'elle. Base injoignable : inutile d'insister.
            if len(records) > 1 and not isinstance(exc, sa.exc.OperationalError):
                for one in records:
                    self._insert(engine, [one])
                return
            failure: Exception = exc
        except Exception as exc:  # jamais propager depuis le thread d'écriture
            failure = exc
        self._drop(len(records))
        # Le message d'une erreur de connexion peut contenir l'URL (et son mot de passe).
        _errors.warning(
            "Écriture de %d journaux impossible (%s)", len(records), type(failure).__name__
        )
