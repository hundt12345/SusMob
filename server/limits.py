"""Kosten- und Limit-Bremse für öffentlich erreichbare Test-Instanzen.

Ein öffentlicher Link + Gratis-Modelle = ein Fremder kann das Tageslimit
(50 Requests) in wenigen Minuten verbrauchen. Diese Schutzschicht bremst:

* **Pro Stunde und IP**  – ``SUSMOB_CHAT_LIMIT_PER_HOUR`` (0 = aus)
* **Global pro Tag**      – ``SUSMOB_DAILY_REQUEST_BUDGET`` (0 = aus; für Free-Tier
  sind 50 realistisch – danach antwortet die App mit klarer Meldung statt Fehler)
* **Maximale Nachrichtenlänge** – ``SUSMOB_MAX_MESSAGE_CHARS`` (Default 8000)

Die Zähler liegen im Prozessspeicher: ausreichend für eine einzelne
Test-Instanz (ein Uvicorn-Worker). Für Mehr-Mandanten-Betrieb gehört das in
Redis/DB – steht so im Plan (Phase 4).
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default) or default)
    except ValueError:
        return default


class Bremse:
    """Einfache Zähler je IP/Stunde und global je Kalendertag (UTC)."""

    def __init__(self) -> None:
        self._stunde: dict[str, list[float]] = {}
        self._tag = ""
        self._tag_count = 0
        self._gesamt = 0

    # ---------------------------------------------------------------- konfig
    @property
    def pro_stunde(self) -> int:
        return _int_env("SUSMOB_CHAT_LIMIT_PER_HOUR", 0)

    @property
    def tagesbudget(self) -> int:
        return _int_env("SUSMOB_DAILY_REQUEST_BUDGET", 0)

    @property
    def max_zeichen(self) -> int:
        return _int_env("SUSMOB_MAX_MESSAGE_CHARS", 8000)

    # ---------------------------------------------------------------- prüfen
    def _heute(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _rotieren(self) -> None:
        heute = self._heute()
        if heute != self._tag:
            self._tag = heute
            self._tag_count = 0

    def _stunde_aufraeumen(self, ip: str) -> None:
        grenze = time.time() - 3600
        self._stunde[ip] = [t for t in self._stunde.get(ip, []) if t > grenze]
        if not self._stunde[ip]:
            self._stunde.pop(ip, None)

    def status(self, ip: str = "") -> dict:
        self._rotieren()
        if ip:
            self._stunde_aufraeumen(ip)
        return {
            "pro_stunde": self.pro_stunde,
            "tagesbudget": self.tagesbudget,
            "verbraucht_heute": self._tag_count,
            "verbraucht_stunde": len(self._stunde.get(ip, [])) if ip else 0,
            "max_zeichen": self.max_zeichen,
        }

    def pruefen(self, ip: str, zeichen: int = 0) -> None:
        """Wirft ``LimitError``, wenn die Anfrage abgelehnt werden muss."""
        self._rotieren()
        if zeichen and zeichen > self.max_zeichen:
            raise LimitError(
                f"Nachricht zu lang ({zeichen} Zeichen). Erlaubt sind {self.max_zeichen} Zeichen – "
                "bitte aufteilen.", status=413)
        if self.tagesbudget and self._tag_count >= self.tagesbudget:
            raise LimitError(
                f"Tagesbudget des Testbetriebs erreicht ({self.tagesbudget} Modell-Aufrufe). "
                "Es wird um 00:00 UTC zurückgesetzt – oder 10 $ Guthaben bei OpenRouter laden "
                "(dann 1.000 Requests/Tag statt 50).", status=429)
        if self.pro_stunde and ip:
            self._stunde_aufraeumen(ip)
            if len(self._stunde.get(ip, [])) >= self.pro_stunde:
                raise LimitError(
                    f"Stundenlimit erreicht ({self.pro_stunde} Aufrufe/Stunde). "
                    "Das schützt das Gratis-Kontingent der Test-Instanz.", status=429)

    def notieren(self, ip: str = "") -> None:
        self._rotieren()
        self._tag_count += 1
        self._gesamt += 1
        if ip:
            self._stunde.setdefault(ip, []).append(time.time())

    def zuruecksetzen(self) -> None:
        self._stunde.clear()
        self._tag_count = 0
        self._gesamt = 0
        self._tag = self._heute()


class LimitError(Exception):
    def __init__(self, message: str, status: int = 429) -> None:
        super().__init__(message)
        self.status = status


BREMSE = Bremse()


def client_ip(request) -> str:
    """IP hinter Reverse Proxy berücksichtigen (Render/Fly/Cloudflare setzen X-Forwarded-For)."""
    weiter = request.headers.get("x-forwarded-for", "")
    if weiter:
        return weiter.split(",")[0].strip()
    return getattr(request.client, "host", "") or ""
