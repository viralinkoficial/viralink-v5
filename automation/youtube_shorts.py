#!/usr/bin/env python3
"""Cria e publica um Short a partir da fila do VIRALINK."""

import os, subprocess, tempfile, textwrap, asyncio, re
from pathlib import Path
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import edge_tts
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

def api(method, path, **kwargs):
    r = requests.request(method, f"{SB}/rest/v1/{path}", headers=HEADERS, timeout=45, **kwargs)
    r.raise_for_status()
    return r.json() if r.content else None

def claim_job():
    jobs = api("GET", "campaign_queue?channel=eq.youtube&status=eq.pending&scheduled_for=lte.now()&order=scheduled_for.asc&limit=1&select=*")
    if not jobs:
        # Fila vazia: o próprio robô escolhe um produto que ainda não foi publicado.
        used = api("GET", "campaign_queue?channel=eq.youtube&status=eq.published&select=product_id&order=created_at.desc&limit=100") or []
        used_ids = {str(item["product_id"]) for item in used}
        products = api("GET", "products?status=eq.active&image_url=not.is.null&affiliate_url=not.is.null&select=id,name&order=created_at.asc&limit=100") or []
        product = next((item for item in products if str(item["id"]) not in used_ids), None)
        if not product:
            # Quando todos já foram usados, inicia uma nova rodada pelo mais antigo.
            product = products[0] if products else None
        if not product:
            print("Nenhum produto ativo com imagem e link.")
            return None

        users_response = requests.get(f"{SB}/auth/v1/admin/users?page=1&per_page=1000", headers=HEADERS, timeout=45)
        users_response.raise_for_status()
        users = users_response.json().get("users", [])
        owner = next((u for u in users if str(u.get("email","")).lower() == "vivianeferreiracaroline@gmail.com"), None)
        if not owner:
            raise RuntimeError("Conta CEO não encontrada no Supabase Auth.")

        create_response = requests.post(f"{SB}/rest/v1/campaign_queue",
            headers={**HEADERS, "Prefer":"return=representation"}, timeout=45, json={
                "product_id": str(product["id"]),
                "product_name": product.get("name") or "Produto",
                "channel": "youtube",
                "scheduled_for": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                "status": "pending",
                "payload": {"automatic": True},
                "created_by": owner["id"]
            })
        create_response.raise_for_status()
        jobs = create_response.json()

    job = jobs[0]
    api("PATCH", f"campaign_queue?id=eq.{job['id']}", json={"status":"processing","attempts":int(job.get("attempts",0))+1,"error_message":None})
    return job

def product_for(job):
    rows = api("GET", f"products?id=eq.{job['product_id']}&select=id,name,description,price,platform,category,image_url,affiliate_url,status&limit=1")
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
        trial = (line+" "+word).strip()
        if draw.textbbox((0,0), trial, font=fnt)[2] <= width: line = trial
        else:
            if line: lines.append(line)
            line = word
    if line: lines.append(line)
    return lines

def poster(product, out):
    raw = requests.get(product["image_url"], timeout=45); raw.raise_for_status()
    src = Image.open(__import__("io").BytesIO(raw.content)).convert("RGB")
    canvas = Image.new("RGB",(1080,1920),(12,8,35))
    bg = src.copy(); bg.thumbnail((1400,2100))
    bg = bg.resize((1080,1920)).filter(ImageFilter.GaussianBlur(32))
    canvas.paste(bg,(0,0))
    canvas.paste(Image.new("RGBA",canvas.size,(8,4,28,145)),(0,0),Image.new("RGBA",canvas.size,(8,4,28,145)))
    pic = src.copy(); pic.thumbnail((900,900))
    canvas.paste(pic,((1080-pic.width)//2,260),pic if pic.mode=="RGBA" else None)
    d=ImageDraw.Draw(canvas)
    d.rounded_rectangle((55,75,1025,190),35,fill=(124,58,237))
    d.text((540,132),"ACHADINHO VIRALINK",font=font(47,True),anchor="mm",fill="white")
    y=1210
    for line in wrap(d,product.get("name","Oferta imperdível"),font(58,True),930)[:3]:
        d.text((540,y),line,font=font(58,True),anchor="ma",fill="white"); y+=74
    price=product.get("price")
    if price is not None:
        value=f"R$ {float(price):,.2f}".replace(",","X").replace(".",",").replace("X",".")
        d.rounded_rectangle((230,1490,850,1630),38,fill=(22,163,74))
        d.text((540,1560),value,font=font(68,True),anchor="mm",fill="white")
    d.text((540,1740),"Link para comprar na descrição",font=font(39,True),anchor="mm",fill="white")
    d.text((540,1815),"#Shorts  #Achadinhos  #VIRALINK",font=font(30),anchor="mm",fill=(220,210,255))
    canvas.save(out,quality=95)

def narration(product):
    name = re.sub(r"\\s+", " ", str(product.get("name") or "este achadinho")).strip()
    description = re.sub(r"\\s+", " ", str(product.get("description") or "")).strip()
    details = description[:520].rsplit(" ", 1)[0] if len(description) > 520 else description
    price = product.get("price")
    price_text = ""
    if price is not None:
        value = f"{float(price):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        price_text = f" Ele está por {value} reais."
    return (
        f"Olha este achadinho: {name}. "
        f"{details} {price_text} "
        "Confira as informações e o link para comprar na descrição do vídeo."
    )

async def make_voice(text, out):
    speaker = edge_tts.Communicate(text=text, voice="pt-BR-FranciscaNeural", rate="+4%")
    await speaker.save(str(out))

def make_video(poster_path, voice_path, out):
    # Voz principal com trilha instrumental própria e discreta ao fundo.
    audio=("[1:a]volume=1.25[voice];"
           "[2:a]volume=0.025[m0];[3:a]volume=0.018[m1];"
           "[voice][m0][m1]amix=inputs=3:duration=first,"
           "afade=t=in:d=0.4[a]")
    subprocess.run(["ffmpeg","-y","-loop","1","-i",str(poster_path),"-i",str(voice_path),
      "-f","lavfi","-i","sine=frequency=220:duration=60",
      "-f","lavfi","-i","sine=frequency=329.63:duration=60",
      "-filter_complex",audio,"-map","0:v","-map","[a]","-shortest",
      "-vf","scale=1080:1920,format=yuv420p","-r","30","-c:v","libx264","-preset","medium",
      "-c:a","aac","-b:a","160k","-movflags","+faststart",str(out)],check=True)

def upload(video, product):
    creds=Credentials(None,refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
      token_uri="https://oauth2.googleapis.com/token",
      client_id=os.environ["YOUTUBE_CLIENT_ID"],client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
      scopes=["https://www.googleapis.com/auth/youtube.upload"])
    yt=build("youtube","v3",credentials=creds,cache_discovery=False)
    title=(f"{product['name']} | Achadinho VIRALINK #Shorts")[:100]
    desc=(f"{product.get('description') or product['name']}\n\n"
          f"Compre aqui: {product['affiliate_url']}\n\n"
          "#Shorts #Achadinhos #Shopee #VIRALINK")
    body={"snippet":{"title":title,"description":desc,"categoryId":"22",
      "tags":["Shorts","Achadinhos","VIRALINK","ofertas"]},
      "status":{"privacyStatus":os.getenv("YOUTUBE_PRIVACY_STATUS","public"),"selfDeclaredMadeForKids":False}}
    result=yt.videos().insert(part="snippet,status",body=body,
      media_body=MediaFileUpload(str(video),mimetype="video/mp4",resumable=True)).execute()
    return result["id"]

def main():
    job=claim_job()
    if not job: return
    try:
        product=product_for(job)
        with tempfile.TemporaryDirectory() as td:
            poster_path=Path(td)/"poster.jpg"; voice_path=Path(td)/"voice.mp3"; video=Path(td)/"short.mp4"
            poster(product,poster_path)
            asyncio.run(make_voice(narration(product),voice_path))
            make_video(poster_path,voice_path,video)
            video_id=upload(video,product)
        api("PATCH",f"campaign_queue?id=eq.{job['id']}",json={"status":"published","external_id":video_id,"error_message":None})
        print(f"Publicado: https://youtube.com/shorts/{video_id}")
    except Exception as exc:
        attempts=int(job.get("attempts",0))+1
        status="failed" if attempts>=3 else "pending"
        api("PATCH",f"campaign_queue?id=eq.{job['id']}",json={"status":status,"error_message":str(exc)[:1000]})
        raise

if __name__=="__main__": main()
