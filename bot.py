import os, math, time, requests
from datetime import datetime
import pytz

# --- Telegram ---
TG_BOT_TOKEN = os.environ["TG_BOT_TOKEN"]
TG_CHANNEL_ID = os.environ["TG_CHANNEL_ID"]

def escape_mdv2(text: str) -> str:
    # Escapa caracteres especiales de MarkdownV2
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
        "disable_web_page_preview": False # Ponemos a False para que el link se vea mejor
    }
    r = requests.post(url, data=data, timeout=30)
    if r.status_code != 200:
        print(f" -> [ERROR TELEGRAM] Fallo al publicar: {r.status_code} - {r.text}")
    r.raise_for_status()

# --- Amazon PA-API ---
from amazon_paapi import AmazonApi

AMZ = AmazonApi(
    os.environ["AMAZON_ACCESS_KEY"],
    os.environ["AMAZON_SECRET_KEY"],
    os.environ["AMAZON_TAG"],
    "ES",
    throttling=1.2
)

# --- AliExpress Open Platform (wrapper) ---
from aliexpress_api import AliexpressApi, models

ALX = AliexpressApi(
    os.environ["ALX_APP_KEY"],
    os.environ["ALX_SECRET"],
    models.Language.ES,
    models.Currency.EUR,
    os.environ["ALX_PID"]
)

MIN_DISCOUNT = int(os.getenv("MIN_DISCOUNT", "25"))
MAX_POSTS = int(os.getenv("MAX_POSTS", "8"))

def pct(off, orig):
    try:
        return round(100.0 * (orig - off) / orig)
    except Exception:
        return None

def now_cet_str():
    cet = pytz.timezone("Europe/Madrid")
    return datetime.now(cet).strftime("%d/%m %H:%M")

def fmt_caption(title, cat, orig, offer, currency, discount_pct, link, fuente):
    # --- FUNCIÓN CORREGIDA PARA SOLUCIONAR EL ERROR DEL '.' ---
    
    # 1. Escapar el texto que puede contener caracteres especiales
    escaped_title = escape_mdv2(title[:120])
    escaped_cat = escape_mdv2(cat)
    
    # 2. Formatear precios (los puntos decimales son seguros, no se escapan)
    orig_price_str = f"{orig:.2f}"
    offer_price_str = f"{offer:.2f}"
    escaped_currency = escape_mdv2(currency)

    # 3. Construir las líneas con una mezcla de Markdown y texto escapado
    line1 = f"🛍️ *{escaped_title}* — _{escaped_cat}_"
    line2 = f"~{orig_price_str}{escaped_currency}~ ➜ *{offer_price_str}{escaped_currency}* `(−{discount_pct}%)`"
    
    # El formato del link [texto](url) no debe ser escapado
    line3 = f"🔗 [Ver oferta]({link})"

    # 4. Escapar completamente las líneas de texto del pie de página
    line4 = escape_mdv2(f"🕒 {now_cet_str()} — Precios y disponibilidad pueden cambiar.")
    line5 = escape_mdv2(f"Fuente: {fuente}.")
    line6 = escape_mdv2("Aviso afiliados: puedo ganar comisión por compras que cumplan requisitos.")
    
    return "\n".join([line1, line2, line3, "\n" + line4, line5, line6])

def get_amazon_deals():
    print("Buscando ofertas en Amazon...")
    deals = []
    # (El resto de la función es correcta, la dejamos como está)
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
    # (El resto de la función es correcta, la dejamos como está)
    kws = ["auriculares bluetooth", "ssd", "zapatillas", "smartwatch", "masajeador", "monitor"]
    for kw in kws:
        try:
            resp = ALX.get_products(keywords=kw, target_language=models.Language.ES, page_size=10)
        except Exception as e:
            print(f"[ERROR ALIEXPRESS] Al buscar '{kw}': {e}")
            continue
        for p in getattr(resp, "products", []) or []:
            try:
                orig = float(p.original_price) if p.original_price else None
                offer = float(p.target_sale_price) if p.target_sale_price else None
                d = None
                if getattr(p, "discount", None): d = int(str(p.discount).replace("%",""))
                elif orig and offer and orig > offer: d = pct(offer, orig)
                if not (orig and offer and d is not None and d >= MIN_DISCOUNT): continue
                link_list = ALX.get_affiliate_links(p.product_detail_url)
                if not link_list: continue
                deals.append({
                    "source": "AliExpress", "category": "AliExpress", "title": p.product_title,
                    "image": p.product_main_image_url, "orig": orig, "offer": offer,
                    "currency": "€", "discount": int(d), "url": link_list[0].promotion_link
                })
            except Exception: continue
    print(f"Encontradas {len(deals)} ofertas en AliExpress.")
    return deals

def main():
    items = get_amazon_deals() + get_aliexpress_deals()
    print(f"\n[INFO] Se encontraron {len(items)} ofertas en total antes de filtrar.")
    items.sort(key=lambda x: x["discount"], reverse=True)
    items = items[:MAX_POSTS]
    print(f"[INFO] Se van a publicar {len(items)} ofertas (MAX_POSTS={MAX_POSTS}).")
    if not items:
        print("[INFO] No hay ofertas para publicar.")
        return
    for i, it in enumerate(items):
        print(f"Publicando oferta {i+1}/{len(items)}: {it['title'][:50]}...")
        try:
            caption = fmt_caption(
                it["title"], it["category"], it["orig"], it["offer"],
                it["currency"], it["discount"], it["url"], it["source"]
            )
            post_telegram(it["image"], caption)
            print(" -> Publicación exitosa.")
            time.sleep(3)
        except Exception as e:
            print(f" -> Fallo en el bucle principal: {e}")
            continue

if __name__ == "__main__":
    main()
