import os
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")

def categorize_product(title: str, url: str) -> str:
    text = f"{title} {url}".lower()
    if any(k in text for k in ["parfüm", "perfume", "parfum", "eau de", "edt", "edp", "cologne", "lõhn"]): return "Perfume"
    if any(k in text for k in ["huule", "pudel", "mascara", "ripsme", "jumestus", "foundation", "lipstick", "makeup", "puder", "põsepuna", "laovärv", "peitepulk", "küünelakk", "gloss"]): return "Makeup"
    if any(k in text for k in ["šampoon", "shampoo", "palsam", "conditioner", "juukse", "hair", "mask", "õli", "seerum", "juustele"]): return "Hair care"
    if any(k in text for k in ["näo", "facial", "face", "kreem", "cream", "seerum", "serum", "toonik", "puhastus", "cleanser", "silma", "silmakreem"]): return "Facial care"
    if any(k in text for k in ["keha", "body", "duši", "shower", "kreem", "lotion", "seep", "scrub", "koorija", "deodorant"]): return "Body care"
    if any(k in text for k in ["hamba", "oral", "tooth", "paste", "hari", "brush", "suuvesi"]): return "Oral care"
    if any(k in text for k in ["laps", "beebi", "baby", "child", "mother", "ema", "mähkmed"]): return "Mother and child"
    if any(k in text for k in ["meeste", "men", "for men", "habeme", "shave", "aftershave"]): return "For men"
    if any(k in text for k in ["päike", "sun", "spf", "päevitus", "after sun"]): return "Sun"
    if any(k in text for k in ["seade", "sirgendaja", "kuivati", "dryer", "trimmer", "epilaator", "electrical"]): return "Electrical equipment"
    if any(k in text for k in ["derma", "apteek", "pharmacy", "sensitive"]): return "Dermacosmetics"
    if any(k in text for k in ["luxury", "luksus", "exclusive"]): return "Luxury"
    return "Facial care"

def save_product(title, fallback_cat, store, current_price, original_price, img, url, volume=""):
    bad_titles = ["ALLAHINDLUS!", "UUS!", "SALE", "ALE", "SOODUSTUS", "OSTA", "PRIVACY", "COOKIES", "NÕUSTUN"]
    if not title or len(title) < 3 or title.strip().upper() in bad_titles: return

    category = categorize_product(title, url)
    discount_pct = 0
    if original_price and original_price > current_price:
        discount_pct = round(((original_price - current_price) / original_price) * 100)

    if not DATABASE_URL:
        print(f"🔍 [DRY-RUN] {store} | {title} | €{current_price} (-{discount_pct}%)")
        return

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO beauty_products 
            (title, category, store_name, current_price, original_price, discount_percentage, image_url, product_url, volume_size, is_discounted)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (store_name, title, volume_size) 
            DO UPDATE SET 
                category = EXCLUDED.category,
                current_price = EXCLUDED.current_price,
                original_price = EXCLUDED.original_price,
                discount_percentage = EXCLUDED.discount_percentage,
                scraped_at = NOW();
        """, (title, category, store, current_price, original_price, discount_pct, img, url, volume, discount_pct > 0))
        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ DB Saved: [{store}] [{category}] {title} - €{current_price} (-{discount_pct}%)")
    except Exception as e:
        print(f"❌ DB Error saving '{title}': {e}")