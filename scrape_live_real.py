import os
import re
import json
import ssl
import time
import urllib.request
import urllib.parse
import psycopg2
from psycopg2.extras import execute_values

DB_URL = os.getenv("DATABASE_URL")

if not DB_URL:
    raise ValueError("DATABASE_URL environment variable is missing!")

SSL_CONTEXT = ssl._create_unverified_context()
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def save_to_db(items, store_name):
    if not items:
        print(f"❌ No items retrieved for {store_name}.")
        return

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    cur.execute("""
        ALTER TABLE grocery_products ADD COLUMN IF NOT EXISTS image_url TEXT;
        ALTER TABLE grocery_products ADD COLUMN IF NOT EXISTS product_url TEXT;
    """)

    unique_items = list({item[0]: item for item in items}.values())

    query = """
        INSERT INTO grocery_products (product_name, category, store_name, price)
        VALUES %s
        ON CONFLICT DO NOTHING;
    """

    try:
        execute_values(cur, query, unique_items)
        conn.commit()
        print(f"✅ Successfully inserted {len(unique_items)} live items for {store_name} into PostgreSQL!")
    except Exception as e:
        conn.rollback()
        print(f"❌ DB save error for {store_name}: {e}")
    finally:
        cur.close()
        conn.close()

# --- 1. LIVE BARBORA (MAXIMA) CATALOG SCRAPER ---
def scrape_barbora():
    print("\n🚀 Scraping live catalog from Barbora (Maxima)...")
    # Corrected Barbora Estonia Category Slugs
    categories = [
        "piimatooted-munad-ja-voi",
        "puuviljad-ja-koogiviljad",
        "leivad-saiad-ja-kondiitritooted",
        "liha-ja-kalatooted",
        "joogid",
        "purgitoidud-ja-konservid"
    ]
    items = []

    for cat in categories:
        time.sleep(2)
        try:
            url = f"https://www.barbora.ee/{cat}"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "et-EE,et;q=0.9,en-US;q=0.8",
                    "Cookie": "region=barbora.ee; language=et"
                }
            )
            with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=12) as response:
                html = response.read().decode("utf-8")

                matches = re.findall(r'data-b-product="([^"]+)"', html)
                for raw_json in matches:
                    try:
                        clean_json = raw_json.replace("&quot;", '"')
                        prod = json.loads(clean_json)
                        title = prod.get("title") or prod.get("name")
                        price = float(prod.get("price", 0.0))
                        if title and price > 0:
                            items.append((title, "Groceries", "Maxima EE", price))
                    except Exception:
                        continue
        except Exception as e:
            print(f"  ⚠️ Error scraping Barbora category '{cat}': {e}")

    save_to_db(items, "Maxima EE")

# --- 2. LIVE SELVER CATALOG SCRAPER (API ROUTE WITH DELAYS) ---
def scrape_selver():
    print("\n🚀 Scraping live catalog from Selver...")
    terms = ["piim", "leib", "juust", "või", "õun", "kana"]
    items = []

    for term in terms:
        time.sleep(4) # 4 second delay to clear 429 rate-limiting
        try:
            url = f"https://www.selver.ee/catalogsearch/result/?q={urllib.parse.quote(term)}"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "et-EE,et;q=0.9,en-US;q=0.8"
                }
            )
            with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=15) as response:
                html = response.read().decode("utf-8")
                
                matches = re.findall(r'"name":"([^"]+)".*?"price":([\d\.]+)', html)
                for name, price_str in matches:
                    try:
                        price = float(price_str)
                        if name and price > 0 and len(name) > 2:
                            items.append((name, "Groceries", "Selver", price))
                    except ValueError:
                        continue
        except Exception as e:
            print(f"  ⚠️ Error scraping Selver term '{term}': {e}")

    save_to_db(items, "Selver")

if __name__ == "__main__":
    scrape_barbora()
    scrape_selver()
