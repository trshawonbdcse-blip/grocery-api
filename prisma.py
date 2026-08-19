import asyncio
import os
import psycopg2
from playwright.async_api import async_playwright

DB_URL = "postgresql://postgres.ocxnykaqirzvwimyvdtt:Rosamund6498!%40%23@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"

PRISMA_CATEGORIES = [
    ("Piimatooted ja munad", "https://www.prismamarket.ee/products/18236"),
    ("Leivad, saiad, kondiitritooted", "https://www.prismamarket.ee/products/18235"),
    ("Puuviljad ja köögiviljad", "https://www.prismamarket.ee/products/18234"),
    ("Liha ja linnuliha", "https://www.prismamarket.ee/products/18237"),
    ("Joogid", "https://www.prismamarket.ee/products/18241"),
]


def save_product(title, category, store, price):
    """Upserts product into Supabase PostgreSQL."""
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
        print(f"❌ DB Error for '{title}': {e}")


async def scrape_prisma_only():
    print("🌐 Launching Playwright Network Interceptor for Prisma EE...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
        )
        page = await context.new_page()

        for cat_name, cat_url in PRISMA_CATEGORIES:
            print(f"\n📂 [Prisma EE] Ingesting category: '{cat_name}'...")

            # Capture background API payloads containing raw JSON product data
            async def handle_response(response, current_cat=cat_name):
                if "api/" in response.url or "products" in response.url or "search" in response.url:
                    try:
                        if response.status == 200 and "json" in response.headers.get("content-type", ""):
                            data = await response.json()
                            
                            # Handle standard Prisma JSON payload structures
                            items = []
                            if isinstance(data, dict):
                                items = data.get("entries", []) or data.get("items", []) or data.get("products", [])
                            elif isinstance(data, list):
                                items = data

                            for item in items:
                                name = item.get("name") or item.get("title")
                                price = item.get("price") or item.get("unit_price")
                                if isinstance(price, dict):
                                    price = price.get("value")

                                if name and price:
                                    save_product(name.strip(), current_cat, "Prisma EE", float(price))
                    except Exception:
                        pass

            page.on("response", handle_response)

            try:
                await page.goto(cat_url, wait_until="networkidle", timeout=30000)

                # Cookie handler
                try:
                    cookie_btn = await page.wait_for_selector("button:has-text('Nõustun')", timeout=2500)
                    if cookie_btn:
                        await cookie_btn.click()
                except Exception:
                    pass

                # Scroll to trigger dynamic API fetches
                await page.mouse.wheel(0, 2000)
                await page.wait_for_timeout(3000)

            except Exception as e:
                print(f"⚠️ Error crawling '{cat_name}': {e}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(scrape_prisma_only())