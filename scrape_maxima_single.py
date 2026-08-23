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

MAXIMA_CATEGORIES = [
    ("Köögiviljad, puuviljad", "https://barbora.ee/koogiviljad-puuviljad"),
    ("Piimatooted ja munad", "https://barbora.ee/piimatooted-ja-munad"),
    ("Leivad, saiad, kondiitritooted", "https://barbora.ee/leiva-ja-kondiitritooted"),
    ("Liha, kala, valmistoit", "https://barbora.ee/liha-kala-ja-valmistoit"),
    ("Kauasäilivad toidukaubad", "https://barbora.ee/kauasailivad-toidukaubad"),
    ("Külmutatud tooted", "https://barbora.ee/kulmutatud-tooted"),
    ("Joogid", "https://barbora.ee/joogid"),
    ("Enesehooldustooted", "https://barbora.ee/enesehooldustooted"),
    ("Puhastustarbed ja lemmikloomatooted", "https://barbora.ee/puhastustarbed-ja-lemmikloomatooted"),
    ("Lastekaubad", "https://barbora.ee/lastekaubad"),
    ("Kodukaubad ja vaba aeg", "https://barbora.ee/kodukaubad-ja-vaba-aeg"),
]

PAGES_PER_CATEGORY = 5
SCROLL_DEPTH = 8

db_pool = psycopg2.pool.SimpleConnectionPool(1, 10, DB_URL)


def save_product(title: str, category: str, price: float) -> bool:
    if not title or price <= 0:
        return False

    clean_t = title.strip().replace("\n", " ")
    conn = None

    try:
        conn = db_pool.getconn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO grocery_products (product_name, category, store_name, price)
            VALUES (%s, %s, 'Maxima EE', %s)
            ON CONFLICT (product_name, store_name) 
            DO UPDATE SET 
                price = EXCLUDED.price, 
                category = EXCLUDED.category, 
                updated_at = CURRENT_TIMESTAMP;
            """,
            (clean_t, category, price),
        )
        conn.commit()
        cursor.close()

        print(f"  ✅ Saved: {clean_t} - €{price:.2f}")
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"  ❌ DB Write Error: {e}")
        return False
    finally:
        if conn:
            db_pool.putconn(conn)


async def scrape_maxima():
    print("============================================================")
    print("🚀 MAXIMA (BARBORA) - RELIABLE DUAL HARVESTER ENGINE")
    print("============================================================")

    total_items = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="et-EE",
            timezone_id="Europe/Tallinn",
        )

        page = await context.new_page()

        print("🌐 Session setup...")
        try:
            await page.goto("https://barbora.ee", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1000)
            try:
                cookie_btn = await page.wait_for_selector("#onetrust-accept-btn-handler", timeout=2500)
                if cookie_btn:
                    await cookie_btn.click()
            except Exception:
                pass
        except Exception:
            pass

        for cat_name, base_url in MAXIMA_CATEGORIES:
            print(f"\n📂 Ingesting Category: '{cat_name}'")
            cat_saved = 0
            processed_in_cat = set()
            api_captured_products = []

            # Background JSON response listener
            async def intercept_response(response):
                try:
                    if response.status == 200 and "application/json" in response.headers.get("content-type", ""):
                        json_body = await response.json()
                        if isinstance(json_body, dict):
                            prods = (
                                json_body.get("products")
                                or json_body.get("items")
                                or (json_body.get("category") and json_body["category"].get("products"))
                                or []
                            )
                            if prods:
                                api_captured_products.extend(prods)
                except Exception:
                    pass

            page.on("response", intercept_response)

            for page_num in range(1, PAGES_PER_CATEGORY + 1):
                url = f"{base_url}?page={page_num}" if page_num > 1 else base_url

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=35000)
                    await page.wait_for_timeout(1000)

                    for _ in range(SCROLL_DEPTH):
                        await page.evaluate("window.scrollBy(0, 1000)")
                        await page.wait_for_timeout(250)

                    # 1. API extraction
                    if api_captured_products:
                        for item in api_captured_products:
                            title = item.get("title") or item.get("name")
                            price = item.get("price") or item.get("final_price")

                            if title and price:
                                try:
                                    p_val = float(price)
                                    dedup_key = f"{title}_{p_val}"
                                    if p_val > 0 and dedup_key not in processed_in_cat:
                                        processed_in_cat.add(dedup_key)
                                        if save_product(title, cat_name, p_val):
                                            cat_saved += 1
                                            total_items += 1
                                except Exception:
                                    pass

                    # 2. DOM fallback
                    items = await page.evaluate("""() => {
                        const results = [];
                        const cards = Array.from(document.querySelectorAll('div.b-product-card, div[data-product-id], li[class*="product"]'));
                        
                        cards.forEach(card => {
                            const titleEl = card.querySelector('span[itemprop="name"], a.b-product-card--title, h3, a[title], div[class*="title"]');
                            const priceEl = card.querySelector('[itemprop="price"], .b-product-card--price, [class*="price"]');

                            if (titleEl && priceEl) {
                                results.push({
                                    title: titleEl.innerText ? titleEl.innerText.trim() : '',
                                    price: priceEl.innerText ? priceEl.innerText.trim() : ''
                                });
                            }
                        });
                        return results;
                    }""")

                    for item in items:
                        title_raw = item.get("title", "").split("\n")[0].strip()
                        price_raw = item.get("price", "").replace(" ", "").replace("\n", "").split("€/")[0]

                        match = re.search(r"(\d+[\.,]\d{2})", price_raw)
                        if title_raw and match:
                            price_val = float(match.group(1).replace(",", "."))
                            dedup_key = f"{title_raw}_{price_val}"

                            if dedup_key not in processed_in_cat:
                                processed_in_cat.add(dedup_key)
                                if save_product(title_raw, cat_name, price_val):
                                    cat_saved += 1
                                    total_items += 1

                except Exception as e:
                    print(f"   ❌ Error on page {page_num}: {e}")
                    break

            print(f"   ✅ '{cat_name}' Summary: {cat_saved} unique items saved")

        await browser.close()

    db_pool.closeall()

    print("\n" + "=" * 60)
    print("📊 MAXIMA INGESTION REPORT")
    print("=" * 60)
    print(f"Total Unique Products Saved/Updated: {total_items}")
    print("============================================================\n")


if __name__ == "__main__":
    asyncio.run(scrape_maxima())