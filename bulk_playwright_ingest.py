import os
import re
import asyncio
import psycopg2
from psycopg2.extras import execute_values
from playwright.async_api import async_playwright

DB_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if not DB_URL:
        raise ValueError("DATABASE_URL environment variable is missing!")
    return psycopg2.connect(DB_URL)

def save_items(items, store_name):
    if not items:
        print(f"❌ No items captured for {store_name}.")
        return

    conn = get_db_connection()
    cur = conn.cursor()

    # Deduplicate items by title
    unique_items = list({item[0]: item for item in items}.values())

    query = """
        INSERT INTO grocery_products (product_name, category, store_name, price, image_url, product_url)
        VALUES %s
        ON CONFLICT DO NOTHING;
    """

    try:
        execute_values(cur, query, unique_items)
        conn.commit()
        print(f"✅ Successfully inserted/updated {len(unique_items)} items for {store_name} in PostgreSQL!")
    except Exception as e:
        conn.rollback()
        print(f"❌ DB save error for {store_name}: {e}")
    finally:
        cur.close()
        conn.close()

async def scrape_barbora():
    print("\n🚀 Launching headless browser for Barbora (Maxima)...")
    items = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        categories = [
            "piimatooted-ja-munad", "leivatooted", "puuviljad-koogiviljad", 
            "lihatooted", "joogid", "kuivained", "kuelmutatud-tooted"
        ]
        
        for cat in categories:
            print(f"  → Scraping Barbora category: {cat}")
            try:
                await page.goto(f"https://www.barbora.ee/{cat}", wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(2)
                
                # Scroll down to trigger image loading and lazy rendering
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
                await asyncio.sleep(1)

                # Extract product details directly from the live DOM
                product_cards = await page.query_selector_all("div[data-b-product-id], li[data-plugin='product'], .b-product-card")
                
                for card in product_cards:
                    try:
                        title_el = await card.query_selector("span[itemprop='name'], .b-product-title, div[data-b-product-title]")
                        price_el = await card.query_selector("span[itemprop='price'], .b-product-price, div[data-b-product-price]")
                        img_el = await card.query_selector("img")
                        link_el = await card.query_selector("a")

                        if title_el and price_el:
                            title = (await title_el.inner_text()).strip()
                            price_text = (await price_el.inner_text()).strip()
                            
                            price_match = re.search(r"(\d+[\.,]\d{2})", price_text)
                            if price_match:
                                price_val = float(price_match.group(1).replace(",", "."))
                                img_url = await img_el.get_attribute("src") if img_el else ""
                                href = await link_el.get_attribute("href") if link_el else ""
                                full_url = f"https://www.barbora.ee{href}" if href and href.startswith("/") else (href or "https://www.barbora.ee")

                                if title and price_val > 0:
                                    items.append((title, "Groceries", "Maxima EE", price_val, img_url or "", full_url))
                    except Exception:
                        continue
            except Exception as e:
                print(f"  ⚠️ Error scraping category {cat}: {e}")

        await browser.close()
        
    save_items(items, "Maxima EE")

async def scrape_selver():
    print("\n🚀 Launching headless browser for Selver...")
    items = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # Intercept GraphQL responses during browsing
        async def handle_response(response):
            if "graphql" in response.url and response.request.method == "POST":
                try:
                    data = await response.json()
                    prods = data.get("data", {}).get("products", {}).get("items", [])
                    for p_item in prods:
                        title = p_item.get("name")
                        price_obj = p_item.get("price_range", {}).get("minimum_price", {}).get("final_price", {})
                        price = price_obj.get("value")
                        img = p_item.get("small_image", {}).get("url", "")
                        url_key = p_item.get("url_key", "")
                        full_url = f"https://www.selver.ee/{url_key}.html" if url_key else "https://www.selver.ee"
                        
                        if title and price:
                            items.append((title, "Groceries", "Selver", float(price), img, full_url))
                except Exception:
                    pass

        page.on("response", handle_response)
        
        terms = ["piim", "leib", "juust", "või", "õun", "kana", "muna", "vesi", "kohv", "tee", "liha", "kala", "jogurt"]
        for term in terms:
            print(f"  → Searching Selver term: {term}")
            try:
                # Use domcontentloaded to prevent networkidle timeouts
                await page.goto(f"https://www.selver.ee/search?q={term}", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(2)
            except Exception as e:
                print(f"  ⚠️ Timeout/Error on term '{term}', continuing...")

        await browser.close()

    save_items(items, "Selver")

async def main():
    await scrape_barbora()
    await scrape_selver()

if __name__ == "__main__":
    asyncio.run(main())
