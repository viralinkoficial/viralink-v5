#!/usr/bin/env python3
"""Publica produtos verificados do VIRALINK no Instagram usando a credencial Meta já validada."""

import os
import re
from datetime import datetime, timezone

import requests


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Segredo obrigatório ausente: {name}")
    return value


SB = required("SUPABASE_URL").rstrip("/")
KEY = required("SUPABASE_SERVICE_ROLE_KEY")
PAGE_ID = required("FACEBOOK_PAGE_ID")
INPUT_TOKEN = required("FACEBOOK_PAGE_ACCESS_TOKEN")
GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v26.0").strip() or "v26.0"
HEADERS = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Content-Type": "application/json",
}


def api(method: str, path: str, **kwargs):
    response = requests.request(method, f"{SB}/rest/v1/{path}", headers=HEADERS, timeout=45, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else None


def graph_get(path: str, token: str, **params):
    response = requests.get(
        f"https://graph.facebook.com/{GRAPH_VERSION}/{path}",
        params={**params, "access_token": token},
        timeout=45,
    )
    data = response.json()
    if not response.ok or data.get("error"):
        raise RuntimeError(data.get("error", {}).get("message") or f"Meta HTTP {response.status_code}")
    return data


def graph_post(path: str, token: str, values: dict[str, str]):
    response = requests.post(
        f"https://graph.facebook.com/{GRAPH_VERSION}/{path}",
        data={**values, "access_token": token},
        timeout=60,
    )
    data = response.json()
    if not response.ok or data.get("error"):
        raise RuntimeError(data.get("error", {}).get("message") or f"Meta HTTP {response.status_code}")
    return data


def resolve_page_token() -> str:
    me = graph_get("me", INPUT_TOKEN, fields="id,name")
    if str(me.get("id")) == PAGE_ID:
        print(f"Token reconhecido diretamente para a Página {me.get('name') or PAGE_ID}.")
        return INPUT_TOKEN

    pages = graph_get("me/accounts", INPUT_TOKEN, fields="id,name,access_token,tasks", limit="100").get("data", [])
    page = next((item for item in pages if str(item.get("id")) == PAGE_ID), None)
    if not page:
        raise RuntimeError("O token Meta atual não concede acesso à Página configurada.")
    page_token = str(page.get("access_token") or "").strip()
    if not page_token:
        raise RuntimeError("A Meta localizou a Página, mas não retornou Page Access Token.")
    print(f"Página Meta localizada: {page.get('name') or PAGE_ID}.")
    return page_token


def instagram_account_id(page_token: str) -> str:
    page = graph_get(PAGE_ID, page_token, fields="instagram_business_account{id,username}")
    account = page.get("instagram_business_account") or {}
    account_id = str(account.get("id") or "").strip()
    if not account_id:
        raise RuntimeError("A Página Viralink não possui uma conta profissional do Instagram vinculada.")
    print(f"Instagram profissional localizado: @{account.get('username') or account_id}.")
    return account_id


def eligible_products():
    return api(
        "GET",
        "products?status=eq.active&affiliate_verified=eq.true&image_url=not.is.null&affiliate_url=not.is.null"
        "&select=id,name,description,price,platform,category,image_url,affiliate_url,status,affiliate_verified"
        "&order=created_at.asc&limit=200",
    ) or []


def select_product():
    products = [p for p in eligible_products() if str(p.get("image_url") or "").startswith("https://") and str(p.get("affiliate_url") or "").startswith("https://")]
    if not products:
        raise RuntimeError("Nenhum produto ativo e verificado com imagem/link HTTPS.")

    rows = api(
        "GET",
        "campaign_queue?channel=eq.instagram&status=eq.published"
        "&select=product_id,created_at&order=created_at.desc&limit=500",
    ) or []
    last_published = {}
    for row in rows:
        pid = str(row.get("product_id"))
        if pid not in last_published:
            last_published[pid] = str(row.get("created_at") or "")

    never = [p for p in products if str(p["id"]) not in last_published]
    if never:
        selected = never[0]
    else:
        selected = min(products, key=lambda p: last_published.get(str(p["id"]), ""))

    print(f"Rotação Instagram selecionou produto {selected['id']}: {selected.get('name') or 'Produto'}")
    return selected


def create_processing_job(product):
    payload = {
        "name": product.get("name"),
        "description": product.get("description"),
        "price": product.get("price"),
        "platform": product.get("platform"),
        "category": product.get("category"),
        "image_url": product.get("image_url"),
        "affiliate_url": product.get("affiliate_url"),
        "automatic": True,
        "format": "feed_image",
    }
    response = requests.post(
        f"{SB}/rest/v1/campaign_queue",
        headers={**HEADERS, "Prefer": "return=representation"},
        timeout=45,
        json={
            "product_id": str(product["id"]),
            "product_name": product.get("name") or "Produto",
            "channel": "instagram",
            "scheduled_for": datetime.now(timezone.utc).isoformat(),
            "status": "processing",
            "attempts": 1,
            "payload": payload,
        },
    )
    response.raise_for_status()
    rows = response.json()
    if not rows:
        raise RuntimeError("A fila do Instagram não retornou o job criado.")
    return rows[0]


def caption(product):
    name = re.sub(r"\s+", " ", str(product.get("name") or "Achadinho VIRALINK")).strip()
    description = re.sub(r"\s+", " ", str(product.get("description") or "")).strip()[:900]
    price = ""
    if product.get("price") is not None:
        price = f"\n💰 R$ {float(product['price']):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return (
        f"{name}\n\n{description}{price}\n\n"
        f"👉 Produto: {product['affiliate_url']}\n\n"
        "#achadinhos #ofertas #shopee #viralink"
    )[:2200]


def publish_instagram(account_id: str, page_token: str, product):
    container = graph_post(
        f"{account_id}/media",
        page_token,
        {"image_url": str(product["image_url"]), "caption": caption(product)},
    )
    creation_id = str(container.get("id") or "")
    if not creation_id:
        raise RuntimeError("O Instagram não criou o contêiner da publicação.")
    published = graph_post(
        f"{account_id}/media_publish",
        page_token,
        {"creation_id": creation_id},
    )
    publication_id = str(published.get("id") or "")
    if not publication_id:
        raise RuntimeError("O Instagram não confirmou a publicação.")
    return publication_id


def main():
    product = select_product()
    job = create_processing_job(product)
    try:
        page_token = resolve_page_token()
        account_id = instagram_account_id(page_token)
        publication_id = publish_instagram(account_id, page_token, product)
        api(
            "PATCH",
            f"campaign_queue?id=eq.{job['id']}",
            json={"status": "published", "external_id": publication_id, "error_message": None},
        )
        print(f"Instagram publicado. publication_id={publication_id}")
    except Exception as exc:
        api(
            "PATCH",
            f"campaign_queue?id=eq.{job['id']}",
            json={"status": "failed", "error_message": str(exc)[:1000]},
        )
        raise


if __name__ == "__main__":
    main()
