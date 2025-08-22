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
        "disable_web_page_preview": True
    }
    r = requests.post(url, data=data, timeout=30)
    # Imprime la respuesta de Telegram para una mejor depuración
    if r.status_code != 200:
        print(f" -> [ERROR TELEGRAM] Fallo al publicar: {r.status_code} - {r.text}")
    r.raise_for_status()

# --- Amazon PA-API ---
from amazon_paapi import AmazonApi

AMZ = AmazonApi(
    os.environ["AMAZON_ACCESS_KEY"],
    os.environ["AMAZON_SECRET_KEY"],
    os.environ["AMAZON_TAG"],
    "ES",            # marketplace España
    throttling=1.2   # ayuda a no pasar límites
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
    # Construye caption MarkdownV2
    title = escape_mdv2(title[:120])
    cat = escape_mdv2(cat)
    currency = escape_mdv2(currency)
    
    # --- CORRECCIÓN CLAVE ---
    # NO se debe escapar el link. Esta era la causa del error 400.
    # En su lugar, creamos un enlace con formato MarkdownV2.
    formatted_link = f"[Ver oferta]({link})"

    line1 = f"🛍️ *{title}* — _{cat}_"
    line2 = f"~{orig:.2f}{currency}~ ➜ *{offer:.2f}{currency}* `(−{discount_pct}%)`"
    line3 = f"🔗 {formatted_link}"
    line4 = escape_mdv2(f"🕒 {now_cet_str()} — Precios y disponibilidad pueden cambiar.")
    line5 = escape_mdv2(f"Fuente: {fuente}.")
    line6 = escape_mdv2("Aviso afiliados: puedo ganar comisión por compras que cumplan requisitos.")
    return "\n".join([line1, line2, line3, line4, line5, line6])

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
                res = AMZ.search_items(
                    keywords=kw,
                    search_index=index,
                    item_count=10
                )
            except Exception as e:
                print(f"[ERROR AMAZON] Al buscar '{kw}': {e}")
                continue
            for it in getattr(res, "items", []) or []:
                try:
                    title = it.item_info.title.display_value
                    url = it.detail_page_url
                    img = it.images.primary.large.url
                    listing = it.offers.listings[0]
                    price = listing.price
                    currency = price.currency
                    if price.savings and price.savings.amount and price.savings.percentage:
                        offer = float(price.amount)
                        orig = float(price.savings.baseline_amount)
                        d = int(price.savings.percentage)
                    else:
                        continue
                    if d >= MIN_DISCOUNT:
                        deals.append({
                            "source": "Amazon", "category": cat_name, "title": title,
                            "image": img, "orig": orig, "offer": offer,
                            "currency": currency, "discount": d, "url": url
                        })
                except Exception as e:
                    print(f"[ERROR AMAZON] Al procesar un item '{getattr(it, 'asin', '')}': {e}")
                    continue
    print(f"Encontradas {len(deals)} ofertas en Amazon.")
    return deals

def get_aliexpress_deals():
    print("Buscando ofertas en AliExpress...")
    deals = []
    kws = ["auriculares bluetooth", "ssd", "zapatillas", "smartwatch", "masajeador", "monitor"]
    for kw in kws:
        try:
            resp = ALX.get_products(keywords=kw, target_language=models.Language.ES, page_size=10)
        except Exception as e:
            print(f"[ERROR ALIEXPRESS] Al buscar '{kw}': {e}")
            continue
        for p in getattr(resp, "products", []) or []:
            try:
                title = p.product_title
                img = p.product_main_image_url
                orig = float(p.original_price) if p.original_price else None
                offer = float(p.target_sale_price) if p.target_sale_price else None
                d = None
                if getattr(p, "discount", None):
                    d = int(str(p.discount).replace("%",""))
                elif orig and offer and orig > offer:
                    d = pct(offer, orig)
                if not (orig and offer and d is not None and d >= MIN_DISCOUNT):
                    continue
                link_list = ALX.get_affiliate_links(p.product_detail_url)
                if not link_list: continue
                link = link_list[0].promotion_link
                deals.append({
                    "source": "AliExpress", "category": "AliExpress", "title": title,
                    "image": img, "orig": orig, "offer": offer,
                    "currency": "€", "discount": int(d), "url": link
                })
            except Exception as e:
                print(f"[ERROR ALIEXPRESS] Al procesar un producto '{getattr(p, 'product_id', '')}': {e}")
                continue
    print(f"Encontradas {len(deals)} ofertas en AliExpress.")
    return deals

def main():
    items = get_amazon_deals() + get_aliexpress_deals()
    print(f"\n[INFO] Se encontraron {len(items)} ofertas en total antes de filtrar.")
    items.sort(key=lambda x: x["discount"], reverse=True)
    items = items[:MAX_POSTS]
    print(f"[INFO] Se van a publicar {len(items)} ofertas después de filtrar (MAX_POSTS={MAX_POSTS}).")
    if not items:
        print("[INFO] No hay ofertas para publicar. Terminando ejecución.")
        return
    for i, it in enumerate(items):
        print(f"Publicando oferta {i+1}/{len(items)}: {it['title'][:50]}...")
        currency = it["currency"] if it["currency"] != "EUR" else "€"
        caption = fmt_caption(
            it["title"], it["category"], it["orig"], it["offer"],
            currency, it["discount"], it["url"], it["source"]
        )
        try:
            post_telegram(it["image"], caption)
            print(" -> Publicación exitosa.")
            time.sleep(3) # Aumentar un poco el tiempo para no saturar
        except Exception as e:
            # El error ya se imprime dentro de post_telegram
            continue

if __name__ == "__main__":
    main()
