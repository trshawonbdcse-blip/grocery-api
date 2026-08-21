import os
import re
import httpx
import psycopg2
from psycopg2.extras import execute_values

DB_URL = os.getenv("DATABASE_URL")

if not DB_URL:
    raise ValueError("DATABASE_URL environment variable is missing!")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "et-EE,et;q=0.9,en-US;q=0.8,en;q=0.7"
}

def save_items(items, store_name):
    if not items:
        print(f"❌ No live items retrieved for {store_name}.")
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
        print(f"✅ Successfully ingested {len(unique_items)} live items for {store_name} into PostgreSQL!")
    except Exception as e:
        conn.rollback()
        print(f"❌ DB save error for {store_name}: {e}")
    finally:
        cur.close()
        conn.close()

# --- 1. LIVE SELVER GRAPHQL SCRAPER ---
def scrape_selver():
    print("\n🚀 Scraping live catalog from Selver GraphQL API...")
    gql_url = "https://www.selver.ee/api/graphql"
    
    search_queries = [
        "piim", "leib", "juust", "või", "õun", "kana", "muna", "vesi", 
        "kohv", "tee", "liha", "kala", "jogurt", "pork", "sai", "kurk"
    ]
    
    items = []
    query_body = """
    query SearchProducts($search: String!) {
      products(search: $search, pageSize: 40) {
        items {
          name
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

    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        for term in search_queries:
            payload = {"query": query_body, "variables": {"search": term}}
            try:
                res = client.post(gql_url, json=payload, headers=HEADERS)
                if res.status_code == 200:
                    data = res.json()
                    products = data.get("data", {}).get("products", {}).get("items", [])
                    for p in products:
                        name = p.get("name")
                        price_val = p.get("price_range", {}).get("minimum_price", {}).get("final_price", {}).get("value")
                        if name and price_val:
                            items.append((name, "Groceries", "Selver", float(price_val)))
            except Exception as e:
                print(f"  ⚠️ Error fetching Selver term '{term}': {e}")

    save_items(items, "Selver")

# --- 2. LIVE BARBORA / MAXIMA SEARCH SCRAPER ---
def scrape_barbora():
    print("\n🚀 Scraping live catalog from Barbora (Maxima)...")
    search_queries = [
        "piim", "leib", "juust", "või", "õun", "kana", "muna", "vesi", 
        "kohv", "tee", "liha", "kala", "jogurt", "pork", "sai", "kurk"
    ]
    
    items = []
    
    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        for term in search_queries:
            url = f"https://www.barbora.ee/api/eshop/v1/subcategories/goods?q={term}&page=1"
            try:
                res = client.get(url, headers=HEADERS)
                if res.status_code == 200:
                    data = res.json()
                    products = data.get("products", []) or data.get("items", [])
                    for prod in products:
                        title = prod.get("title") or prod.get("name")
                        price = prod.get("price")
                        if title and price:
                            items.append((title, "Groceries", "Maxima EE", float(price)))
            except Exception as e:
                print(f"  ⚠️ Error fetching Barbora term '{term}': {e}")

    save_items(items, "Maxima EE")

if __name__ == "__main__":
    scrape_selver()
    scrape_barbora()
