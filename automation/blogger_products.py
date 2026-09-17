#!/usr/bin/env python3
"""Publica somente produtos ativos do VIRALINK no Blogger."""

import html, os, re
from datetime import datetime, timezone
import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SB=os.environ["SUPABASE_URL"].rstrip("/")
KEY=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
HEADERS={"apikey":KEY,"Authorization":f"Bearer {KEY}","Content-Type":"application/json"}

def api(method,path,**kwargs):
    r=requests.request(method,f"{SB}/rest/v1/{path}",headers=HEADERS,timeout=45,**kwargs)
    r.raise_for_status()
    return r.json() if r.content else None

def owner_id():
    r=requests.get(f"{SB}/auth/v1/admin/users?page=1&per_page=1000",headers=HEADERS,timeout=45)
    r.raise_for_status()
    user=next((u for u in r.json().get("users",[]) if str(u.get("email","")).lower()=="vivianeferreiracaroline@gmail.com"),None)
    if not user: raise RuntimeError("Conta CEO não encontrada.")
    return user["id"]

def select_product():
    used=api("GET","campaign_queue?channel=eq.blogger&status=eq.published&select=product_id&order=created_at.desc&limit=100") or []
    used_ids={str(x["product_id"]) for x in used}
    products=api("GET","products?status=eq.active&image_url=not.is.null&affiliate_url=not.is.null&select=id,name,description,price,platform,category,image_url,affiliate_url&order=created_at.asc&limit=100") or []
    product=next((p for p in products if str(p["id"]) not in used_ids),None)
    return product or (products[0] if products else None)

def create_job(product):
    r=requests.post(f"{SB}/rest/v1/campaign_queue",headers={**HEADERS,"Prefer":"return=representation"},timeout=45,json={
      "product_id":str(product["id"]),"product_name":product.get("name") or "Produto",
      "channel":"blogger","scheduled_for":datetime.now(timezone.utc).isoformat(),
      "status":"processing","attempts":1,"payload":{"automatic":True},"created_by":owner_id()
    })
    r.raise_for_status()
    return r.json()[0]

def access_token():
    creds=Credentials(None,refresh_token=os.environ["BLOGGER_REFRESH_TOKEN"],
      token_uri="https://oauth2.googleapis.com/token",
      client_id=os.environ["BLOGGER_CLIENT_ID"],client_secret=os.environ["BLOGGER_CLIENT_SECRET"],
      scopes=["https://www.googleapis.com/auth/blogger"])
    creds.refresh(Request())
    return creds.token

def blog_id(token):
    url=os.getenv("BLOGGER_BLOG_URL","https://alienigenaorbita.blogspot.com")
    r=requests.get("https://www.googleapis.com/blogger/v3/blogs/byurl",params={"url":url},
      headers={"Authorization":f"Bearer {token}"},timeout=45)
    r.raise_for_status()
    return r.json()["id"]

def clean(text):
    return re.sub(r"\\s+"," ",str(text or "")).strip()

def post_html(p):
    name=html.escape(clean(p.get("name") or "Achadinho VIRALINK"))
    desc=html.escape(clean(p.get("description") or "Confira os detalhes desta oferta."))
    image=html.escape(p["image_url"],quote=True)
    link=html.escape(p["affiliate_url"],quote=True)
    price=p.get("price")
    price_html=""
    if price is not None:
        value=f"{float(price):,.2f}".replace(",","X").replace(".",",").replace("X",".")
        price_html=f'<p style="font-size:28px;font-weight:800;color:#16a34a">R$ {value}</p>'
    return f"""<div style="max-width:760px;margin:auto;font-family:Arial,sans-serif;line-height:1.65;color:#172033">
      <img src="{image}" alt="{name}" style="width:100%;max-height:620px;object-fit:contain;border-radius:18px;background:#f5f3ff">
      <h1 style="font-size:32px">{name}</h1>
      {price_html}
      <p style="font-size:18px">{desc}</p>
      <p><a href="{link}" rel="nofollow sponsored" target="_blank"
        style="display:inline-block;background:#7c3aed;color:white;text-decoration:none;padding:16px 26px;border-radius:12px;font-weight:800">
        Ver produto e comprar
      </a></p>
      <p style="font-size:13px;color:#64748b">Este conteúdo contém link de afiliada. O preço e a disponibilidade podem mudar.</p>
    </div>"""

def publish(token,p):
    bid=blog_id(token)
    title=f"{clean(p.get('name'))} — vale a pena? | VIRALINK"[:100]
    r=requests.post(f"https://www.googleapis.com/blogger/v3/blogs/{bid}/posts/",
      params={"isDraft":"false"},headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},
      json={"kind":"blogger#post","blog":{"id":bid},"title":title,"content":post_html(p),
        "labels":["VIRALINK","Achadinhos",clean(p.get("category") or "Ofertas")]},timeout=60)
    r.raise_for_status()
    return r.json()["id"]

def main():
    p=select_product()
    if not p:
        print("Nenhum produto ativo com imagem e link.")
        return
    job=create_job(p)
    try:
        post_id=publish(access_token(),p)
        api("PATCH",f"campaign_queue?id=eq.{job['id']}",json={"status":"published","external_id":post_id,"error_message":None})
        print(f"Produto publicado no Blogger: {post_id}")
    except Exception as exc:
        api("PATCH",f"campaign_queue?id=eq.{job['id']}",json={"status":"failed","error_message":str(exc)[:1000]})
        raise

if __name__=="__main__": main()
