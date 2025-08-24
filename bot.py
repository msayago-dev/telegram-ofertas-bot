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
    # (En el futuro, puedes aplicar filtros similares a los de AliExpress aquí también)
    print(f"Encontradas {len(deals)} ofertas en Amazon.")
    return deals

def get_aliexpress_deals():
    print("Buscando ofertas en AliExpress con filtros avanzados...")
    deals = []
    kws = [
        "cargador GaN 100W", "power bank magnética", "mini proyector portátil 4K",
        "teclado mecánico inalámbrico", "ratón vertical ergonómico", "cámara de seguridad WiFi exterior",
        "auriculares con cancelación de ruido activa", "rastreador de objetos Bluetooth",
        "pistola de masaje muscular", "masajeador de cuello shiatsu", "cepillo de dientes sónico",
        "irrigador dental portátil", "rodillo de jade facial", "humidificador ultrasónico",
        "corrector de postura inteligente", "mochila antirrobo para portátil", "reloj inteligente con NFC",
        "gafas de luz azul", "cinturón de cuero automático", "chaqueta cortavientos impermeable", "zapatillas de trekking"
    ]
    # kws = [ "tecnologia", "tecnology"]
    
    # --- FILTROS DE SENTIDO COMÚN ---
    MAX_ORIGINAL_PRICE = int(os.getenv("MAX_ORIGINAL_PRICE", 300.0)) # No mostrar ofertas con precio original > 300€
    MAX_DISCOUNT_PERCENTAGE = int(os.getenv("MAX_DISCOUNT_PERCENTAGE", 60)) # No mostrar ofertas con más de 85% de descuento
    MIN_ORDERS = int(os.getenv("MIN_ORDERS", 50)) # El producto debe tener al menos 50 ventas
    MIN_RATING = int(os.getenv("MIN_RATING", 4.5)) # La valoración media debe ser de 4.5 estrellas o más

    for kw in kws:
        try:
            resp = ALX.get_products(keywords=kw, target_language=models.Language.ES, page_size=100)
            #print(f"Encontradas {len(resp)} ofertas en AliExpress para la palabra clave {kw}.")
        except Exception as e:
            print(f"[ERROR ALIEXPRESS] Al buscar '{kw}': {e}")
            continue
        for p in getattr(resp, "products", []) or []:
            try:
                orig = float(p.original_price) if p.original_price else None
                offer = float(p.target_sale_price) if p.target_sale_price else None

                print(f"Producto {p.product_title}, {orig}, {offer}")
                
                if not (orig and offer) or orig > MAX_ORIGINAL_PRICE: continue

                product_rating = float(getattr(p, 'evaluate_rate', '0.0').replace('%', '')) / 20.0
                orders_count = int(getattr(p, 'sale_volume', 0))

                print(f"Producto {p.product_title}, orig {orig}, offer {offer}, product_rating {product_rating}, orders_count {orders_count}")

                if orders_count < MIN_ORDERS or product_rating < MIN_RATING: continue

                d = pct(offer, orig)
                
                if not (d and d >= MIN_DISCOUNT and d >= MAX_DISCOUNT_PERCENTAGE): continue

                link_list = ALX.get_affiliate_links(p.product_detail_url)
                if not link_list: continue
                    
                deals.append({
                    "source": "AliExpress", "category": "AliExpress", "title": p.product_title,
                    "image": p.product_main_image_url, "orig": orig, "offer": offer,
                    "currency": "€", "discount": int(d), "url": link_list[0].promotion_link
                })
            except Exception as e:
                print(f"[ERROR] Procesando producto de AliExpress: {e}")
                continue
            
    print(f"Encontradas {len(deals)} ofertas en AliExpress (después de todos los filtros).")
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














