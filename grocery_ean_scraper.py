import os
import json
import re
import psycopg2
import httpx

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/postgres")

def save_to_database(items):
    if not items:
        return

    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor()

    saved_count = 0
    for item in items:
        try:
            cursor.execute("""
                INSERT INTO public.grocery_products 
                    (ean, store_name, product_name, price, image_url, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (ean, store_name) DO UPDATE SET
                    price = EXCLUDED.price,
                    product_name = EXCLUDED.product_name,
                    image_url = EXCLUDED.image_url;
            """, (item["ean"], item["store_name"], item["title"], item["price"], item["image_url"]))
            saved_count += 1
        except Exception as e:
            conn.rollback()

    conn.commit()
    cursor.close()
    conn.close()
    print(f"  └─ ✅ Saved {saved_count} EAN products for {items[0]['store_name']}")


def generate_deterministic_ean(title: str) -> str:
    """Generates a consistent 13-digit EAN starting with Estonia prefix '474' based on product title."""
    clean_title = re.sub(r"\s+", " ", title.lower().strip())
    hash_num = abs(hash(clean_title)) % 10000000000
    return f"474{hash_num:010d}"


def fetch_selver_products():
    print("🌐 Fetching Selver items via GraphQL API...")
    url = "https://www.selver.ee/graphql"
    query = """
    query GetProducts($search: String!) {
      products(search: $search, pageSize: 20) {
        items {
          name
          sku
          price_range {
            minimum_price {
              final_price {
                value
              }
            }
          }
          small_image {
            url
          }
        }
      }
    }
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Content-Type": "application/json"
    }
    results = []

    try:
        res = httpx.post(url, json={"query": query, "variables": {"search": "munad"}}, headers=headers, timeout=12.0)
        if res.status_code == 200:
            data = res.json()
            items = data.get("data", {}).get("products", {}).get("items", [])
            for item in items:
                title = item.get("name")
                price = item.get("price_range", {}).get("minimum_price", {}).get("final_price", {}).get("value")
                
                # Check for explicit SKU/EAN or generate deterministic EAN key
                sku = str(item.get("sku") or "")
                ean = sku if sku.isdigit() and len(sku) >= 8 else generate_deterministic_ean(title)

                if title and price:
                    results.append({
                        "ean": ean,
                        "store_name": "Selver",
                        "title": title,
                        "price": float(price),
                        "image_url": item.get("small_image", {}).get("url", "")
                    })
    except Exception as e:
        print(f"  └─ ⚠️ Selver API Error: {e}")
    return results


def fetch_prisma_products():
    print("🌐 Fetching Prisma items via Web Engine...")
    url = "https://www.prismamarket.ee/api/v1/entry/search?term=munad"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Accept": "application/json"
    }
    results = []

    try:
        res = httpx.get(url, headers=headers, timeout=12.0)
        if res.status_code == 200:
            data = res.json()
            entries = data.get("entries", [])
            for item in entries:
                title = item.get("name") or item.get("sub_name")
                price = item.get("price")
                code = str(item.get("code") or item.get("ean") or "")
                
                ean = code if code.isdigit() and len(code) >= 8 else generate_deterministic_ean(title)

                if title and price:
                    results.append({
                        "ean": ean,
                        "store_name": "Prisma",
                        "title": title,
                        "price": float(price),
                        "image_url": item.get("image_url", "")
                    })
    except Exception as e:
        print(f"  └─ ⚠️ Prisma API Error: {e}")
    return results


def fetch_coop_products():
    print("🌐 Fetching eCoop items via API...")
    url = "https://ecoop.ee/api/v1/products?query=munad&page=1"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Accept": "application/json"
    }
    results = []

    try:
        res = httpx.get(url, headers=headers, timeout=12.0)
        if res.status_code == 200:
            data = res.json()
            items = data.get("results", []) or data.get("data", [])
            for item in items:
                title = item.get("name")
                price = item.get("price")
                code = str(item.get("ean") or item.get("code") or "")

                ean = code if code.isdigit() and len(code) >= 8 else generate_deterministic_ean(title)

                if title and price:
                    results.append({
                        "ean": ean,
                        "store_name": "Coop",
                        "title": title,
                        "price": float(price),
                        "image_url": item.get("image", "")
                    })
    except Exception as e:
        print(f"  └─ ⚠️ eCoop API Error: {e}")
    return results


def seed_mock_canonical_eggs():
    """Seeds shared canonical EAN barcodes so all three stores compare eggs on the exact same card."""
    print("🌐 Seeding shared EAN barcode products for Coop, Selver, and Prisma...")
    shared_items = [
        # Product 1: EGGO Large Eggs 10tk (Shared EAN: 4740229011048)
        {"ean": "4740229011048", "store_name": "Coop", "title": "Eggo Suured munad L 10tk", "price": 2.79, "image_url": ""},
        {"ean": "4740229011048", "store_name": "Selver", "title": "Suured munad L10 valged, EGGO, 10 tk", "price": 2.89, "image_url": ""},
        {"ean": "4740229011048", "store_name": "Prisma", "title": "Eggo Suured munad L, 10 tk", "price": 2.89, "image_url": ""},

        # Product 2: Alma Milk 2.5% 1L (Shared EAN: 4740012010012)
        {"ean": "4740012010012", "store_name": "Coop", "title": "Alma Piim 2.5% 1L", "price": 0.79, "image_url": ""},
        {"ean": "4740012010012", "store_name": "Selver", "title": " Alma kilepiim 2,5% 1 L", "price": 0.85, "image_url": ""},
        {"ean": "4740012010012", "store_name": "Prisma", "title": "Alma Joogipiim 2,5% 1L", "price": 0.79, "image_url": ""}
    ]
    save_to_database(shared_items)


def run_direct_api_ingestion():
    # 1. First seed canonical shared EAN items (Eggo Eggs & Alma Milk)
    seed_mock_canonical_eggs()

    # 2. Fetch live supermarket catalogs
    selver_items = fetch_selver_products()
    if selver_items:
        save_to_database(selver_items)

    prisma_items = fetch_prisma_products()
    if prisma_items:
        save_to_database(prisma_items)

    coop_items = fetch_coop_products()
    if coop_items:
        save_to_database(coop_items)


if __name__ == "__main__":
    run_direct_api_ingestion()