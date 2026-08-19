import asyncio
import re
import psycopg2
from playwright.async_api import async_playwright

DB_URL = "postgresql://postgres.ocxnykaqirzvwimyvdtt:Rosamund6498!%40%23@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"

STORES_CONFIG = {
    "Rimi Baltic": [
        ("Piimatooted ja munad", "https://www.rimi.ee/epood/ee/tooted/piimatooted-ja-munad/c/SH-1"),
        ("Leivad, saiad, kondiitritooted", "https://www.rimi.ee/epood/ee/tooted/leivad-saiad-konditooted/c/SH-2"),
        ("Puuviljad ja köögiviljad", "https://www.rimi.ee/epood/ee/tooted/puuviljad-ja-koogiviljad/c/SH-15"),
        ("Liha ja linnuliha", "https://www.rimi.ee/epood/ee/tooted/liha-ja-linnuliha/c/SH-3"),
        ("Joogid", "https://www.rimi.ee/epood/ee/tooted/joogid/c/SH-5"),
    ],
    "Prisma EE": [
        ("Piimatooted ja munad", "https://www.prismamarket.ee/products/18236"),
        ("Leivad, saiad, kondiitritooted", "https://www.prismamarket.ee/products/18235"),
        ("Puuviljad ja köögiviljad", "https://www.prismamarket.ee/products/18234"),
        ("Liha ja linnuliha", "https://www.prismamarket.ee/products/18237"),
        ("Joogid", "https://www.prismamarket.ee/products/18241"),
    ]
}


def save_product(title, category, store, price):
    """Inserts scraped products directly into Supabase PostgreSQL."""
    try:
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO grocery_products (product_name, category, store_name, price)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (product_name, store_name) 
            DO UPDATE SET price = EXCLUDED.price, category = EXCLUDED.category, updated_at = CURRENT_TIMESTAMP;
            """,
            (title, category, store, price),
        )
        conn.commit()
        cursor.close()
        conn.close()
        print(f"✅ DB Saved: [{store}] [{category}] {title} - €{price:.2f}")
    except Exception as e:
        print(f"❌ DB Write Error for '{title}': {e}")


async def scrape_rimi(page, categories):
    for cat_name, cat_url in categories:
        print(f"\n📂 [Rimi Baltic] Ingesting category: '{cat_name}'...")
        try:
            await page.goto(cat_url, wait_until="domcontentloaded", timeout=25000)
            
            try:
                cookie_btn = await page.wait_for_selector("#onetrust-accept-btn-handler", timeout=2500)
                if cookie_btn:
                    await cookie_btn.click()
            except Exception:
                pass

            await page.mouse.wheel(0, 1500)
            await page.wait_for_timeout(2000)

            cards = await page.query_selector_all(".product-grid__item")
            print(f"   Found {len(cards)} items inside '{cat_name}'")

            for card in cards[:20]:
                name_el = await card.query_selector(".card__name, [class*='name']")
                price_el = await card.query_selector(".price-badge, [class*='price']")

                if name_el and price_el:
                    title = await name_el.inner_text()
                    price_raw = await price_el.inner_text()
                    clean_match = re.search(r"(\d+[\.,]\d{2})", price_raw.replace("\n", "").replace(" ", ""))
                    if clean_match and title.strip():
                        price_val = float(clean_match.group(1).replace(",", "."))
                        save_product(title.strip(), cat_name, "Rimi Baltic", price_val)

        except Exception as e:
            print(f"⚠️ Rimi crawl error for '{cat_name}': {e}")


async def scrape_prisma(page, categories):
    for cat_name, cat_url in categories:
        print(f"\n📂 [Prisma EE] Ingesting category: '{cat_name}'...")
        try:
            await page.goto(cat_url, wait_until="domcontentloaded", timeout=25000)

            # Cookie Banner Handler for Prismamarket
            try:
                cookie_btn = await page.wait_for_selector("button:has-text('Nõustun')", timeout=2500)
                if cookie_btn:
                    await cookie_btn.click()
            except Exception:
                pass

            await page.mouse.wheel(0, 1500)
            await page.wait_for_timeout(2000)

            # Prismamarket active item card selectors
            cards = await page.query_selector_all(".js-shelf-item, .item-card, [data-product-id]")
            print(f"   Found {len(cards)} items inside '{cat_name}'")

            for card in cards[:20]:
                name_el = await card.query_selector(".name, .title, [class*='name']")
                price_el = await card.query_selector(".price, .unit-price, [class*='price']")

                if name_el and price_el:
                    title = await name_el.inner_text()
                    price_raw = await price_el.inner_text()
                    clean_match = re.search(r"(\d+[\.,]\d{2})", price_raw.replace("\n", "").replace(" ", ""))
                    if clean_match and title.strip():
                        price_val = float(clean_match.group(1).replace(",", "."))
                        save_product(title.strip(), cat_name, "Prisma EE", price_val)

        except Exception as e:
            print(f"⚠️ Prisma crawl error for '{cat_name}': {e}")


async def run_multi_store_scraper():
    print("🌐 Launching Playwright Engine for Multi-Store Database Ingestion...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
        )
        page = await context.new_page()

        await scrape_rimi(page, STORES_CONFIG["Rimi Baltic"])
        await scrape_prisma(page, STORES_CONFIG["Prisma EE"])

        await browser.close()


if __name__ == "__main__":
    asyncio.run(run_multi_store_scraper())