#!/usr/bin/env python3
"""Valida se os Shorts automáticos estão saindo no ritmo esperado."""

import os
import sys
from collections import Counter
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import requests


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Segredo obrigatório ausente: {name}")
    return value


SB = required("SUPABASE_URL").rstrip("/")
KEY = required("SUPABASE_SERVICE_ROLE_KEY")
HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
BELEM = ZoneInfo("America/Belem")
SLOTS = list(range(6, 24))
ACTIVATED_AT = datetime(2026, 9, 4, 14, 0, tzinfo=BELEM)


def rest_get(path: str):
    response = requests.get(f"{SB}/rest/v1/{path}", headers=HEADERS, timeout=45)
    response.raise_for_status()
    return response.json()


def expected_slots(now_local: datetime) -> int:
    start_hour = 6
    if now_local.date() == ACTIVATED_AT.date():
        start_hour = max(start_hour, ACTIVATED_AT.hour)
    if now_local.date() < ACTIVATED_AT.date():
        return 0
    # O vigia roda aos 30 minutos; nesse ponto a execução da hora já deve ter terminado.
    return sum(1 for hour in SLOTS if hour >= start_hour and hour <= now_local.hour)


def main():
    now_local = datetime.now(timezone.utc).astimezone(BELEM)
    day_start_local = datetime.combine(now_local.date(), time.min, tzinfo=BELEM)
    day_start_utc = day_start_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    rows = rest_get(
        "campaign_queue?channel=eq.youtube"
        f"&created_at=gte.{day_start_utc}"
        "&select=id,status,created_at,external_id,error_message"
        "&order=created_at.asc&limit=500"
    ) or []

    counts = Counter(str(row.get("status") or "unknown") for row in rows)
    published = counts.get("published", 0)
    failed = counts.get("failed", 0)
    processing = counts.get("processing", 0)
    expected = expected_slots(now_local)

    print(
        f"YouTube hoje ({now_local:%d/%m %H:%M} Belém): "
        f"published={published}, failed={failed}, processing={processing}, expected={expected}"
    )

    errors = []
    if failed:
        errors.append(f"{failed} publicação(ões) com falha")
    if published < expected:
        errors.append(f"apenas {published} publicada(s) para {expected} horário(s) esperado(s)")

    if errors:
        print("ALERTA: " + " | ".join(errors))
        for row in rows[-8:]:
            if row.get("status") == "failed":
                print(f"Falha fila {row.get('id')}: {str(row.get('error_message') or '')[:300]}")
        sys.exit(1)

    print("Saúde OK: ritmo de publicação dentro do esperado e sem falhas registradas.")


if __name__ == "__main__":
    main()
