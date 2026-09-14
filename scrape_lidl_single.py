import asyncio
import os
import re
import psycopg2
from psycopg2 import pool
from playwright.async_api import async_playwright

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres.ocxnykaqirzvwimyvdtt:Rosamund6498%21%40%23@aws-0-eu-central-1.pooler.supabase.com:6543/postgres",
)

# LIDL ESTONIA INTERNAL CATEGORY GRID SLUGS
LIDL_GRID_SLUGS = [
    ("Nädala Pakkumised", "s10023886"),
    ("Head Pakkumised", "s10023888"),
]

db_pool = psycopg2.pool.SimpleConnectionPool(1, 10, DB_URL)


def clean_ean(raw_code):
    if not raw_code:
        return None
    cleaned = re.sub(r"\D", "", str(raw_code)).strip()
    return cleaned if len(cleaned) >= 5 else None


def save_product(title: str, category: str, price: float, raw_code: str = None) -> bool:
    if not title or price <= 0:
        return False

    clean_t = title.strip().replace("\n", " ")
    ean = clean_ean(raw_code)
    conn = None

    try:
        conn = db_pool.getconn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO grocery_products (product_name, category, store_name, price, ean)
            VALUES (%s, %s, 'Lidl EE', %s, %s)
            ON CONFLICT (product_name, store_name) 
            DO UPDATE SET 
                price = EXCLUDED.price, 
                category = EXCLUDED.category, 
                ean = COALESCE(EXCLUDED.ean, grocery_products.ean),
                updated_at = CURRENT_TIMESTAMP;
            """,
            (clean_t, category, price, ean),
        )
        conn.commit()
        cursor.close()

        ean_str = f" [SKU/ID: {ean}]" if ean else " [NO EAN]"
        print(f"  ✅ Saved: {clean_t}{ean_str} - €{price:.2f}")
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"  ❌ DB Write Error: {e}")
        return False
    finally:
        if conn:
            db_pool.putconn(conn)


async def scrape_lidl():
    print("============================================================")
    print("🛒 LIDL ESTONIA - INTERNAL API HARVESTER ENGINE")
    print("============================================================")

    total_items = 0
    total_eans = 0

    async with async_playwright() as p:
        request_context = await p.request.new_context(
            extra_http_headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.lidl.ee/",
                "Accept-Language": "et-EE,et;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )

        for cat_name, slug in LIDL_GRID_SLUGS:
            print(f"\n📂 Processing Lidl Section: '{cat_name}' (Slug: {slug})")
            cat_saved = 0
            cat_eans = 0

            # Direct Lidl EE internal JSON endpoint
            api_url = f"https://www.lidl.ee/p/api/gridboxes/EE/et/campaign/{slug}"

            try:
                response = await request_context.get(api_url, timeout=15000)
                
                if response.status == 200:
                    data = await response.json()
                    
                    # Extract list of products from returned JSON
                    grid_boxes = []
                    if isinstance(data, list):
                        grid_boxes = data
                    elif isinstance(data, dict):
                        grid_boxes = data.get("gridboxes") or data.get("items") or []

                    for item in grid_boxes:
                        if not isinstance(item, dict):
                            continue

                        title = item.get("title") or item.get("fullTitle")
                        price_obj = item.get("price", {})
                        
                        raw_price = None
                        if isinstance(price_obj, dict):
                            raw_price = price_obj.get("price")
                        elif isinstance(price_obj, (int, float)):
                            raw_price = price_obj

                        raw_code = item.get("productId") or item.get("code") or item.get("id")

                        if title and raw_price:
                            try:
                                p_val = float(raw_price)
                                if save_product(title, cat_name, p_val, str(raw_code) if raw_code else None):
                                    cat_saved += 1
                                    total_items += 1
                                    if clean_ean(raw_code):
                                        cat_eans += 1
                                        total_eans += 1
                            except Exception:
                                pass
                else:
                    print(f"  ⚠️ HTTP {response.status} returned for section {cat_name}")

            except Exception as e:
                print(f"  ❌ Section crawl failed: {e}")

            print(f"   ✅ '{cat_name}' Summary: {cat_saved} items saved ({cat_eans} with SKU/ID)")

        await request_context.dispose()

    db_pool.closeall()

    print("\n" + "=" * 60)
    print("📊 LIDL INGESTION REPORT")
    print("=" * 60)
    print(f"Total Unique Products Saved/Updated: {total_items}")
    print(f"Products with Valid SKU/ID:          {total_eans}")
    print("============================================================\n")


if __name__ == "__main__":
    asyncio.run(scrape_lidl())