import asyncio
import re
import psycopg2
from playwright.async_api import async_playwright

DB_URL = "postgresql://postgres.ocxnykaqirzvwimyvdtt:Rosamund6498!%40%23@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"


def save_product(title, category, store, price):
    """Upserts scraped products into Supabase PostgreSQL."""
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
        print(f"✅ DB Saved: [Prisma EE] [{category}] {title} - €{price:.2f}")
    except Exception as e:
        print(f"❌ DB Write Error for '{title}': {e}")


async def scrape_prisma_dynamic():
    print("🌐 Launching Playwright Dynamic Engine for Prisma Estonia...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
        )
        page = await context.new_page()

        print("🔍 Navigating to https://www.prismamarket.ee/tooted...")
        await page.goto("https://www.prismamarket.ee/tooted", wait_until="domcontentloaded", timeout=30000)

        # 1. Accept Cookie Banner
        try:
            cookie_btn = await page.wait_for_selector("button:has-text('Nõustun')", timeout=3000)
            if cookie_btn:
                await cookie_btn.click()
                await page.wait_for_timeout(1000)
        except Exception:
            pass

        # 2. Extract Category Pill Buttons
        await page.wait_for_selector("a[href*='/tooted/']", timeout=10000)
        pill_elements = await page.query_selector_all("a[href*='/tooted/']")
        
        dynamic_categories = []
        for el in pill_elements:
            href = await el.get_attribute("href")
            text = await el.inner_text()
            clean_name = text.strip().replace("\n", " ")

            if href and clean_name and href != "/tooted":
                full_url = f"https://www.prismamarket.ee{href}" if href.startswith("/") else href
                if (clean_name, full_url) not in dynamic_categories:
                    dynamic_categories.append((clean_name, full_url))

        print(f"🎯 Dynamically discovered {len(dynamic_categories)} categories from UI pills!")

        # 3. Crawl each discovered category
        for cat_name, cat_url in dynamic_categories:
            print(f"\n📂 Ingesting dynamic category: '{cat_name}'...")
            try:
                await page.goto(cat_url, wait_until="domcontentloaded", timeout=25000)
                await page.mouse.wheel(0, 1500)
                await page.wait_for_timeout(2000)

                # Locate grid product cards
                cards = await page.query_selector_all("article, [class*='ProductCard'], [data-product-id]")
                print(f"   Found {len(cards)} items inside '{cat_name}'")

                saved_in_category = 0
                for card in cards[:20]:
                    # Precise title selector targeting product name elements
                    name_el = await card.query_selector("a[class*='name'], [class*='title'], h2, h3, div[class*='Name']")
                    
                    # Precise price selector targeting main item price
                    price_el = await card.query_selector("[class*='price']:not([class*='unit']), [data-test-id='product-price'], span[class*='Price']")

                    if not name_el:
                        # Fallback to direct anchor text inside card
                        name_el = await card.query_selector("a")

                    if not price_el:
                        # Fallback to card text containing € symbol
                        price_el = card

                    if name_el and price_el:
                        title_text = await name_el.inner_text()
                        price_text = await price_el.inner_text()

                        # Clean title string
                        clean_title = title_text.strip().split("\n")[0]

                        # Extract main price float (e.g. "1.99 €" or "1,99")
                        price_match = re.search(r"(\d+[\.,]\d{2})", price_text.replace(" ", ""))
                        if price_match and len(clean_title) > 2 and clean_title not in ["Tooted", "Otsi"]:
                            price_val = float(price_match.group(1).replace(",", "."))
                            save_product(clean_title, cat_name, "Prisma EE", price_val)
                            saved_in_category += 1

                if saved_in_category == 0:
                    print(f"⚠️ Warning: 0 elements parsed inside '{cat_name}'")

            except Exception as e:
                print(f"⚠️ Error crawling '{cat_name}': {e}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(scrape_prisma_dynamic())