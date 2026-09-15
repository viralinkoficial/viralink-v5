#!/usr/bin/env python3
"""Converte links Shopee comuns em links oficiais de afiliado.

O script processa produtos Shopee inativos cujo ``affiliate_url`` ainda usa
``shope.ee/an_redir?origin_link=...``. Links duplicados são convertidos apenas uma
vez: todas as cópias recebem o novo link, mas somente o registro mais recente
(maior ID) é verificado e reativado. Isso evita duplicatas na vitrine.

Credenciais obrigatórias (somente em ambiente seguro, nunca no frontend):
- SUPABASE_URL
- SUPABASE_SERVICE_ROLE_KEY
- SHOPEE_AFFILIATE_APP_ID
- SHOPEE_AFFILIATE_SECRET

Configuração opcional:
- SHOPEE_AFFILIATE_API (default BR)
- SHOPEE_BATCH_SIZE (default 20, máximo 100 links únicos)
- SHOPEE_SUB_ID (default viralink)
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from urllib.parse import parse_qs, urlparse

import requests


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Segredo/configuração obrigatória ausente: {name}")
    return value


SUPABASE_URL = required_env("SUPABASE_URL").rstrip("/")
SUPABASE_KEY = required_env("SUPABASE_SERVICE_ROLE_KEY")
SHOPEE_APP_ID = required_env("SHOPEE_AFFILIATE_APP_ID")
SHOPEE_SECRET = required_env("SHOPEE_AFFILIATE_SECRET")
SHOPEE_API = os.environ.get(
    "SHOPEE_AFFILIATE_API",
    "https://open-api.affiliate.shopee.com.br/graphql",
).strip()
SUB_ID = os.environ.get("SHOPEE_SUB_ID", "viralink").strip() or "viralink"
BATCH_SIZE = min(max(int(os.environ.get("SHOPEE_BATCH_SIZE", "20")), 1), 100)

SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


def fetch_pending_products() -> list[dict]:
    # A base histórica possui duplicatas. Busca todas as pendências (o conjunto atual
    # cabe no limite 1000) e reduz localmente para BATCH_SIZE links únicos.
    params = {
        "platform": "ilike.Shopee",
        "status": "eq.inactive",
        "affiliate_url": "like.https://shope.ee/an_redir?origin_link=*",
        "select": "id,name,affiliate_url",
        "order": "id.asc",
        "limit": "1000",
    }
    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/products",
        headers=SB_HEADERS,
        params=params,
        timeout=45,
    )
    response.raise_for_status()
    rows = response.json()

    # Um representante por URL antiga. Mantemos o maior ID como registro canônico,
    # pois é a cópia mais recente do produto na base.
    unique: dict[str, dict] = {}
    for row in rows:
        old_url = str(row.get("affiliate_url") or "")
        current = unique.get(old_url)
        if current is None or int(row["id"]) > int(current["id"]):
            unique[old_url] = row
    return list(unique.values())[:BATCH_SIZE]


def extract_origin_url(redirect_url: str) -> str:
    parsed = urlparse(redirect_url)
    if parsed.netloc.lower() != "shope.ee" or parsed.path != "/an_redir":
        raise ValueError("Link não está no formato an_redir esperado")

    origin = parse_qs(parsed.query).get("origin_link", [""])[0].strip()
    if not origin:
        raise ValueError("origin_link ausente")

    origin_parsed = urlparse(origin)
    host = origin_parsed.netloc.lower()
    if host not in {"shopee.com.br", "www.shopee.com.br"}:
        raise ValueError(f"origin_link fora da Shopee Brasil: {host or 'sem host'}")
    return origin


def shopee_short_link(origin_url: str, product_id: int) -> str:
    # JSON strings também são strings GraphQL válidas e fazem o escaping seguro.
    origin_literal = json.dumps(origin_url, ensure_ascii=False)
    sub_ids_literal = json.dumps([SUB_ID, f"produto_{product_id}"], ensure_ascii=False)
    query = (
        "mutation { generateShortLink(input: {"
        f"originUrl: {origin_literal}, subIds: {sub_ids_literal}"
        "}) { shortLink } }"
    )

    # A Shopee assina exatamente o payload textual enviado. Não use requests.post(json=...)
    # aqui, pois qualquer serialização diferente da assinada causa Invalid Signature.
    payload = json.dumps({"query": query}, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(time.time()))
    signature_base = f"{SHOPEE_APP_ID}{timestamp}{payload}{SHOPEE_SECRET}"
    signature = hashlib.sha256(signature_base.encode("utf-8")).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "Authorization": (
            f"SHA256 Credential={SHOPEE_APP_ID}, "
            f"Timestamp={timestamp}, Signature={signature}"
        ),
    }

    response = requests.post(
        SHOPEE_API,
        headers=headers,
        data=payload.encode("utf-8"),
        timeout=45,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("errors"):
        messages = "; ".join(str(e.get("message", e)) for e in body["errors"])
        raise RuntimeError(f"Shopee recusou a conversão: {messages}")

    short_link = (
        body.get("data", {})
        .get("generateShortLink", {})
        .get("shortLink", "")
        .strip()
    )
    if not short_link:
        raise RuntimeError("Shopee não retornou shortLink")

    parsed = urlparse(short_link)
    if parsed.scheme != "https" or parsed.netloc.lower() not in {
        "shope.ee",
        "s.shopee.com.br",
    }:
        raise RuntimeError(f"Shopee retornou link inesperado: {short_link}")
    if parsed.path == "/an_redir":
        raise RuntimeError("Shopee retornou an_redir em vez de link de afiliado curto")
    return short_link


def save_converted_group(old_url: str, canonical_id: int, short_link: str) -> int:
    # Primeiro corrige TODAS as cópias históricas desse produto, sem reativá-las.
    response = requests.patch(
        f"{SUPABASE_URL}/rest/v1/products",
        headers={**SB_HEADERS, "Prefer": "return=representation"},
        params={
            "platform": "ilike.Shopee",
            "status": "eq.inactive",
            "affiliate_url": f"eq.{old_url}",
        },
        json={"affiliate_url": short_link},
        timeout=45,
    )
    response.raise_for_status()
    changed = response.json()
    if not changed:
        raise RuntimeError("Supabase não encontrou o grupo a ser atualizado")

    # Depois verifica e reativa somente a cópia canônica (mais recente).
    # O banco bloqueia qualquer produto ativo cujo affiliate_verified seja falso.
    response = requests.patch(
        f"{SUPABASE_URL}/rest/v1/products",
        headers={**SB_HEADERS, "Prefer": "return=representation"},
        params={"id": f"eq.{canonical_id}", "affiliate_url": f"eq.{short_link}"},
        json={"affiliate_verified": True, "status": "active"},
        timeout=45,
    )
    response.raise_for_status()
    rows = response.json()
    if (
        len(rows) != 1
        or rows[0].get("status") != "active"
        or rows[0].get("affiliate_verified") is not True
    ):
        raise RuntimeError(f"Supabase não confirmou verificação/reativação do produto {canonical_id}")
    return len(changed)


def main() -> None:
    products = fetch_pending_products()
    if not products:
        print("Nenhum link Shopee an_redir pendente para converter.")
        return

    converted = 0
    failed = 0
    corrected_rows = 0
    for product in products:
        product_id = int(product["id"])
        old_url = product["affiliate_url"]
        try:
            origin_url = extract_origin_url(old_url)
            short_link = shopee_short_link(origin_url, product_id)
            group_size = save_converted_group(old_url, product_id, short_link)
            corrected_rows += group_size
            converted += 1
            print(
                f"OK #{product_id}: {product.get('name', '')} -> {short_link} "
                f"({group_size} registro(s) corrigido(s), 1 ativo)"
            )
            # Evita rajadas desnecessárias na API.
            time.sleep(0.35)
        except Exception as exc:
            failed += 1
            print(f"ERRO #{product_id}: {exc}")

    print(
        f"Resumo: links_unicos_convertidos={converted}, registros_corrigidos={corrected_rows}, "
        f"falhas={failed}, lote={len(products)}"
    )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
