#!/usr/bin/env python3
"""Cria e publica Reels no Facebook a partir dos produtos do VIRALINK."""

import io
import os
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def secret(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Segredo obrigatório ausente: {name}")
    return value


SB = secret("SUPABASE_URL").rstrip("/")
KEY = secret("SUPABASE_SERVICE_ROLE_KEY")
PAGE_ID = secret("FACEBOOK_PAGE_ID")
PAGE_TOKEN = secret("FACEBOOK_PAGE_ACCESS_TOKEN")
GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v26.0").strip() or "v26.0"
BUCKET = os.environ.get("FACEBOOK_REELS_BUCKET", "facebook-reels-temp").strip() or "facebook-reels-temp"
HEADERS = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Content-Type": "application/json",
}


def api(method, path, **kwargs):
    response = requests.request(method, f"{SB}/rest/v1/{path}", headers=HEADERS, timeout=45, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else None


def ceo_user_id():
    response = requests.get(f"{SB}/auth/v1/admin/users?page=1&per_page=1000", headers=HEADERS, timeout=45)
    response.raise_for_status()
    users = response.json().get("users", [])
    owner = next(
        (u for u in users if str(u.get("email", "")).lower() == "vivianeferreiracaroline@gmail.com"),
        None,
    )
    if not owner:
        raise RuntimeError("Conta CEO não encontrada no Supabase Auth.")
    return owner["id"]


def claim_job():
    jobs = api(
        "GET",
        "campaign_queue?channel=eq.facebook&status=eq.pending&scheduled_for=lte.now()"
        "&order=scheduled_for.asc&limit=1&select=*",
    ) or []

    if not jobs:
        used = api(
            "GET",
            "campaign_queue?channel=eq.facebook&status=in.(published,processing,pending)"
            "&select=product_id&order=created_at.desc&limit=100",
        ) or []
        used_ids = {str(item["product_id"]) for item in used}
        products = api(
            "GET",
            "products?status=eq.active&image_url=not.is.null&affiliate_url=not.is.null"
            "&select=id,name&order=created_at.asc&limit=100",
        ) or []
        product = next((item for item in products if str(item["id"]) not in used_ids), None)
        if not product:
            product = products[0] if products else None
        if not product:
            print("Nenhum produto ativo com imagem e link.")
            return None

        response = requests.post(
            f"{SB}/rest/v1/campaign_queue",
            headers={**HEADERS, "Prefer": "return=representation"},
            timeout=45,
            json={
                "product_id": str(product["id"]),
                "product_name": product.get("name") or "Produto",
                "channel": "facebook",
                "scheduled_for": datetime.now(timezone.utc).isoformat(),
                "status": "pending",
                "payload": {"automatic": True, "format": "reel"},
                "created_by": ceo_user_id(),
            },
        )
        response.raise_for_status()
        jobs = response.json()

    job = jobs[0]
    attempt = int(job.get("attempts", 0)) + 1
    api(
        "PATCH",
        f"campaign_queue?id=eq.{job['id']}",
        json={"status": "processing", "attempts": attempt, "error_message": None},
    )
    job["attempts"] = attempt
    return job


def product_for(job):
    rows = api(
        "GET",
        f"products?id=eq.{job['product_id']}"
        "&select=id,name,description,price,platform,category,image_url,affiliate_url,status&limit=1",
    ) or []
    if not rows:
        raise RuntimeError("Produto não encontrado.")
    product = rows[0]
    if product.get("status") != "active" or not product.get("image_url") or not product.get("affiliate_url"):
        raise RuntimeError("Produto inativo ou sem imagem/link.")
    return product


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
    response = requests.get(product["image_url"], timeout=45)
    response.raise_for_status()
    src = Image.open(io.BytesIO(response.content)).convert("RGB")
    canvas = Image.new("RGB", (1080, 1920), (12, 8, 35))
    bg = src.copy().resize((1080, 1920)).filter(ImageFilter.GaussianBlur(32))
    canvas.paste(bg, (0, 0))
    overlay = Image.new("RGBA", canvas.size, (8, 4, 28, 145))
    canvas.paste(overlay, (0, 0), overlay)

    pic = src.copy()
    pic.thumbnail((900, 900))
    canvas.paste(pic, ((1080 - pic.width) // 2, 260))

    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((55, 75, 1025, 190), 35, fill=(124, 58, 237))
    draw.text((540, 132), "ACHADINHO VIRALINK", font=font(47, True), anchor="mm", fill="white")

    y = 1210
    for line in wrap(draw, product.get("name", "Oferta imperdível"), font(58, True), 930)[:3]:
        draw.text((540, y), line, font=font(58, True), anchor="ma", fill="white")
        y += 74

    if product.get("price") is not None:
        value = f"R$ {float(product['price']):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        draw.rounded_rectangle((230, 1490, 850, 1630), 38, fill=(22, 163, 74))
        draw.text((540, 1560), value, font=font(68, True), anchor="mm", fill="white")

    draw.text((540, 1740), "Confira a oferta no link", font=font(39, True), anchor="mm", fill="white")
    draw.text((540, 1815), "#Reels  #Achadinhos  #VIRALINK", font=font(30), anchor="mm", fill=(220, 210, 255))
    canvas.save(out, quality=95)


def make_video(poster_path, out):
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
            "-filter_complex", audio,
            "-map", "0:v", "-map", "[a]", "-t", "22",
            "-vf", "scale=1080:1920,format=yuv420p", "-r", "30",
            "-c:v", "libx264", "-preset", "medium",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out),
        ],
        check=True,
    )


def ensure_bucket():
    response = requests.get(f"{SB}/storage/v1/bucket/{BUCKET}", headers=HEADERS, timeout=45)
    if response.status_code == 200:
        return
    if response.status_code != 404:
        response.raise_for_status()
    create = requests.post(
        f"{SB}/storage/v1/bucket",
        headers=HEADERS,
        timeout=45,
        json={
            "id": BUCKET,
            "name": BUCKET,
            "public": True,
            "file_size_limit": 50 * 1024 * 1024,
            "allowed_mime_types": ["video/mp4"],
        },
    )
    if create.status_code not in (200, 201, 409):
        create.raise_for_status()


def upload_temp_video(video_path):
    ensure_bucket()
    object_name = f"facebook/{datetime.now(timezone.utc):%Y/%m/%d}/{uuid.uuid4().hex}.mp4"
    with open(video_path, "rb") as handle:
        response = requests.post(
            f"{SB}/storage/v1/object/{BUCKET}/{object_name}",
            headers={
                "apikey": KEY,
                "Authorization": f"Bearer {KEY}",
                "Content-Type": "video/mp4",
                "x-upsert": "false",
            },
            data=handle,
            timeout=120,
        )
    response.raise_for_status()
    return object_name, f"{SB}/storage/v1/object/public/{BUCKET}/{object_name}"


def delete_temp_video(object_name):
    try:
        requests.delete(
            f"{SB}/storage/v1/object/{BUCKET}/{object_name}",
            headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"},
            timeout=45,
        )
    except requests.RequestException:
        pass


def graph_post(path, values):
    response = requests.post(
        f"https://graph.facebook.com/{GRAPH_VERSION}/{path}",
        data=values,
        timeout=60,
    )
    data = response.json()
    if not response.ok or data.get("error"):
        raise RuntimeError(data.get("error", {}).get("message") or f"Meta HTTP {response.status_code}")
    return data


def facebook_caption(product):
    name = re.sub(r"\s+", " ", str(product.get("name") or "Achadinho")).strip()
    description = re.sub(r"\s+", " ", str(product.get("description") or "")).strip()[:700]
    price = ""
    if product.get("price") is not None:
        price = f"\n💰 R$ {float(product['price']):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return (
        f"{name}\n\n{description}{price}\n\n"
        f"👉 Confira: {product['affiliate_url']}\n\n"
        "#Reels #Achadinhos #Ofertas #VIRALINK"
    )[:5000]


def publish_reel(public_video_url, product):
    start = graph_post(
        f"{PAGE_ID}/video_reels",
        {"upload_phase": "start", "access_token": PAGE_TOKEN},
    )
    video_id = str(start.get("video_id") or "")
    upload_url = str(start.get("upload_url") or "")
    if not video_id or not upload_url.startswith("https://"):
        raise RuntimeError("A Meta não retornou uma sessão de upload válida.")

    upload = requests.post(
        upload_url,
        headers={"Authorization": f"OAuth {PAGE_TOKEN}", "file_url": public_video_url},
        timeout=120,
    )
    upload_data = upload.json()
    if not upload.ok or upload_data.get("error"):
        raise RuntimeError(upload_data.get("error", {}).get("message") or "Falha ao enviar vídeo para a Meta.")

    finish = graph_post(
        f"{PAGE_ID}/video_reels",
        {
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": facebook_caption(product),
            "access_token": PAGE_TOKEN,
        },
    )
    if finish.get("success") is not True:
        raise RuntimeError("A Meta não confirmou a publicação do Reel.")
    return video_id


def main():
    job = claim_job()
    if not job:
        return
    object_name = None
    try:
        product = product_for(job)
        with tempfile.TemporaryDirectory() as td:
            poster_path = Path(td) / "poster.jpg"
            video_path = Path(td) / "reel.mp4"
            poster(product, poster_path)
            make_video(poster_path, video_path)
            object_name, public_url = upload_temp_video(video_path)
            video_id = publish_reel(public_url, product)

        api(
            "PATCH",
            f"campaign_queue?id=eq.{job['id']}",
            json={"status": "published", "external_id": video_id, "error_message": None},
        )
        print(f"Facebook Reel publicado. video_id={video_id}")
    except Exception as exc:
        attempts = int(job.get("attempts", 1))
        status = "failed" if attempts >= 3 else "pending"
        api(
            "PATCH",
            f"campaign_queue?id=eq.{job['id']}",
            json={"status": status, "error_message": str(exc)[:1000]},
        )
        raise
    finally:
        if object_name:
            delete_temp_video(object_name)


if __name__ == "__main__":
    main()
