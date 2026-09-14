#!/usr/bin/env python3
"""Resolve o token da Página e executa o Facebook com fila exclusiva e rotação segura."""

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
    me = graph_get("me", INPUT_TOKEN, fields="id,name")
    if str(me.get("id")) == PAGE_ID:
        print(f"Token reconhecido diretamente para a Página {me.get('name') or PAGE_ID}.")
        return INPUT_TOKEN

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


# O token resolvido existe apenas dentro deste processo do GitHub Actions.
os.environ["FACEBOOK_PAGE_ACCESS_TOKEN"] = resolve_page_token()

import facebook_reels as base  # noqa: E402
import facebook_reels_dynamic as dynamic  # noqa: E402


def _claim_pending(job):
    attempt = int(job.get("attempts", 0)) + 1
    response = base.requests.patch(
        f"{base.SB}/rest/v1/campaign_queue?id=eq.{job['id']}&status=eq.pending",
        headers={**base.HEADERS, "Prefer": "return=representation"},
        timeout=45,
        json={"status": "processing", "attempts": attempt, "error_message": None},
    )
    response.raise_for_status()
    claimed = response.json() if response.content else []
    if not claimed:
        print(f"Fila {job['id']} já foi capturada por outro executor.")
        return None
    result = claimed[0]
    result["attempts"] = attempt
    return result


def claim_facebook_job():
    # Respeita primeiro qualquer item explicitamente agendado para o Facebook.
    jobs = base.api(
        "GET",
        "campaign_queue?channel=eq.facebook&status=eq.pending&scheduled_for=lte.now()"
        "&order=scheduled_for.asc&limit=1&select=*",
    ) or []
    if jobs:
        return _claim_pending(jobs[0])

    # Somente produtos ativos E aprovados pelo guard de link de afiliada podem entrar na rotação.
    products = base.api(
        "GET",
        "products?status=eq.active&affiliate_verified=eq.true"
        "&image_url=not.is.null&affiliate_url=not.is.null"
        "&select=id,name&order=created_at.asc&limit=200",
    ) or []
    if not products:
        print("Nenhum produto verificado, ativo e completo disponível para Facebook.")
        return None

    # Não duplica produto que já esteja aguardando ou sendo processado no Facebook.
    reserved = base.api(
        "GET",
        "campaign_queue?channel=eq.facebook&status=in.(pending,processing)&select=product_id&limit=500",
    ) or []
    reserved_ids = {str(item.get("product_id")) for item in reserved}

    # Rotação justa: nunca publicados primeiro; depois o menos recentemente publicado.
    history = base.api(
        "GET",
        "campaign_queue?channel=eq.facebook&status=eq.published"
        "&select=product_id,created_at&order=created_at.desc&limit=1000",
    ) or []
    last_published = {}
    for item in history:
        pid = str(item.get("product_id"))
        if pid and pid not in last_published:
            last_published[pid] = str(item.get("created_at") or "")

    candidates = [p for p in products if str(p.get("id")) not in reserved_ids]
    if not candidates:
        print("Todos os produtos verificados já estão reservados para o Facebook.")
        return None

    def rotation_key(product):
        pid = str(product.get("id"))
        return (pid in last_published, last_published.get(pid, ""), int(product.get("id") or 0))

    product = sorted(candidates, key=rotation_key)[0]
    response = base.requests.post(
        f"{base.SB}/rest/v1/campaign_queue",
        headers={**base.HEADERS, "Prefer": "return=representation"},
        timeout=45,
        json={
            "product_id": str(product["id"]),
            "product_name": product.get("name") or "Produto",
            "channel": "facebook",
            "scheduled_for": base.datetime.now(base.timezone.utc).isoformat(),
            "status": "pending",
            "payload": {"automatic": True, "format": "reel", "rotation": "least_recently_published"},
            "created_by": base.ceo_user_id(),
        },
    )
    response.raise_for_status()
    created = response.json()
    if not created:
        return None
    print(f"Rotação Facebook selecionou produto {product['id']}: {product.get('name') or 'Produto'}")
    return _claim_pending(created[0])


def verified_product_for(job):
    rows = base.api(
        "GET",
        f"products?id=eq.{job['product_id']}"
        "&select=id,name,description,price,platform,category,image_url,affiliate_url,status,affiliate_verified&limit=1",
    ) or []
    if not rows:
        raise RuntimeError("Produto não encontrado.")
    product = rows[0]
    if (
        product.get("status") != "active"
        or product.get("affiliate_verified") is not True
        or not product.get("image_url")
        or not product.get("affiliate_url")
    ):
        raise RuntimeError("Produto bloqueado: exige status ativo, imagem e link de afiliada verificado.")
    return product


# O módulo dinâmico continua cuidando do visual/música; estas duas funções passam a
# controlar exclusivamente a seleção e a validação do produto para o Facebook.
base.claim_job = claim_facebook_job
base.product_for = verified_product_for
main = dynamic.main


if __name__ == "__main__":
    main()
