#!/usr/bin/env python3
"""Resolve um token de Página com segurança e executa o robô de Facebook Reels."""

import os
import requests


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Segredo obrigatório ausente: {name}")
    return value


PAGE_ID = required("FACEBOOK_PAGE_ID")
INPUT_TOKEN = required("FACEBOOK_PAGE_ACCESS_TOKEN")
GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v26.0").strip() or "v26.0"
BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


def graph_get(path: str, token: str, **params):
    response = requests.get(
        f"{BASE}/{path}",
        params={**params, "access_token": token},
        timeout=45,
    )
    data = response.json()
    if not response.ok or data.get("error"):
        message = data.get("error", {}).get("message") or f"Meta HTTP {response.status_code}"
        raise RuntimeError(message)
    return data


def resolve_page_token() -> str:
    # Se o segredo já for um Page Access Token da página certa, usamos diretamente.
    me = graph_get("me", INPUT_TOKEN, fields="id,name")
    if str(me.get("id")) == PAGE_ID:
        print(f"Token reconhecido diretamente para a Página {me.get('name') or PAGE_ID}.")
        return INPUT_TOKEN

    # Se o segredo for um User Access Token, tentamos obter o Page Access Token
    # da Página gerenciada. O valor obtido fica apenas na memória do runner.
    pages = graph_get(
        "me/accounts",
        INPUT_TOKEN,
        fields="id,name,access_token,tasks",
        limit="100",
    ).get("data", [])

    page = next((item for item in pages if str(item.get("id")) == PAGE_ID), None)
    if not page:
        raise RuntimeError(
            "O token atual não concede acesso à Página configurada. "
            "Gere um token com acesso à Página e permissão pages_manage_posts."
        )

    tasks = {str(task) for task in (page.get("tasks") or [])}
    print(
        "Página localizada pelo token de usuário: "
        f"{page.get('name') or PAGE_ID}. Tarefas concedidas: "
        + (", ".join(sorted(tasks)) if tasks else "não informadas")
    )
    page_token = str(page.get("access_token") or "").strip()
    if not page_token:
        raise RuntimeError("A Meta localizou a Página, mas não retornou Page Access Token.")
    return page_token


# Substitui apenas dentro do processo do GitHub Actions; o token nunca é impresso.
os.environ["FACEBOOK_PAGE_ACCESS_TOKEN"] = resolve_page_token()

from facebook_reels import main  # noqa: E402


if __name__ == "__main__":
    main()
