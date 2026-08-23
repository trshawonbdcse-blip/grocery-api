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

# UNCAPPED SELVER CATEGORY LIST
SELVER_CATEGORIES = [
    ("Puu- ja köögiviljad", "https://www.selver.ee/puu-ja-koogiviljad"),
    ("Liha- ja kalatooted", "https://www.selver.ee/liha-ja-kalatooted"),
    ("Piimatooted, munad, võid", "https://www.selver.ee/piimatooted-munad-void"),
    ("Juustud", "https://www.selver.ee/juustud"),
    ("Leivad, saiad, kondiitritooted", "https://www.selver.ee/leivad-saiad-kondiitritooted"),
    ("Kuivained, hommikusöögid, hoidised", "https://www.selver.ee/kuivained-hommikusoogid-hoidised"),
    ("Maailma köök, maitseained, puljongid", "https://www.selver.ee/maailma-kook-maitseained-puljongid"),
    ("Kastmed, õlid", "https://www.selver.ee/kastmed-olid"),
    ("Maiustused, küpsised, näksid", "https://www.selver.ee/maiustused-kupsised-naksid"),
    ("Joogid", "https://www.selver.ee/joogid"),
    ("Külmutatud toidukaubad", "https://www.selver.ee/kulmutatud-toidukaubad"),
    ("Valmistoidud", "https://www.selver.ee/valmistoidud"),
]

# Increase max pages to pull the full 800+ item categories
PAGES_PER_CATEGORY = 30
SCROLL_DEPTH = 6

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
            VALUES (%s, %s, 'Selver', %s, %s)
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

        ean_str = f" [SKU/EAN: {ean}]" if ean else " [NO EAN]"
        print(f"  ✅ Saved: {clean_t}{ean_str} - €{price:.2f}")
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"  ❌ DB Error: {e}")
        return False
    finally:
        if conn:
            db_pool.putconn(conn)


async def scrape_selver():
    print("============================================================")
    print("🚀 SELVER ESTONIA - DEEP UNCAPPED INGESTION ENGINE")
    print("============================================================")

    total_items = 0
    total_eans = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="et-EE",
        )

        page = await context.new_page()

        print("🌐 Initializing session context...")
        try:
            await page.goto("https://www.selver.ee", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1000)
            try:
                cookie_btn = await page.wait_for_selector("button:has-text('Nõustun'), #cookie-accept", timeout=3000)
                if cookie_btn:
                    await cookie_btn.click()
            except Exception:
                pass
        except Exception:
            pass

        for cat_name, base_url in SELVER_CATEGORIES:
            print(f"\n📂 Ingesting Deep Category: '{cat_name}'")
            cat_saved = 0
            cat_eans = 0
            processed_in_cat = set()

            for page_num in range(1, PAGES_PER_CATEGORY + 1):
                # Pass limit parameter if supported to fetch up to 96 items per page
                url = f"{base_url}?page={page_num}&limit=96" if page_num > 1 else f"{base_url}?limit=96"

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=35000)
                    await page.wait_for_timeout(1200)

                    for _ in range(SCROLL_DEPTH):
                        await page.evaluate("window.scrollBy(0, 1000)")
                        await page.wait_for_timeout(200)

                    # Extract products and embedded JSON attributes from DOM
                    dom_items = await page.evaluate("""() => {
                        const results = [];
                        const cards = Array.from(document.querySelectorAll('.product-item, [class*="ProductCard"], [class*="product-card"], li.item'));

                        cards.forEach(card => {
                            const titleEl = card.querySelector('.product-item-link, [class*="title"], [class*="Name"], h2, h3, a');
                            const priceEl = card.querySelector('.price, [data-price-amount], [class*="price"]');
                            const linkEl = card.querySelector('a[href*="/"]');
                            
                            // Check embedded data attributes for SKU/EAN
                            let sku = card.getAttribute('data-sku') || card.getAttribute('data-product-id') || '';
                            
                            if (!sku && linkEl && linkEl.href) {
                                const match = linkEl.href.match(/(\\d{5,14})/);
                                if (match) sku = match[1];
                            }

                            if (titleEl && priceEl) {
                                results.push({
                                    title: titleEl.innerText ? titleEl.innerText.trim() : '',
                                    price: priceEl.innerText ? priceEl.innerText.trim() : '',
                                    sku: sku
                                });
                            }
                        });
                        return results;
                    }""")

                    if not dom_items:
                        print(f"   ℹ️ Reached end of items at page {page_num - 1}.")
                        break

                    page_added = 0
                    for item in dom_items:
                        title_raw = item.get("title", "").split("\n")[0].strip()
                        price_raw = item.get("price", "")
                        raw_code = item.get("sku")

                        match = re.search(r"(\d+[\.,]\d{2})", price_raw)
                        if title_raw and match:
                            price_val = float(match.group(1).replace(",", "."))
                            dedup_key = f"{title_raw}_{price_val}"

                            if dedup_key not in processed_in_cat:
                                processed_in_cat.add(dedup_key)
                                if save_product(title_raw, cat_name, price_val, str(raw_code) if raw_code else None):
                                    cat_saved += 1
                                    total_items += 1
                                    page_added += 1
                                    if clean_ean(raw_code):
                                        cat_eans += 1
                                        total_eans += 1

                    if page_added == 0 and page_num > 2:
                        # Stop advancing if no new unique items are found
                        break

                except Exception as e:
                    print(f"   ❌ Page {page_num} Error: {e}")
                    break

            print(f"   ✅ '{cat_name}' Summary: {cat_saved} items saved ({cat_eans} with SKU/EAN)")

        await browser.close()

    db_pool.closeall()

    print("\n" + "=" * 60)
    print("📊 DEEP SELVER INGESTION REPORT")
    print("=" * 60)
    print(f"Total Unique Products Saved/Updated: {total_items}")
    print(f"Products with Valid SKU/EAN:          {total_eans}")
    print("============================================================\n")


if __name__ == "__main__":
    asyncio.run(scrape_selver())