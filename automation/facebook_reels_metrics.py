#!/usr/bin/env python3
"""Coleta métricas dos Reels publicados pelo VIRALINK e salva no Supabase.

O coletor é tolerante a mudanças/limitações da Graph API: tenta métricas de
vídeo conhecidas e, quando uma não estiver disponível, mantém as demais.
Nenhum token é impresso em logs.
"""

import json
import math
import os
from datetime import datetime, timezone

import requests


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Segredo obrigatório ausente: {name}")
    return value


SB = required("SUPABASE_URL").rstrip("/")
SB_KEY = required("SUPABASE_SERVICE_ROLE_KEY")
PAGE_ID = required("FACEBOOK_PAGE_ID")
INPUT_TOKEN = required("FACEBOOK_PAGE_ACCESS_TOKEN")
GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v26.0").strip() or "v26.0"
GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"

SB_HEADERS = {
    "apikey": SB_KEY,
    "Authorization": f"Bearer {SB_KEY}",
    "Content-Type": "application/json",
}


def graph_get(path: str, token: str, **params):
    response = requests.get(
        f"{GRAPH}/{path}",
        params={**params, "access_token": token},
        timeout=45,
    )
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok or data.get("error"):
        message = data.get("error", {}).get("message") or f"Meta HTTP {response.status_code}"
        raise RuntimeError(message)
    return data


def resolve_page_token() -> str:
    me = graph_get("me", INPUT_TOKEN, fields="id,name")
    if str(me.get("id")) == PAGE_ID:
        return INPUT_TOKEN

    pages = graph_get(
        "me/accounts",
        INPUT_TOKEN,
        fields="id,name,access_token,tasks",
        limit="100",
    ).get("data", [])
    page = next((item for item in pages if str(item.get("id")) == PAGE_ID), None)
    if not page:
        raise RuntimeError("O token atual não concede acesso à Página configurada.")
    page_token = str(page.get("access_token") or "").strip()
    if not page_token:
        raise RuntimeError("A Meta localizou a Página, mas não retornou Page Access Token.")
    return page_token


def sb_get(path: str):
    response = requests.get(f"{SB}/rest/v1/{path}", headers=SB_HEADERS, timeout=45)
    response.raise_for_status()
    return response.json()


def sb_upsert(row: dict):
    response = requests.post(
        f"{SB}/rest/v1/facebook_reel_performance?on_conflict=video_id",
        headers={**SB_HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
        data=json.dumps(row, ensure_ascii=False),
        timeout=45,
    )
    response.raise_for_status()


def edge_summary_count(video_id: str, edge: str, token: str):
    data = graph_get(f"{video_id}/{edge}", token, limit="0", summary="true")
    summary = data.get("summary") or {}
    value = summary.get("total_count")
    return int(value) if value is not None else None


def insight_value(video_id: str, metric: str, token: str):
    data = graph_get(f"{video_id}/video_insights", token, metric=metric)
    items = data.get("data") or []
    if not items:
        return None
    item = items[0]
    if "value" in item and isinstance(item.get("value"), (int, float)):
        return int(item["value"])
    values = item.get("values") or []
    if values:
        value = values[-1].get("value")
        if isinstance(value, (int, float)):
            return int(value)
    return None


def first_insight(video_id: str, candidates, token: str, errors: list):
    for metric in candidates:
        try:
            value = insight_value(video_id, metric, token)
            if value is not None:
                return value, metric
        except Exception as exc:
            errors.append(f"{metric}: {str(exc)[:140]}")
    return None, None


def optional_field(video_id: str, field: str, token: str):
    try:
        return graph_get(video_id, token, fields=field).get(field)
    except Exception:
        return None


def numeric_share_value(value):
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, dict):
        for key in ("count", "total_count", "value"):
            if isinstance(value.get(key), (int, float)):
                return int(value[key])
    return None


def normalize_permalink(value, video_id: str):
    """Garante link absoluto do Facebook; a Meta às vezes retorna /reel/<id>."""
    fallback = f"https://www.facebook.com/reel/{video_id}"
    text = str(value or "").strip()
    if not text:
        return fallback
    if text.startswith("/"):
        return "https://www.facebook.com" + text
    if text.startswith("https://") or text.startswith("http://"):
        return text
    return fallback


def collect(video_id: str, token: str):
    errors = []
    raw = {}

    views, views_metric = first_insight(
        video_id,
        ["total_video_views", "post_video_views", "post_media_view", "blue_reels_play_count"],
        token,
        errors,
    )
    if views is not None:
        raw["views_metric"] = views_metric

    try:
        reactions = edge_summary_count(video_id, "reactions", token)
    except Exception as exc:
        reactions = None
        errors.append(f"reactions: {str(exc)[:140]}")

    try:
        comments = edge_summary_count(video_id, "comments", token)
    except Exception as exc:
        comments = None
        errors.append(f"comments: {str(exc)[:140]}")

    shares, shares_metric = first_insight(
        video_id,
        ["total_video_shares", "post_shares"],
        token,
        errors,
    )
    if shares is None:
        shares = numeric_share_value(optional_field(video_id, "shares", token))
    if shares is not None and shares_metric:
        raw["shares_metric"] = shares_metric

    permalink = normalize_permalink(optional_field(video_id, "permalink_url", token), video_id)
    created_time = optional_field(video_id, "created_time", token)

    values = {
        "views": 0 if views is None else int(views),
        "reactions": 0 if reactions is None else int(reactions),
        "comments": 0 if comments is None else int(comments),
        "shares": 0 if shares is None else int(shares),
    }
    available = sum(v is not None for v in (views, reactions, comments, shares))
    status = "ok" if available == 4 else "partial" if available > 0 else "error"
    raw.update({"available_metrics": available})
    return values, permalink, created_time, status, errors, raw


def score_for(views: int, reactions: int, comments: int, shares: int):
    interactions = reactions + comments + shares
    rate = (interactions / views * 100.0) if views > 0 else 0.0
    score = (
        math.sqrt(max(0, views)) * 2.0
        + reactions * 5.0
        + comments * 12.0
        + shares * 20.0
        + min(50.0, rate * 5.0)
    )
    return interactions, rate, round(score, 2)


def published_jobs():
    return sb_get(
        "campaign_queue?channel=eq.facebook&status=eq.published&external_id=not.is.null"
        "&select=id,product_id,product_name,external_id,scheduled_for,created_at"
        "&order=created_at.desc&limit=100"
    ) or []


def main():
    token = resolve_page_token()
    jobs = published_jobs()
    if not jobs:
        print("Nenhum Reel publicado para sincronizar.")
        return

    synced = 0
    partial = 0
    for job in jobs:
        video_id = str(job.get("external_id") or "").strip()
        if not video_id:
            continue
        try:
            metrics, permalink, created_time, status, errors, raw = collect(video_id, token)
            engagement, rate, score = score_for(**metrics)
            now = datetime.now(timezone.utc).isoformat()
            row = {
                "video_id": video_id,
                "campaign_queue_id": job.get("id"),
                "product_id": None if job.get("product_id") is None else str(job.get("product_id")),
                "product_name": job.get("product_name") or "Produto",
                "permalink_url": normalize_permalink(permalink, video_id),
                "published_at": created_time or job.get("scheduled_for") or job.get("created_at"),
                **metrics,
                "engagement": engagement,
                "engagement_rate": round(rate, 4),
                "score": score,
                "sync_status": status,
                "sync_error": " | ".join(errors[-4:])[:900] if errors else None,
                "raw_metrics": raw,
                "last_sync_at": now,
                "updated_at": now,
            }
            sb_upsert(row)
            synced += 1
            if status != "ok":
                partial += 1
            print(f"Métricas atualizadas para Reel {video_id}: status={status}, score={score}")
        except Exception as exc:
            now = datetime.now(timezone.utc).isoformat()
            sb_upsert({
                "video_id": video_id,
                "campaign_queue_id": job.get("id"),
                "product_id": None if job.get("product_id") is None else str(job.get("product_id")),
                "product_name": job.get("product_name") or "Produto",
                "permalink_url": f"https://www.facebook.com/reel/{video_id}",
                "published_at": job.get("scheduled_for") or job.get("created_at"),
                "sync_status": "error",
                "sync_error": str(exc)[:900],
                "last_sync_at": now,
                "updated_at": now,
            })
            print(f"Falha ao sincronizar Reel {video_id}: {str(exc)[:180]}")

    print(f"Sincronização concluída: {synced} Reel(s), {partial} parcial(is).")


if __name__ == "__main__":
    main()
