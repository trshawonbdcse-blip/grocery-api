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

# --- 1. SELVER REST API INGESTION ---
def ingest_selver():
    print("\n🚀 Ingesting Selver via Magento REST API...")
    items = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    terms = ["piim", "leib", "juust", "või", "õun", "kana", "muna", "vesi", "kohv", "tee", "liha", "kala", "jogurt", "pork"]

    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        for q in terms:
            url = f"https://www.selver.ee/rest/V1/products?searchCriteria[filter_groups][0][filters][0][field]=name&searchCriteria[filter_groups][0][filters][0][value]=%{q}%&searchCriteria[filter_groups][0][filters][0][condition_type]=like&searchCriteria[pageSize]=30"
            try:
                res = client.get(url, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    prods = data.get("items", [])
                    for p in prods:
                        name = p.get("name")
                        price = float(p.get("price", 0.0))
                        sku = p.get("sku", "")
                        
                        # Find product URL or image from custom attributes
                        img_path = ""
                        url_key = ""
                        for attr in p.get("custom_attributes", []):
                            if attr.get("attribute_code") == "small_image":
                                img_path = attr.get("value")
                            elif attr.get("attribute_code") == "url_key":
                                url_key = attr.get("value")

                        img_url = f"https://www.selver.ee/media/catalog/product{img_path}" if img_path else ""
                        full_url = f"https://www.selver.ee/{url_key}.html" if url_key else f"https://www.selver.ee"

                        if name and price > 0:
                            items.append((name, "Groceries", "Selver", price, img_url, full_url))
            except Exception as e:
                print(f"  ⚠️ Error on Selver query '{q}': {e}")

    save_items(items, "Selver")

# --- 2. BARBORA SEARCH API INGESTION ---
def ingest_barbora():
    print("\n🚀 Ingesting Barbora (Maxima) via Regional API...")
    items = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.barbora.ee/"
    }

    terms = ["piim", "leib", "juust", "või", "õun", "kana", "muna", "vesi", "kohv", "tee", "liha", "kala", "jogurt", "pork"]

    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        for q in terms:
            url = f"https://barbora.ee/api/eshop/v1/subcategories/goods?q={q}&page=1"
            try:
                res = client.get(url, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    products = data.get("products", []) or data.get("items", [])
                    for prod in products:
                        title = prod.get("title") or prod.get("name")
                        price = float(prod.get("price", 0.0))
                        img = prod.get("image", "")
                        url_path = prod.get("url", "")
                        full_url = f"https://www.barbora.ee{url_path}" if url_path else "https://www.barbora.ee"

                        if title and price > 0:
                            items.append((title, "Groceries", "Maxima EE", price, img, full_url))
            except Exception as e:
                print(f"  ⚠️ Error on Barbora query '{q}': {e}")

    save_items(items, "Maxima EE")

if __name__ == "__main__":
    ingest_selver()
    ingest_barbora()
