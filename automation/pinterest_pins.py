#!/usr/bin/env python3
"""Publica no Pinterest Sandbox um Pin de produto real do VIRALINK."""

import base64
import io
import os
import textwrap
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps


def secret(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Segredo obrigatório ausente: {name}")
    return value


SB = secret("SUPABASE_URL").rstrip("/")
KEY = secret("SUPABASE_SERVICE_ROLE_KEY")
PINTEREST_TOKEN_FILE = Path(os.environ.get("PINTEREST_TOKEN_FILE", "pinterest_tokens.json"))
PINTEREST_API = os.environ.get("PINTEREST_API", "https://api-sandbox.pinterest.com/v5").rstrip("/")
HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def supabase(path):
    response = requests.get(f"{SB}/rest/v1/{path}", headers=HEADERS, timeout=45)
    response.raise_for_status()
    return response.json()


def choose_product():
    rows = supabase(
        "products?status=eq.active&image_url=not.is.null&affiliate_url=not.is.null"
        "&select=id,name,description,price,image_url,affiliate_url,category"
        "&order=created_at.asc&limit=500"
    )
    blocked = ("cerveja", "vinho", "whisky", "vodka", "cigarro", "tabaco", "vape")
    rows = [
        p for p in rows
        if not any(word in f"{p.get('name','')} {p.get('category','')}".lower() for word in blocked)
    ]
    if not rows:
        raise RuntimeError("Nenhum produto ativo com imagem e link de compra.")
    run_number = int(os.environ.get("GITHUB_RUN_NUMBER", "1"))
    return rows[(run_number - 1) % len(rows)]


def font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}", size)


def fit_lines(draw, text, fnt, max_width, max_lines):
    words = str(text).split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textbbox((0, 0), trial, font=fnt)[2] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) == max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len(" ".join(lines)) < len(str(text)):
        lines[-1] = lines[-1].rstrip(" .") + "…"
    return lines


def make_card(product):
    response = requests.get(product["image_url"], timeout=45)
    response.raise_for_status()
    src = Image.open(io.BytesIO(response.content)).convert("RGB")

    canvas = Image.new("RGB", (1000, 1500), "#351071")
    draw = ImageDraw.Draw(canvas)

    draw.text((500, 48), "VIRALINK • ACHADINHO", font=font(28, True), anchor="ma", fill="#d8c9ff")

    frame = (70, 115, 930, 865)
    draw.rounded_rectangle(frame, radius=30, fill="white")
    fitted = ImageOps.contain(src, (800, 690), Image.Resampling.LANCZOS)
    x = 500 - fitted.width // 2
    y = 490 - fitted.height // 2
    canvas.paste(fitted, (x, y))

    title_font = font(43, True)
    y_text = 920
    for line in fit_lines(draw, product.get("name") or "Achadinho VIRALINK", title_font, 860, 3):
        draw.text((500, y_text), line, font=title_font, anchor="ma", fill="white")
        y_text += 58

    price = product.get("price")
    if price is not None:
        value = f"R$ {float(price):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        draw.text((500, 1190), value, font=font(60, True), anchor="mm", fill="#ffd84d")

    draw.rounded_rectangle((170, 1280, 830, 1385), radius=34, fill="#ffffff")
    draw.text((500, 1332), "VEJA A OFERTA • LINK NO PIN", font=font(28, True), anchor="mm", fill="#351071")

    output = io.BytesIO()
    canvas.save(output, format="JPEG", quality=92, optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")


def pinterest_headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def first_board(token):
    response = requests.get(
        f"{PINTEREST_API}/boards?page_size=25",
        headers=pinterest_headers(token),
        timeout=45,
    )
    response.raise_for_status()
    items = response.json().get("items", [])
    if not items:
        raise RuntimeError("Nenhum painel disponível no Pinterest Sandbox.")
    return items[0]["id"]


def publish(product, token, board_id, image_data):
    description = (product.get("description") or product["name"]).strip()
    payload = {
        "board_id": board_id,
        "title": product["name"][:100],
        "description": f"{description[:350]}\n\nConfira a oferta no link.",
        "link": product["affiliate_url"],
        "alt_text": f"{product['name']} disponível na vitrine VIRALINK"[:500],
        "media_source": {
            "source_type": "image_base64",
            "content_type": "image/jpeg",
            "data": image_data,
        },
    }
    response = requests.post(
        f"{PINTEREST_API}/pins",
        headers={**pinterest_headers(token), "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    if response.status_code != 201:
        try:
            detail = response.json().get("message", "sem detalhes")
        except Exception:
            detail = "sem detalhes"
        raise RuntimeError(f"Pinterest recusou o Pin. HTTP {response.status_code}: {detail}")
    return response.json()["id"]


def main():
    tokens = __import__("json").loads(PINTEREST_TOKEN_FILE.read_text(encoding="utf-8"))
    token = tokens.get("access_token", "").strip()
    if not token:
        raise RuntimeError("Token do Pinterest ausente.")

    product = choose_product()
    card = make_card(product)
    board_id = first_board(token)
    pin_id = publish(product, token, board_id, card)
    print(f"Pin de produto publicado com sucesso. ID: {pin_id}")
    print(f"Produto: {product['name']}")


if __name__ == "__main__":
    main()
