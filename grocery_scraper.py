import asyncio
import re
import json
import psycopg2
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

DB_URL = "postgresql://postgres.ocxnykaqirzvwimyvdtt:Rosamund6498!%40%23@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"

STORES_CONFIG = {
    "Rimi Baltic": [
        ("Piimatooted ja munad", "https://www.rimi.ee/epood/ee/tooted/piimatooted-ja-munad/c/SH-1"),
        ("Leivad, saiad, kondiitritooted", "https://www.rimi.ee/epood/ee/tooted/leivad-saiad-konditooted/c/SH-2"),
        ("Puuviljad ja köögiviljad", "https://www.rimi.ee/epood/ee/tooted/puuviljad-ja-koogiviljad/c/SH-15"),
        ("Liha ja linnuliha", "https://www.rimi.ee/epood/ee/tooted/liha-ja-linnuliha/c/SH-3"),
        ("Joogid", "https://www.rimi.ee/epood/ee/tooted/joogid/c/SH-5"),
    ]
}

def save_product(title, category, store, price, ean=None):
    """Inserts scraped products directly into Supabase PostgreSQL."""
    try:
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO grocery_products (product_name, category, store_name, price, ean)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (product_name, store_name) 
            DO UPDATE SET price = EXCLUDED.price, category = EXCLUDED.category, ean = COALESCE(EXCLUDED.ean, grocery_products.ean), updated_at = CURRENT_TIMESTAMP;
            """,
            (title, category, store, price, ean),
        )
        conn.commit()
        cursor.close()
        conn.close()
        ean_str = f" [EAN: {ean}]" if ean else " [NO EAN]"
        print(f"✅ DB Saved: [{store}] [{category}] {title}{ean_str} - €{price:.2f}")
    except Exception as e:
        print(f"❌ DB Write Error for '{title}': {e}")


async def scrape_rimi(page, categories):
    for cat_name, cat_url in categories:
        print(f"\n📂 [Rimi Baltic] Ingesting category: '{cat_name}'...")
        try:
            await page.goto(cat_url, wait_until="domcontentloaded", timeout=30000)
            
            try:
                cookie_btn = await page.wait_for_selector("#onetrust-accept-btn-handler", timeout=2500)
                if cookie_btn:
                    await cookie_btn.click()
            except Exception:
                pass

            await page.mouse.wheel(0, 2000)
            await page.wait_for_timeout(2000)

            # Target the main product grid container exclusively (bypassing top banners)
            cards = await page.query_selector_all("main .product-grid .product-grid__item, div[class*='product-grid'] .product-grid__item")
            print(f"   Found {len(cards)} items inside '{cat_name}'")

            for card in cards[:20]:
                name_el = await card.query_selector(".card__name, [class*='name']")
                price_el = await card.query_selector(".price-badge, [class*='price']")
                link_el = await card.query_selector("a.card__url, a[href*='/p/']")

                ean_val = None
                if link_el:
                    href = await link_el.get_attribute("href")
                    if href:
                        # Extract EAN barcode if appended to product link structure
                        code_match = re.search(r"/p/(\d{8,14})", href)
                        if code_match:
                            ean_val = code_match.group(1)

                if name_el and price_el:
                    title = await name_el.inner_text()
                    price_raw = await price_el.inner_text()
                    clean_match = re.search(r"(\d+[\.,]\d{2})", price_raw.replace("\n", "").replace(" ", ""))

                    if clean_match and title.strip():
                        price_val = float(clean_match.group(1).replace(",", "."))
                        save_product(title.strip(), cat_name, "Rimi Baltic", price_val, ean_val)

        except Exception as e:
            print(f"⚠️ Rimi crawl error for '{cat_name}': {e}")


async def run_multi_store_scraper():
    print("🌐 Launching Playwright Engine for Rimi Ingestion...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
        )
        page = await context.new_page()

        await scrape_rimi(page, STORES_CONFIG["Rimi Baltic"])
        await browser.close()


if __name__ == "__main__":
    asyncio.run(run_multi_store_scraper())