import os, math, time, requests
from datetime import datetime
import pytz

# --- Telegram ---
TG_BOT_TOKEN = os.environ["TG_BOT_TOKEN"]
TG_CHANNEL_ID = os.environ["TG_CHANNEL_ID"]

def escape_mdv2(text: str) -> str:
    specials = r'_\*\[\]\(\)~`>#+\-=|{}\.!'
    out = []
    for ch in text:
        out.append("\\" + ch if ch in specials else ch)
    return "".join(out)

def post_telegram(photo_url: str, caption_md: str):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
    data = {
        "chat_id": TG_CHANNEL_ID,
        "photo": photo_url,
        "caption": caption_md,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": False
    }
    r = requests.post(url, data=data, timeout=30)
    if r.status_code != 200:
        print(f" -> [ERROR TELEGRAM] Fallo al publicar: {r.status_code} - {r.text}")
    r.raise_for_status()

# --- APIs ---
from amazon_paapi import AmazonApi
AMZ = AmazonApi(os.environ["AMAZON_ACCESS_KEY"], os.environ["AMAZON_SECRET_KEY"], os.environ["AMAZON_TAG"], "ES", throttling=1.2)

from aliexpress_api import AliexpressApi, models
ALX = AliexpressApi(os.environ["ALX_APP_KEY"], os.environ["ALX_SECRET"], models.Language.ES, models.Currency.EUR, os.environ["ALX_PID"])

MIN_DISCOUNT = int(os.getenv("MIN_DISCOUNT", "25"))
MAX_POSTS = int(os.getenv("MAX_POSTS", "8"))

def pct(off, orig):
    try: return round(100.0 * (orig - off) / orig)
    except: return None

def now_cet_str():
    return datetime.now(pytz.timezone("Europe/Madrid")).strftime("%d/%m %H:%M")

def fmt_caption(title, cat, orig, offer, currency, discount_pct, link, fuente):
    escaped_title = escape_mdv2(title[:120])
    escaped_cat = escape_mdv2(cat)
    escaped_currency = escape_mdv2(currency)
    orig_price_str = escape_mdv2(f"{orig:.2f}")
    offer_price_str = escape_mdv2(f"{offer:.2f}")

    line1 = f"🛍️ *{escaped_title}* — _{escaped_cat}_"
    line2 = f"~{orig_price_str}{escaped_currency}~ ➜ *{offer_price_str}{escaped_currency}* `(−{discount_pct}%)`"
    line3 = f"🔗 [Ver oferta]({link})"
    line4 = escape_mdv2(f"🕒 {now_cet_str()} — Precios y disponibilidad pueden cambiar.")
    line5 = escape_mdv2(f"Fuente: {fuente}.")
    line6 = escape_mdv2("Aviso afiliados: puedo ganar comisión por compras que cumplan requisitos.")
    
    return "\n".join([line1, line2, line3, "\n" + line4, line5, line6])

def get_amazon_deals():
    print("Buscando ofertas en Amazon...")
    deals = []
    searches = [
        ("Tecnología", "Electronics", ["ssd", "monitor", "ratón", "teclado", "smartwatch"]),
        ("Salud", "HealthPersonalCare", ["cepillo dental", "masajeador", "oxímetro", "vitamina"]),
        ("Moda", "Fashion", ["zapatillas", "chaqueta", "mochila", "reloj"])
    ]
    for cat_name, index, kws in searches:
        for kw in kws:
            try:
                res = AMZ.search_items(keywords=kw, search_index=index, item_count=10)
            except Exception as e:
                print(f"[ERROR AMAZON] Al buscar '{kw}': {e}")
                continue
            for it in getattr(res, "items", []) or []:
                try:
                    price = it.offers.listings[0].price
                    if price.savings and price.savings.amount and price.savings.percentage:
                        if int(price.savings.percentage) >= MIN_DISCOUNT:
                            deals.append({
                                "source": "Amazon", "category": cat_name, "title": it.item_info.title.display_value,
                                "image": it.images.primary.large.url, "orig": float(price.savings.baseline_amount), 
                                "offer": float(price.amount), "currency": price.currency, 
                                "discount": int(price.savings.percentage), "url": it.detail_page_url
                            })
                except Exception: continue
    print(f"Encontradas {len(deals)} ofertas en Amazon.")
    return deals

def get_aliexpress_deals():
    print("Buscando ofertas en AliExpress...")
    deals = []
    kws = ["auriculares bluetooth", "ssd", "zapatillas", "smartwatch", "masajeador", "monitor"]

    # --- FILTROS DE SENTIDO COMÚN ---
    MAX_ORIGINAL_PRICE = int(os.getenv("MAX_ORIGINAL_PRICE", 300.0)) # No mostrar ofertas con precio original > 300€
    MAX_DISCOUNT_PERCENTAGE = int(os.getenv("MAX_DISCOUNT_PERCENTAGE", 85)) # No mostrar ofertas con más de 85% de descuento
    

    for kw in kws:
        try:
            resp = ALX.get_products(keywords=kw, target_language=models.Language.ES, page_size=20)
        except Exception as e:
            print(f"[ERROR ALIEXPRESS] Al buscar '{kw}': {e}")
            continue
        for p in getattr(resp, "products", []) or []:
            try:
                orig = float(p.original_price) if p.original_price else None
                offer = float(p.target_sale_price) if p.target_sale_price else None
                
                if not (orig and offer): continue

                # --- APLICACIÓN DE LOS NUEVOS FILTROS ---
                if orig > MAX_ORIGINAL_PRICE:
                    # print(f"[FILTRADO] Precio original demasiado alto: {p.product_title} ({orig}€)")
                    continue

                d = None
                if getattr(p, "discount", None): d = int(str(p.discount).replace("%",""))
                elif orig > offer: d = pct(offer, orig)
                
                if not (d and d >= MIN_DISCOUNT): continue

                if d > MAX_DISCOUNT_PERCENTAGE:
                    # print(f"[FILTRADO] Descuento irreal: {p.product_title} ({d}%)")
                    continue

                link_list = ALX.get_affiliate_links(p.product_detail_url)
                if not link_list: continue

                deals.append({
                    "source": "AliExpress", "category": "AliExpress", "title": p.product_title,
                    "image": p.product_main_image_url, "orig": orig, "offer": offer,
                    "currency": "€", "discount": int(d), "url": link_list[0].promotion_link
                })
            except Exception: continue
    print(f"Encontradas {len(deals)} ofertas en AliExpress (después de filtrar).")
    return deals

def main():
    items = get_amazon_deals() + get_aliexpress_deals()
    print(f"\n[INFO] Se encontraron {len(items)} ofertas en total.")
    items.sort(key=lambda x: x["discount"], reverse=True)
    items = items[:MAX_POSTS]
    print(f"[INFO] Se van a publicar {len(items)} ofertas (MAX_POSTS={MAX_POSTS}).")
    if not items:
        print("[INFO] No hay ofertas para publicar.")
        return
    for i, it in enumerate(items):
        print(f"Publicando oferta {i+1}/{len(items)}: {it['title'][:50]}...")
        try:
            caption = fmt_caption(it["title"], it["category"], it["orig"], it["offer"],
                                  it["currency"], it["discount"], it["url"], it["source"])
            post_telegram(it["image"], caption)
            print(" -> Publicación exitosa.")
            time.sleep(3)
        except Exception as e:
            print(f" -> Fallo en el bucle principal: {e}")
            continue

if __name__ == "__main__":
    main()

