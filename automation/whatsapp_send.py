"""Envio seguro de mensagens pelo WhatsApp Cloud API.

O destinatario precisa ter autorizado mensagens do VIRALINK e, no ambiente de
teste da Meta, estar cadastrado entre os numeros permitidos.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v25.0")


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Configuracao ausente: {name}")
    return value


def normalized_phone(value: str) -> str:
    phone = "".join(character for character in value if character.isdigit())
    if len(phone) < 10 or len(phone) > 15:
        raise RuntimeError("WHATSAPP_RECIPIENT deve conter DDI, DDD e numero.")
    return phone


def send_template() -> dict:
    token = required("WHATSAPP_ACESS_TOKEN")
    phone_number_id = required("WHATSAPP_PHONE_NUMBER_ID")
    recipient = normalized_phone(required("WHATSAPP_RECIPIENT"))
    if os.getenv("WHATSAPP_RECIPIENT_OPT_IN", "").lower() != "true":
        raise RuntimeError("Envio pausado: confirme o consentimento em WHATSAPP_RECIPIENT_OPT_IN=true.")

    template = os.getenv("WHATSAPP_TEMPLATE", "hello_world").strip()
    language = os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en_US").strip()
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "template",
        "template": {"name": template, "language": {"code": language}},
    }
    request = urllib.request.Request(
        f"https://graph.facebook.com/{GRAPH_VERSION}/{phone_number_id}/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"WhatsApp API retornou HTTP {error.code}: {body[:500]}") from error


def main() -> int:
    try:
        result = send_template()
        message_id = ((result.get("messages") or [{}])[0]).get("id")
        if not message_id:
            raise RuntimeError("A Meta nao confirmou o identificador da mensagem.")
        print(json.dumps({"success": True, "message_id": message_id}))
        return 0
    except Exception as error:  # mensagem curta para o log do Actions
        print(json.dumps({"success": False, "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
