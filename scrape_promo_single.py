import asyncio
import json
import os
import re
import psycopg2
from psycopg2 import pool
from playwright.async_api import async_playwright

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres.ocxnykaqirzvwimyvdtt:Rosamund6498%21%40%23@aws-0-eu-central-1.pooler.supabase.com:6543/postgres",
)

# KEYWORD SEARCH ENGINE FOR PROMO CATALOG
SEARCH_KEYWORDS = [
    ("Grocery", "oil"),
    ("Grocery", "vinegar"),
    ("Grocery", "pasta"),
    ("Grocery", "rice"),
    ("Grocery", "flour"),
    ("Grocery", "sugar"),
    ("Grocery", "spice"),
    ("Dairy", "milk"),
    ("Dairy", "cheese"),
    ("Dairy", "butter"),
    ("Meat & Fish", "chicken"),
    ("Meat & Fish", "pork"),
    ("Meat & Fish", "fish"),
    ("Drinks", "juice"),
    ("Drinks", "water"),
    ("Drinks", "coffee"),
]

PAGES_PER_KEYWORD = 3
db_pool = psycopg2.pool.SimpleConnectionPool(1, 10, DB_URL)


def clean_ean(raw_code):
    if not raw_code:
        return None
    cleaned = re.sub(r"\D", "", str(raw_code)).strip()
    return cleaned if len(cleaned) in [8, 12, 13, 14] else None


def save_product(title: str, category: str, price: float, raw_code: str = None) -> bool:
    if not title:
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
            VALUES (%s, %s, 'PROMO EE', %s, %s)
            ON CONFLICT (product_name, store_name) 
            DO UPDATE SET 
                price = CASE WHEN EXCLUDED.price > 0 THEN EXCLUDED.price ELSE grocery_products.price END, 
                category = EXCLUDED.category, 
                ean = COALESCE(EXCLUDED.ean, grocery_products.ean),
                updated_at = CURRENT_TIMESTAMP;
            """,
            (clean_t, category, price, ean),
        )
        conn.commit()
        cursor.close()

        price_str = f"€{price:.2f}" if price > 0 else "PRICE LOCKED"
        ean_str = f" [REAL EAN: {ean}]" if ean else " [NO EAN]"
        print(f"  ✅ Saved: {clean_t}{ean_str} - {price_str}")
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"  ❌ DB Error: {e}")
        return False
    finally:
        if conn:
            db_pool.putconn(conn)


async def scrape_promo():
    print("============================================================")
    print("🚀 PROMO CASH & CARRY - GRAPHQL & SEARCH INTERCEPTOR ENGINE")
    print("============================================================")

    total_items = 0
    total_eans = 0
    processed_global = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )

        page = await context.new_page()

        for category, keyword in SEARCH_KEYWORDS:
            print(f"\n🔍 Searching Query: '{keyword}' ({category})")
            cat_saved = 0
            cat_eans = 0
            intercepted_products = []

            # Intercept live background GraphQL/REST JSON responses
            async def handle_response(response):
                try:
                    if response.status == 200 and "application/json" in response.headers.get("content-type", ""):
                        data = await response.json()
                        if isinstance(data, dict):
                            def extract_items(obj):
                                if isinstance(obj, dict):
                                    for k, v in obj.items():
                                        if k in ["products", "items", "results", "hits"] and isinstance(v, list) and len(v) > 0:
                                            intercepted_products.extend(v)
                                        else:
                                            extract_items(v)
                                elif isinstance(obj, list):
                                    for el in obj:
                                        extract_items(el)

                            extract_items(data)
                except Exception:
                    pass

            page.on("response", handle_response)

            for page_num in range(1, PAGES_PER_KEYWORD + 1):
                url = f"https://epromo.ee/en/ee/search?q={keyword}&page={page_num}"

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(1500)

                    for _ in range(6):
                        await page.evaluate("window.scrollBy(0, 1000)")
                        await page.wait_for_timeout(250)

                    if intercepted_products:
                        for item in intercepted_products:
                            if not isinstance(item, dict):
                                continue

                            title = item.get("name") or item.get("title") or item.get("pTitle")
                            raw_price = (
                                item.get("price")
                                or item.get("priceWithVat")
                                or item.get("finalPrice")
                                or 0.0
                            )
                            real_ean = item.get("barcode") or item.get("gtin") or item.get("code") or item.get("sku")

                            if title:
                                try:
                                    price_val = float(str(raw_price).replace(",", ".")) if raw_price else 0.0
                                    dedup_key = f"{title}_{real_ean}"

                                    if dedup_key not in processed_global:
                                        processed_global.add(dedup_key)
                                        if save_product(title, category, price_val, str(real_ean) if real_ean else None):
                                            cat_saved += 1
                                            total_items += 1
                                            if clean_ean(real_ean):
                                                cat_eans += 1
                                                total_eans += 1
                                except Exception:
                                    pass

                except Exception as e:
                    print(f"   ❌ Error on query '{keyword}' page {page_num}: {e}")
                    break

            print(f"   ✅ Query '{keyword}' Summary: {cat_saved} items saved ({cat_eans} with REAL GTIN/EAN)")

        await browser.close()

    db_pool.closeall()

    print("\n" + "=" * 60)
    print("📊 PROMO INGESTION FINAL REPORT")
    print("=" * 60)
    print(f"Total Unique Products Saved/Updated: {total_items}")
    print(f"Products with Valid GTIN Barcode:    {total_eans}")
    print("============================================================\n")


if __name__ == "__main__":
    asyncio.run(scrape_promo())
