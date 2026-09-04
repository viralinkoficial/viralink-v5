#!/usr/bin/env python3
"""Cria e publica um Short a partir da fila do VIRALINK."""

import math
import os
import re
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


def secret(name):
    """Lê credenciais sem espaços/quebras de linha acidentais."""
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


def api(method, path, **kwargs):
    r = requests.request(method, f"{SB}/rest/v1/{path}", headers=HEADERS, timeout=45, **kwargs)
    r.raise_for_status()
    return r.json() if r.content else None


def choose_product():
    """Escolhe produto por desempenho, preservando exploração e evitando repetição imediata."""
    published = api(
        "GET",
        "campaign_queue?channel=eq.youtube&status=eq.published"
        "&select=product_id&order=created_at.desc&limit=300",
    ) or []
    recent_ids = {str(item.get("product_id")) for item in published[:18] if item.get("product_id") is not None}
    published_counts = Counter(str(item.get("product_id")) for item in published if item.get("product_id") is not None)

    products = api(
        "GET",
        "products?status=eq.active&image_url=not.is.null&affiliate_url=not.is.null"
        "&select=id,name&order=created_at.asc&limit=1000",
    ) or []
    if not products:
        return None, 0.0

    performance_rows = api(
        "GET",
        "youtube_performance?select=product_id,score,views,likes,comments"
        "&order=published_at.desc&limit=2000",
    ) or []
    click_rows = api(
        "GET",
        "product_clicks?source=eq.youtube&select=product_id&order=clicked_at.desc&limit=5000",
    ) or []

    performance = defaultdict(lambda: {"score_sum": 0.0, "count": 0})
    for row in performance_rows:
        pid = str(row.get("product_id") or "")
        if not pid:
            continue
        performance[pid]["score_sum"] += float(row.get("score") or 0)
        performance[pid]["count"] += 1

    clicks = Counter(str(row.get("product_id")) for row in click_rows if row.get("product_id") is not None)

    candidates = [p for p in products if str(p.get("id")) not in recent_ids]
    if not candidates:
        candidates = products

    def smart_score(product):
        pid = str(product.get("id"))
        perf = performance[pid]
        avg_video_score = perf["score_sum"] / perf["count"] if perf["count"] else 0.0
        click_bonus = math.log1p(clicks[pid]) * 25.0
        posts = published_counts[pid]
        exploration_bonus = 18.0 if posts == 0 else max(0.0, 8.0 - posts)
        return avg_video_score + click_bonus + exploration_bonus

    product = max(candidates, key=smart_score)
    score = round(smart_score(product), 2)
    print(
        f"Seleção inteligente: produto={product.get('id')} score={score} "
        f"posts={published_counts[str(product.get('id'))]} clicks={clicks[str(product.get('id'))]}"
    )
    return product, score


def claim_job():
    jobs = api(
        "GET",
        "campaign_queue?channel=eq.youtube&status=eq.pending&scheduled_for=lte.now()"
        "&order=scheduled_for.asc&limit=1&select=*",
    )
    if not jobs:
        product, selection_score = choose_product()
        if not product:
            print("Nenhum produto ativo com imagem e link.")
            return None

        users_response = requests.get(
            f"{SB}/auth/v1/admin/users?page=1&per_page=1000",
            headers=HEADERS,
            timeout=45,
        )
        users_response.raise_for_status()
        users = users_response.json().get("users", [])
        owner = next(
            (u for u in users if str(u.get("email", "")).lower() == "vivianeferreiracaroline@gmail.com"),
            None,
        )
        if not owner:
            raise RuntimeError("Conta CEO não encontrada no Supabase Auth.")

        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        create_response = requests.post(
            f"{SB}/rest/v1/campaign_queue",
            headers={**HEADERS, "Prefer": "return=representation"},
            timeout=45,
            json={
                "product_id": str(product["id"]),
                "product_name": product.get("name") or "Produto",
                "channel": "youtube",
                "scheduled_for": now,
                "status": "pending",
                "payload": {
                    "automatic": True,
                    "selection": "performance",
                    "selection_score": selection_score,
                },
                "created_by": owner["id"],
            },
        )
        create_response.raise_for_status()
        jobs = create_response.json()

    job = jobs[0]
    api(
        "PATCH",
        f"campaign_queue?id=eq.{job['id']}",
        json={
            "status": "processing",
            "attempts": int(job.get("attempts", 0)) + 1,
            "error_message": None,
        },
    )
    return job


def product_for(job):
    rows = api(
        "GET",
        f"products?id=eq.{job['product_id']}"
        "&select=id,name,description,price,platform,category,image_url,affiliate_url,status&limit=1",
    )
    if not rows:
        raise RuntimeError("Produto não encontrado.")
    p = rows[0]
    if p.get("status") != "active" or not p.get("image_url") or not p.get("affiliate_url"):
        raise RuntimeError("Produto inativo ou sem imagem/link.")
    return p


def font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}", size)


def wrap(draw, text, fnt, width):
    words, lines, line = str(text).split(), [], ""
    for word in words:
        trial = (line + " " + word).strip()
        if draw.textbbox((0, 0), trial, font=fnt)[2] <= width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def poster(product, out):
    raw = requests.get(product["image_url"], timeout=45)
    raw.raise_for_status()
    src = Image.open(__import__("io").BytesIO(raw.content)).convert("RGB")
    canvas = Image.new("RGB", (1080, 1920), (12, 8, 35))
    bg = src.copy()
    bg.thumbnail((1400, 2100))
    bg = bg.resize((1080, 1920)).filter(ImageFilter.GaussianBlur(32))
    canvas.paste(bg, (0, 0))
    canvas.paste(
        Image.new("RGBA", canvas.size, (8, 4, 28, 145)),
        (0, 0),
        Image.new("RGBA", canvas.size, (8, 4, 28, 145)),
    )
    pic = src.copy()
    pic.thumbnail((900, 900))
    canvas.paste(pic, ((1080 - pic.width) // 2, 260), pic if pic.mode == "RGBA" else None)
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((55, 75, 1025, 190), 35, fill=(124, 58, 237))
    d.text((540, 132), "ACHADINHO VIRALINK", font=font(47, True), anchor="mm", fill="white")
    y = 1210
    for line in wrap(d, product.get("name", "Oferta imperdível"), font(58, True), 930)[:3]:
        d.text((540, y), line, font=font(58, True), anchor="ma", fill="white")
        y += 74
    price = product.get("price")
    if price is not None:
        value = f"R$ {float(price):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        d.rounded_rectangle((230, 1490, 850, 1630), 38, fill=(22, 163, 74))
        d.text((540, 1560), value, font=font(68, True), anchor="mm", fill="white")
    d.text((540, 1740), "Link para comprar na descrição", font=font(39, True), anchor="mm", fill="white")
    d.text((540, 1815), "#Shorts  #Achadinhos  #VIRALINK", font=font(30), anchor="mm", fill=(220, 210, 255))
    canvas.save(out, quality=95)


def make_video(poster_path, out):
    # Trilha instrumental gerada localmente: não depende de narração ou serviço externo.
    audio = (
        "[1:a]volume=0.045[a0];[2:a]volume=0.03[a1];"
        "[a0][a1]amix=inputs=2:duration=longest,"
        "afade=t=in:d=0.6,afade=t=out:st=20:d=2[a]"
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-loop", "1", "-i", str(poster_path),
            "-f", "lavfi", "-i", "sine=frequency=220:duration=22",
            "-f", "lavfi", "-i", "sine=frequency=329.63:duration=22",
            "-filter_complex", audio, "-map", "0:v", "-map", "[a]", "-t", "22",
            "-vf", "scale=1080:1920,format=yuv420p", "-r", "30", "-c:v", "libx264", "-preset", "medium",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out),
        ],
        check=True,
    )


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
        raise RuntimeError(
            "Autenticação do YouTube recusada. Gere um novo refresh token com o mesmo "
            "Client ID/Secret e o escopo youtube.upload, depois atualize YOUTUBE_REFRESH_TOKEN."
        ) from exc
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def tracking_link(product, job):
    product_id = quote(str(product["id"]), safe="")
    queue_id = quote(str(job["id"]), safe="")
    return (
        f"{SB}/functions/v1/track-click?product_id={product_id}"
        f"&source=youtube&campaign_queue_id={queue_id}"
    )


def upload(video, product, job, yt):
    title = (f"{product['name']} | Achadinho VIRALINK #Shorts")[:100]
    product_name = re.sub(r"[^\w\s.,!?:;()%-]", " ", str(product["name"]))
    product_name = re.sub(r"\s+", " ", product_name).strip()[:300]
    buy_url = tracking_link(product, job)
    desc = (
        f"{product_name}\n\n"
        f"Compre aqui: {buy_url}\n\n"
        "ℹ️ Link de afiliado: o VIRALINK pode receber comissão sem custo extra para você.\n\n"
        "#Shorts #Achadinhos #Shopee #VIRALINK"
    )
    body = {
        "snippet": {
            "title": title,
            "description": desc,
            "categoryId": "22",
            "tags": ["Shorts", "Achadinhos", "VIRALINK", "ofertas"],
        },
        "status": {
            "privacyStatus": os.getenv("YOUTUBE_PRIVACY_STATUS", "public"),
            "selfDeclaredMadeForKids": False,
        },
    }
    result = yt.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(str(video), mimetype="video/mp4", resumable=True),
    ).execute()
    return result["id"]


def main():
    # Valida o OAuth antes de buscar produto e renderizar o vídeo.
    yt = youtube_client()
    print("Autenticação do YouTube validada.")
    job = claim_job()
    if not job:
        return
    try:
        product = product_for(job)
        with tempfile.TemporaryDirectory() as td:
            poster_path = Path(td) / "poster.jpg"
            video = Path(td) / "short.mp4"
            poster(product, poster_path)
            make_video(poster_path, video)
            video_id = upload(video, product, job, yt)
        api(
            "PATCH",
            f"campaign_queue?id=eq.{job['id']}",
            json={"status": "published", "external_id": video_id, "error_message": None},
        )
        print(f"Publicado: https://youtube.com/shorts/{video_id}")
    except Exception as exc:
        attempts = int(job.get("attempts", 0)) + 1
        status = "failed" if attempts >= 3 else "pending"
        api(
            "PATCH",
            f"campaign_queue?id=eq.{job['id']}",
            json={"status": status, "error_message": str(exc)[:1000]},
        )
        raise


if __name__ == "__main__":
    main()
