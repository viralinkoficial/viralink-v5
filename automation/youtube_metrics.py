#!/usr/bin/env python3
"""Sincroniza métricas públicas dos Shorts do VIRALINK com o Supabase."""

import json
import math
import os
from datetime import datetime, timezone

import requests
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Segredo obrigatório ausente: {name}")
    return value


SB = secret("SUPABASE_URL").rstrip("/")
KEY = secret("SUPABASE_SERVICE_ROLE_KEY")
HEADERS = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Content-Type": "application/json",
}


def sb_get(path: str):
    response = requests.get(f"{SB}/rest/v1/{path}", headers=HEADERS, timeout=45)
    response.raise_for_status()
    return response.json()


def sb_upsert(row: dict):
    response = requests.post(
        f"{SB}/rest/v1/youtube_performance?on_conflict=video_id",
        headers={**HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
        data=json.dumps(row, ensure_ascii=False),
        timeout=45,
    )
    response.raise_for_status()


def youtube_client():
    creds = Credentials(
        None,
        refresh_token=secret("YOUTUBE_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=secret("YOUTUBE_CLIENT_ID"),
        client_secret=secret("YOUTUBE_CLIENT_SECRET"),
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    try:
        creds.refresh(GoogleAuthRequest())
    except RefreshError as exc:
        raise RuntimeError("Autenticação do YouTube recusada ao sincronizar métricas.") from exc
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def published_jobs():
    return sb_get(
        "campaign_queue?channel=eq.youtube&status=eq.published&external_id=not.is.null"
        "&select=id,product_id,product_name,external_id,scheduled_for,created_at"
        "&order=created_at.desc&limit=200"
    ) or []


def score_for(views: int, likes: int, comments: int):
    engagement = likes + comments
    rate = (engagement / views * 100.0) if views > 0 else 0.0
    score = (
        math.sqrt(max(0, views)) * 2.0
        + likes * 5.0
        + comments * 12.0
        + min(50.0, rate * 5.0)
    )
    return engagement, rate, round(score, 2)


def chunks(items, size=50):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def main():
    jobs = published_jobs()
    if not jobs:
        print("Nenhum Short publicado para sincronizar.")
        return

    yt = youtube_client()
    by_video = {str(job["external_id"]): job for job in jobs if job.get("external_id")}
    video_ids = list(by_video)
    found = set()
    synced = 0

    for batch in chunks(video_ids, 50):
        response = yt.videos().list(
            part="statistics,snippet,status",
            id=",".join(batch),
        ).execute()

        for item in response.get("items", []):
            video_id = str(item.get("id") or "")
            if not video_id or video_id not in by_video:
                continue
            found.add(video_id)
            job = by_video[video_id]
            stats = item.get("statistics") or {}
            snippet = item.get("snippet") or {}
            views = int(stats.get("viewCount") or 0)
            likes = int(stats.get("likeCount") or 0)
            comments = int(stats.get("commentCount") or 0)
            engagement, rate, score = score_for(views, likes, comments)
            now = datetime.now(timezone.utc).isoformat()
            row = {
                "video_id": video_id,
                "campaign_queue_id": job.get("id"),
                "product_id": None if job.get("product_id") is None else str(job.get("product_id")),
                "product_name": job.get("product_name") or "Produto",
                "permalink_url": f"https://youtube.com/shorts/{video_id}",
                "published_at": snippet.get("publishedAt") or job.get("scheduled_for") or job.get("created_at"),
                "views": views,
                "likes": likes,
                "comments": comments,
                "engagement": engagement,
                "engagement_rate": round(rate, 4),
                "score": score,
                "sync_status": "ok",
                "sync_error": None,
                "raw_metrics": {"statistics": stats, "privacyStatus": (item.get("status") or {}).get("privacyStatus")},
                "last_sync_at": now,
                "updated_at": now,
            }
            sb_upsert(row)
            synced += 1
            print(f"Short {video_id}: views={views}, likes={likes}, comments={comments}, score={score}")

    missing = [video_id for video_id in video_ids if video_id not in found]
    for video_id in missing:
        job = by_video[video_id]
        now = datetime.now(timezone.utc).isoformat()
        sb_upsert({
            "video_id": video_id,
            "campaign_queue_id": job.get("id"),
            "product_id": None if job.get("product_id") is None else str(job.get("product_id")),
            "product_name": job.get("product_name") or "Produto",
            "permalink_url": f"https://youtube.com/shorts/{video_id}",
            "published_at": job.get("scheduled_for") or job.get("created_at"),
            "sync_status": "error",
            "sync_error": "Vídeo não retornado pela API do YouTube.",
            "last_sync_at": now,
            "updated_at": now,
        })

    print(f"Sincronização concluída: {synced} Short(s) atualizado(s), {len(missing)} não localizado(s).")


if __name__ == "__main__":
    main()
