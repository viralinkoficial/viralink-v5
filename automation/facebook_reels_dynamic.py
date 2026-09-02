#!/usr/bin/env python3
"""Modelo dinâmico de Reels do Facebook para o VIRALINK.

Mantém a publicação segura do robô original, mas troca o vídeo estático por
quatro cenas verticais com cortes rápidos, zoom suave, preço, benefício, CTA
e uma trilha instrumental gerada localmente conforme a categoria do produto.
"""

import io
import re
import subprocess
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import facebook_reels as base


W, H = 1080, 1920


def font(size: int, bold: bool = False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}", size)


def clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def wrap(draw, text, fnt, width, max_lines=3):
    words = clean(text).split()
    lines, line = [], ""
    for word in words:
        trial = (line + " " + word).strip()
        if draw.textbbox((0, 0), trial, font=fnt)[2] <= width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
            if len(lines) >= max_lines:
                break
    if line and len(lines) < max_lines:
        lines.append(line)
    if words and len(lines) == max_lines:
        consumed = " ".join(lines)
        if len(consumed) < len(clean(text)):
            lines[-1] = lines[-1].rstrip(" .") + "…"
    return lines


def price_text(product):
    if product.get("price") is None:
        return "VEJA O PREÇO"
    return f"R$ {float(product['price']):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def benefit_text(product):
    description = clean(product.get("description"))
    if not description:
        return "Achadinho selecionado automaticamente pelo VIRALINK."
    first = re.split(r"(?<=[.!?])\s+", description)[0]
    if len(first) > 145:
        first = first[:142].rsplit(" ", 1)[0] + "…"
    return first


def music_style(product):
    """Escolhe uma trilha instrumental sem depender de áudio externo."""
    haystack = " ".join(
        clean(product.get(key)).lower()
        for key in ("name", "category", "description", "platform")
    )

    electronics = (
        "fone", "bluetooth", "smartwatch", "relógio", "celular", "smartphone",
        "carregador", "usb", "led", "eletr", "tecnologia", "gamer", "headset",
        "caixa de som", "projeção", "projetor", "cabo", "power bank",
    )
    beauty = (
        "beleza", "skincare", "sérum", "serum", "pele", "cabelo", "cachos",
        "shampoo", "maquiagem", "cosmético", "cosmetico", "unha", "creme",
    )
    promo = (
        "promoção", "promocao", "oferta", "desconto", "liquidação", "liquidacao",
        "imperdível", "imperdivel", "kit", "leve 2", "combo",
    )

    if any(term in haystack for term in electronics):
        return "electronic_fast"
    if any(term in haystack for term in beauty):
        return "beauty_soft"
    if any(term in haystack for term in promo):
        return "sales_energy"
    return "upbeat"


def download_image(product):
    response = requests.get(product["image_url"], timeout=45)
    response.raise_for_status()
    return Image.open(io.BytesIO(response.content)).convert("RGB")


def background(src, strength=155):
    bg = src.copy().resize((W, H)).filter(ImageFilter.GaussianBlur(38))
    canvas = Image.new("RGB", (W, H))
    canvas.paste(bg, (0, 0))
    overlay = Image.new("RGBA", (W, H), (7, 4, 25, strength))
    canvas.paste(overlay, (0, 0), overlay)
    return canvas


def product_card(canvas, src, box, radius=42):
    x1, y1, x2, y2 = box
    cw, ch = x2 - x1, y2 - y1
    card = Image.new("RGBA", (cw, ch), (248, 248, 250, 255))
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw, ch), radius, fill=255)

    pic = src.copy()
    pic.thumbnail((cw - 70, ch - 70), Image.Resampling.LANCZOS)
    card.alpha_composite(pic.convert("RGBA"), ((cw - pic.width) // 2, (ch - pic.height) // 2))
    canvas.paste(card, (x1, y1), mask)


def watermark(draw):
    draw.rounded_rectangle((760, 44, 1030, 118), 24, fill=(20, 13, 48, 210))
    draw.text((895, 81), "VIRALINK", font=font(29, True), anchor="mm", fill="white")


def scene_hook(src, product):
    canvas = background(src, 145)
    draw = ImageDraw.Draw(canvas, "RGBA")
    watermark(draw)
    draw.rounded_rectangle((70, 165, 1010, 320), 42, fill=(124, 58, 237, 245))
    draw.text((540, 242), "OLHA ESSE ACHADINHO!", font=font(57, True), anchor="mm", fill="white")
    product_card(canvas, src, (70, 385, 1010, 1325))
    draw.rounded_rectangle((170, 1415, 910, 1560), 38, fill=(255, 255, 255, 235))
    draw.text((540, 1488), "OFERTA DO DIA", font=font(54, True), anchor="mm", fill=(45, 24, 92))
    draw.text((540, 1670), "Veja até o final", font=font(40, True), anchor="mm", fill="white")
    draw.text((540, 1740), "produto • preço • link", font=font(31), anchor="mm", fill=(230, 222, 255))
    return canvas


def scene_product(src, product):
    canvas = background(src, 160)
    draw = ImageDraw.Draw(canvas, "RGBA")
    watermark(draw)
    draw.text((70, 165), "VALE A PENA?", font=font(58, True), fill="white")
    category = clean(product.get("category")) or "Achadinho"
    draw.rounded_rectangle((70, 250, 70 + min(600, 44 + len(category) * 22), 330), 28, fill=(124, 58, 237, 235))
    draw.text((95, 290), category[:24].upper(), font=font(28, True), anchor="lm", fill="white")
    product_card(canvas, src, (55, 385, 1025, 1325))
    name_font = font(48, True)
    y = 1435
    for line in wrap(draw, product.get("name") or "Oferta selecionada", name_font, 940, 3):
        draw.text((540, y), line, font=name_font, anchor="ma", fill="white")
        y += 63
    return canvas


def scene_price(src, product):
    canvas = background(src, 175)
    draw = ImageDraw.Draw(canvas, "RGBA")
    watermark(draw)
    draw.text((540, 170), "PREÇO ENCONTRADO", font=font(52, True), anchor="mm", fill="white")
    product_card(canvas, src, (155, 265, 925, 1035))
    draw.rounded_rectangle((140, 1120, 940, 1305), 48, fill=(22, 163, 74, 245))
    draw.text((540, 1212), price_text(product), font=font(78, True), anchor="mm", fill="white")
    draw.text((540, 1400), "DESTAQUE", font=font(30, True), anchor="mm", fill=(204, 190, 255))
    benefit_font = font(37, True)
    y = 1460
    for line in wrap(draw, benefit_text(product), benefit_font, 900, 3):
        draw.text((540, y), line, font=benefit_font, anchor="ma", fill="white")
        y += 50
    draw.text((540, 1770), "Preço e disponibilidade podem mudar", font=font(25), anchor="mm", fill=(226, 220, 240))
    return canvas


def scene_cta(src, product):
    canvas = background(src, 165)
    draw = ImageDraw.Draw(canvas, "RGBA")
    watermark(draw)
    draw.text((540, 180), "QUER VER A OFERTA?", font=font(56, True), anchor="mm", fill="white")
    product_card(canvas, src, (160, 295, 920, 1055))
    draw.rounded_rectangle((105, 1150, 975, 1365), 52, fill=(124, 58, 237, 250))
    draw.text((540, 1258), "LINK NA DESCRIÇÃO", font=font(61, True), anchor="mm", fill="white")
    draw.text((540, 1480), "Confira o preço e a disponibilidade", font=font(36, True), anchor="mm", fill="white")
    draw.text((540, 1560), "antes que a oferta mude", font=font(32), anchor="mm", fill=(226, 219, 250))
    draw.rounded_rectangle((300, 1690, 780, 1810), 36, fill=(255, 255, 255, 235))
    draw.text((540, 1750), "VIRALINK", font=font(45, True), anchor="mm", fill=(70, 38, 145))
    return canvas


def dynamic_poster(product, out):
    src = download_image(product)
    out = Path(out)
    scenes = [
        scene_hook(src, product),
        scene_product(src, product),
        scene_price(src, product),
        scene_cta(src, product),
    ]
    for idx, image in enumerate(scenes, start=1):
        path = out if idx == 1 else out.parent / f"scene_{idx}.jpg"
        image.save(path, quality=94, optimize=True)

    # Guarda apenas o nome do perfil musical no diretório temporário.
    # Nenhum áudio externo ou protegido por direitos autorais é baixado.
    (out.parent / "music_style.txt").write_text(music_style(product), encoding="utf-8")


def make_clip(scene_path, clip_path, duration, zoom_speed):
    vf = (
        "scale=1200:2134,"
        f"zoompan=z='min(max(pzoom,1.0)+{zoom_speed},1.12)':"
        "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        "d=1:s=1080x1920:fps=30,format=yuv420p"
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-loop", "1", "-t", str(duration), "-i", str(scene_path),
            "-vf", vf, "-r", "30", "-an", "-c:v", "libx264", "-preset", "medium",
            "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(clip_path),
        ],
        check=True,
    )


def music_config(style, total):
    """Retorna frequências e mix para uma trilha instrumental sintética."""
    configs = {
        "electronic_fast": {
            "freqs": (220.00, 329.63, 440.00),
            "filters": (
                "[1:a]volume=0.038,tremolo=f=6.8:d=0.78[a0];"
                "[2:a]volume=0.025,tremolo=f=3.4:d=0.62[a1];"
                "[3:a]volume=0.014,tremolo=f=6.8:d=0.50[a2];"
            ),
        },
        "beauty_soft": {
            "freqs": (174.61, 220.00, 261.63),
            "filters": (
                "[1:a]volume=0.024,tremolo=f=1.8:d=0.25[a0];"
                "[2:a]volume=0.017,tremolo=f=1.2:d=0.20[a1];"
                "[3:a]volume=0.010,tremolo=f=1.8:d=0.18[a2];"
            ),
        },
        "sales_energy": {
            "freqs": (196.00, 293.66, 392.00),
            "filters": (
                "[1:a]volume=0.036,tremolo=f=7.4:d=0.82[a0];"
                "[2:a]volume=0.022,tremolo=f=3.7:d=0.64[a1];"
                "[3:a]volume=0.013,tremolo=f=7.4:d=0.52[a2];"
            ),
        },
        "upbeat": {
            "freqs": (196.00, 246.94, 329.63),
            "filters": (
                "[1:a]volume=0.030,tremolo=f=4.4:d=0.55[a0];"
                "[2:a]volume=0.020,tremolo=f=2.2:d=0.42[a1];"
                "[3:a]volume=0.012,tremolo=f=4.4:d=0.36[a2];"
            ),
        },
    }
    cfg = configs.get(style, configs["upbeat"])
    mix = (
        cfg["filters"]
        + "[a0][a1][a2]amix=inputs=3:duration=longest:normalize=0,"
        + f"afade=t=in:d=0.30,afade=t=out:st={total - 1.35:.2f}:d=1.35[a]"
    )
    return cfg["freqs"], mix


def dynamic_make_video(poster_path, out):
    poster_path = Path(poster_path)
    out = Path(out)
    scenes = [poster_path] + [poster_path.parent / f"scene_{i}.jpg" for i in range(2, 5)]
    durations = [3.4, 4.5, 4.6, 4.5]
    speeds = ["0.00145", "0.00090", "0.00115", "0.00075"]
    clips = []

    for idx, (scene, duration, speed) in enumerate(zip(scenes, durations, speeds), start=1):
        clip = poster_path.parent / f"clip_{idx}.mp4"
        make_clip(scene, clip, duration, speed)
        clips.append(clip)

    concat_file = poster_path.parent / "clips.txt"
    concat_file.write_text("".join(f"file '{clip.as_posix()}'\n" for clip in clips), encoding="utf-8")
    total = sum(durations)
    style_file = poster_path.parent / "music_style.txt"
    style = style_file.read_text(encoding="utf-8").strip() if style_file.exists() else "upbeat"
    freqs, audio = music_config(style, total)

    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-f", "lavfi", "-i", f"sine=frequency={freqs[0]}:duration={total:.2f}",
            "-f", "lavfi", "-i", f"sine=frequency={freqs[1]}:duration={total:.2f}",
            "-f", "lavfi", "-i", f"sine=frequency={freqs[2]}:duration={total:.2f}",
            "-filter_complex", audio,
            "-map", "0:v:0", "-map", "[a]", "-t", f"{total:.2f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "22",
            "-c:a", "aac", "-b:a", "160k", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(out),
        ],
        check=True,
    )
    print(f"Trilha automática aplicada: {style}")


# Troca apenas a camada visual e musical; fila, upload, token e publicação
# continuam usando o robô já testado e aprovado.
base.poster = dynamic_poster
base.make_video = dynamic_make_video
main = base.main


if __name__ == "__main__":
    main()
