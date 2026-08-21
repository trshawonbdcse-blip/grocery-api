import os
import re
import json
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

    # Deduplicate by title
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
    print("\n🚀 Ingesting Barbora (Maxima) via Next.js State Extraction...")
    items = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        categories = [
            "piimatooted-ja-munad", "leivatooted", "puuviljad-koogiviljad", 
            "lihatooted", "joogid", "kuivained", "kuelmutatud-tooted"
        ]
        
        for cat in categories:
            print(f"  → Extracting Barbora state for: {cat}")
            try:
                await page.goto(f"https://www.barbora.ee/{cat}", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(1)

                # Extract raw Next.js JSON state
                next_data = await page.evaluate("""() => {
                    const el = document.querySelector('#__NEXT_DATA__');
                    return el ? el.innerText : null;
                }""")

                if next_data:
                    data = json.loads(next_data)
                    # Recursively search for product arrays inside pageProps
                    page_props = data.get("props", {}).get("pageProps", {})
                    
                    def find_products(obj):
                        if isinstance(obj, dict):
                            if "id" in obj and "title" in obj and "price" in obj:
                                title = obj.get("title")
                                price = obj.get("price")
                                img = obj.get("image", "")
                                url = obj.get("url", "")
                                full_url = f"https://www.barbora.ee{url}" if url.startswith("/") else url
                                if title and price:
                                    items.append((title, "Groceries", "Maxima EE", float(price), img, full_url))
                            for k, v in obj.items():
                                find_products(v)
                        elif isinstance(obj, list):
                            for item in obj:
                                find_products(item)

                    find_products(page_props)
            except Exception as e:
                print(f"  ⚠️ Error on category {cat}: {e}")

        await browser.close()
        
    save_items(items, "Maxima EE")

async def scrape_selver():
    print("\n🚀 Ingesting Selver via Direct DOM Card Parsing...")
    items = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        terms = ["piim", "leib", "juust", "või", "õun", "kana", "muna", "vesi", "kohv", "tee", "liha", "kala", "jogurt"]
        
        for term in terms:
            print(f"  → Extracting Selver term: {term}")
            try:
                await page.goto(f"https://www.selver.ee/search?q={term}", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(2)
                
                # Extract rendered product links directly from page
                cards = await page.query_selector_all("a[href*='.html']")
                for card in cards:
                    try:
                        text = await card.inner_text()
                        href = await card.get_attribute("href")
                        
                        # Match title and price pattern in text block
                        lines = [l.strip() for l in text.split("\n") if l.strip()]
                        price_match = re.search(r"(\d+[\.,]\d{2})\s*€?", text)
                        
                        if lines and price_match:
                            title = lines[0]
                            price_val = float(price_match.group(1).replace(",", "."))
                            full_url = href if href.startswith("http") else f"https://www.selver.ee{href}"
                            
                            if len(title) > 3 and price_val > 0 and "ostukorv" not in title.lower():
                                items.append((title, "Groceries", "Selver", price_val, "", full_url))
                    except Exception:
                        continue
            except Exception as e:
                print(f"  ⚠️ Error on Selver term '{term}': {e}")

        await browser.close()

    save_items(items, "Selver")

async def main():
    await scrape_barbora()
    await scrape_selver()

if __name__ == "__main__":
    asyncio.run(main())
