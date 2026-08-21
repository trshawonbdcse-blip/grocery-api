import os
import re
import httpx
import psycopg2
from psycopg2.extras import execute_values

DB_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if not DB_URL:
        raise ValueError("DATABASE_URL environment variable is missing!")
    return psycopg2.connect(DB_URL)

def save_items(items, store_name):
    if not items:
        print(f"❌ No items captured for {store_name}.")
        return

    conn = get_db_connection()
    cur = conn.cursor()

    # Deduplicate items by title
    unique_items = list({item[0]: item for item in items}.values())

    query = """
        INSERT INTO grocery_products (product_name, category, store_name, price, image_url, product_url)
        VALUES %s
        ON CONFLICT DO NOTHING;
    """

    try:
        execute_values(cur, query, unique_items)
        conn.commit()
        print(f"✅ Successfully inserted/updated {len(unique_items)} items for {store_name} in PostgreSQL!")
    except Exception as e:
        conn.rollback()
        print(f"❌ DB save error for {store_name}: {e}")
    finally:
        cur.close()
        conn.close()

# --- 1. BARBORA (MAXIMA) BULK INGESTION ---
def ingest_barbora():
    print("\n🚀 Ingesting Barbora (Maxima)...")
    items = []
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "et-EE,et;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cookie": "region=barbora.ee; language=et"
    }

    terms = ["piim", "leib", "juust", "või", "õun", "kana", "muna", "vesi", "kohv", "tee", "liha", "kala", "jogurt"]

    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        for q in terms:
            url = f"https://www.barbora.ee/otsing?q={q}"
            try:
                res = client.get(url, headers=headers)
                if res.status_code == 200:
                    # Parse embedded product objects in html
                    matches = re.findall(r'data-b-product="([^"]+)"', res.text)
                    for m in matches:
                        # Unescape html quotes
                        clean_json = m.replace("&quot;", '"')
                        try:
                            import json
                            p = json.loads(clean_json)
                            title = p.get("title") or p.get("name")
                            price = float(p.get("price", 0.0))
                            img = p.get("image", "")
                            url_path = p.get("url", "")
                            full_url = f"https://www.barbora.ee{url_path}" if url_path else "https://www.barbora.ee"

                            if title and price > 0:
                                items.append((title, "Groceries", "Maxima EE", price, img, full_url))
                        except Exception:
                            continue
            except Exception as e:
                print(f"  ⚠️ Error on Barbora query '{q}': {e}")

    save_items(items, "Maxima EE")

# --- 2. SELVER BULK INGESTION ---
def ingest_selver():
    print("\n🚀 Ingesting Selver...")
    items = []
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "et-EE,et;q=0.9,en-US;q=0.8,en;q=0.7"
    }

    terms = ["piim", "leib", "juust", "või", "õun", "kana", "muna", "vesi", "kohv", "tee", "liha", "kala", "jogurt"]

    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        for q in terms:
            url = f"https://www.selver.ee/catalogsearch/result/?q={q}"
            try:
                res = client.get(url, headers=headers)
                if res.status_code == 200:
                    # Match Magento JSON product payload embedded in page state
                    matches = re.findall(r'"name":"([^"]+)","id":"[^"]+","price":([\d\.]+)', res.text)
                    for name, price_str in matches:
                        try:
                            price = float(price_str)
                            if name and price > 0:
                                items.append((name, "Groceries", "Selver", price, "", f"https://www.selver.ee/catalogsearch/result/?q={q}"))
                        except Exception:
                            continue
            except Exception as e:
                print(f"  ⚠️ Error on Selver query '{q}': {e}")

    save_items(items, "Selver")

if __name__ == "__main__":
    ingest_barbora()
    ingest_selver()
