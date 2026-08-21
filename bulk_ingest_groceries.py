import os
import re
import httpx
import psycopg2
from psycopg2.extras import execute_values

DB_URL = os.getenv("DATABASE_URL")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "et-EE,et;q=0.9,en-US;q=0.8,en;q=0.7"
}

def get_db_connection():
    if not DB_URL:
        raise ValueError("DATABASE_URL environment variable missing!")
    return psycopg2.connect(DB_URL)

# --- 1. BARBORA DIRECT API INGESTION ---
def ingest_barbora():
    print("\n🚀 Ingesting Barbora (Maxima) via API...")
    search_terms = ["piim", "leib", "juust", "või", "õun", "kana", "muna", "vesi", "kohv", "tee", "kera", "liha", "kala", "jogurt"]
    items_to_insert = []

    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        for q in search_terms:
            url = f"https://www.barbora.ee/api/eshop/v1/subcategories/goods?q={q}"
            try:
                res = client.get(url, headers=HEADERS)
                if res.status_code == 200:
                    data = res.json()
                    products = data.get("products", [])
                    for p in products:
                        title = p.get("title", "")
                        price = float(p.get("price", 0.0))
                        image = p.get("image", "")
                        url_path = p.get("url", "")
                        full_url = f"https://www.barbora.ee{url_path}" if url_path else "https://www.barbora.ee"

                        if title and price > 0:
                            items_to_insert.append((
                                title, "Groceries", "Maxima EE", price, image, full_url
                            ))
            except Exception as e:
                print(f"⚠️ Error on Barbora term '{q}': {e}")

    save_grocery_items(items_to_insert, "Maxima EE")

# --- 2. SELVER DIRECT GRAPHQL INGESTION ---
def ingest_selver():
    print("\n🚀 Ingesting Selver via GraphQL API...")
    gql_url = "https://www.selver.ee/api/graphql"
    search_terms = ["piim", "leib", "juust", "või", "õun", "kana", "muna", "vesi", "kohv", "tee", "kera", "liha", "kala", "jogurt"]
    items_to_insert = []

    query = """
    query SearchProducts($search: String!) {
      products(search: $search, pageSize: 20) {
        items {
          name
          sku
          url_key
          small_image {
            url
          }
          price_range {
            minimum_price {
              final_price {
                value
              }
            }
          }
        }
      }
    }
    """

    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        for q in search_terms:
            payload = {"query": query, "variables": {"search": q}}
            try:
                res = client.post(gql_url, json=payload, headers=HEADERS)
                if res.status_code == 200:
                    data = res.json()
                    products = data.get("data", {}).get("products", {}).get("items", [])
                    for p in products:
                        title = p.get("name", "")
                        price_obj = p.get("price_range", {}).get("minimum_price", {}).get("final_price", {})
                        price = float(price_obj.get("value", 0.0))
                        image = p.get("small_image", {}).get("url", "")
                        url_key = p.get("url_key", "")
                        full_url = f"https://www.selver.ee/{url_key}.html" if url_key else "https://www.selver.ee"

                        if title and price > 0:
                            items_to_insert.append((
                                title, "Groceries", "Selver", price, image, full_url
                            ))
            except Exception as e:
                print(f"⚠️ Error on Selver term '{q}': {e}")

    save_grocery_items(items_to_insert, "Selver")

# --- SAVE TO POSTGRES DB ---
def save_grocery_items(items, store_name):
    if not items:
        print(f"❌ No items returned for {store_name}.")
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
        print(f"✅ Successfully ingested {len(unique_items)} items for {store_name} into PostgreSQL!")
    except Exception as e:
        conn.rollback()
        print(f"❌ DB error saving {store_name}: {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    ingest_barbora()
    ingest_selver()
