import asyncio
import re
import psycopg2
from playwright.async_api import async_playwright

DB_URL = "postgresql://postgres.ocxnykaqirzvwimyvdtt:Rosamund6498!%40%23@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
PAGES_PER_CATEGORY = 10  # Set page depth cap per category


def save_product(title, category, store, price, ean=None):
    """Upserts scraped products into Supabase PostgreSQL with EAN support."""
    try:
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO grocery_products (product_name, category, store_name, price, ean)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (product_name, store_name) 
            DO UPDATE SET 
                price = EXCLUDED.price, 
                category = EXCLUDED.category, 
                ean = COALESCE(EXCLUDED.ean, grocery_products.ean), 
                updated_at = CURRENT_TIMESTAMP;
            """,
            (title, category, store, price, ean),
        )
        conn.commit()
        cursor.close()
        conn.close()
        ean_str = f" [EAN: {ean}]" if ean else ""
        print(f"✅ DB Saved: [{store}] [{category}] {title}{ean_str} - €{price:.2f}")
    except Exception as e:
        print(f"❌ DB Write Error for '{title}': {e}")


async def scrape_prisma_dynamic():
    print("🌐 Launching Playwright Dynamic Engine for Prisma Estonia...")
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

        print("🔍 Navigating to https://www.prismamarket.ee/tooted...")
        await page.goto("https://www.prismamarket.ee/tooted", wait_until="domcontentloaded", timeout=30000)

        try:
            cookie_btn = await page.wait_for_selector("button:has-text('Nõustun'), #cookie-consent-accept-button", timeout=3000)
            if cookie_btn:
                await cookie_btn.click()
                await page.wait_for_timeout(1000)
        except Exception:
            pass

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

        for cat_name, cat_url in dynamic_categories:
            print(f"\n📂 Ingesting category: '{cat_name}'...")
            processed_in_cat = set()

            for page_num in range(1, PAGES_PER_CATEGORY + 1):
                page_target_url = f"{cat_url}?page={page_num}" if page_num > 1 else cat_url
                print(f"   📄 Scraping Page {page_num}...")

                try:
                    await page.goto(page_target_url, wait_until="domcontentloaded", timeout=30000)

                    # Progressive Scroll to force trigger infinite loading / card hydration
                    for _ in range(5):
                        await page.mouse.wheel(0, 1200)
                        await page.wait_for_timeout(300)

                    # Click 'Laadi rohkem' (Load More) if present
                    try:
                        load_more = await page.query_selector("button:has-text('Laadi rohkem'), button:has-text('Näita rohkem')")
                        if load_more and await load_more.is_visible():
                            await load_more.click()
                            await page.wait_for_timeout(1000)
                    except Exception:
                        pass

                    cards = await page.query_selector_all("article, [class*='ProductCard'], [data-product-id], [data-test-id='product-card']")
                    if not cards:
                        print(f"   ℹ️ Reached end of category at page {page_num - 1}.")
                        break

                    saved_count = 0
                    # REMOVED [:20] CUTOFF - Iterating through ALL discovered cards
                    for card in cards:
                        name_el = await card.query_selector("a[class*='name'], [class*='title'], h2, h3, div[class*='Name']")
                        price_el = await card.query_selector("[class*='price']:not([class*='unit']), [data-test-id='product-price'], span[class*='Price']")

                        ean_val = None
                        ean_attr = await card.get_attribute("data-gtin") or await card.get_attribute("data-ean") or await card.get_attribute("data-product-id")
                        if ean_attr and re.match(r"^\d{8,14}$", ean_attr.strip()):
                            ean_val = ean_attr.strip()

                        if not name_el:
                            name_el = await card.query_selector("a")
                        if not price_el:
                            price_el = card

                        if name_el and price_el:
                            title_text = await name_el.inner_text()
                            price_text = await price_el.inner_text()
                            clean_title = title_text.strip().split("\n")[0]

                            price_match = re.search(r"(\d+[\.,]\d{2})", price_text.replace(" ", ""))
                            if price_match and len(clean_title) > 2 and clean_title not in ["Tooted", "Otsi"]:
                                price_val = float(price_match.group(1).replace(",", "."))
                                dedup_key = f"{clean_title}_{price_val}"

                                if dedup_key not in processed_in_cat:
                                    processed_in_cat.add(dedup_key)
                                    save_product(clean_title, cat_name, "Prisma EE", price_val, ean_val)
                                    saved_count += 1

                    if saved_count == 0 and page_num > 1:
                        print(f"   ℹ️ No new unique items on page {page_num}. Moving to next category.")
                        break

                except Exception as e:
                    print(f"⚠️ Error crawling '{cat_name}' page {page_num}: {e}")
                    break

        await browser.close()


if __name__ == "__main__":
    asyncio.run(scrape_prisma_dynamic())