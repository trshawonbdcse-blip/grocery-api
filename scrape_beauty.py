import asyncio
import re
import os
import json
from playwright.async_api import async_playwright
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")

# --- CATEGORY MAPPING ENGINE ---
def categorize_product(title: str, url: str) -> str:
    text = f"{title} {url}".lower()

    if any(k in text for k in ["parfüm", "perfume", "parfum", "eau de", "edt", "edp", "cologne", "lõhn"]):
        return "Perfume"
    elif any(k in text for k in ["huule", "pudel", "mascara", "ripsme", "jumestus", "foundation", "lipstick", "makeup", "puder", "põsepuna", "laovärv", "peitepulk", "küünelakk", "gloss"]):
        return "Makeup"
    elif any(k in text for k in ["šampoon", "shampoo", "palsam", "conditioner", "juukse", "hair", "mask", "õli", "seerum", "juustele"]):
        return "Hair care"
    elif any(k in text for k in ["näo", "facial", "face", "kreem", "cream", "seerum", "serum", "toonik", "puhastus", "cleanser", "silma", "silmakreem"]):
        return "Facial care"
    elif any(k in text for k in ["keha", "body", "duši", "shower", "kreem", "lotion", "seep", "scrub", "koorija", "deodorant"]):
        return "Body care"
    elif any(k in text for k in ["hamba", "oral", "tooth", "paste", "hari", "brush", "suuvesi"]):
        return "Oral care"
    elif any(k in text for k in ["laps", "beebi", "baby", "child", "mother", "ema", "mähkmed"]):
        return "Mother and child"
    elif any(k in text for k in ["meeste", "men", "for men", "habeme", "shave", "aftershave"]):
        return "For men"
    elif any(k in text for k in ["päike", "sun", "spf", "päevitus", "after sun"]):
        return "Sun"
    elif any(k in text for k in ["seade", "sirgendaja", "kuivati", "dryer", "trimmer", "epilaator", "electrical"]):
        return "Electrical equipment"
    elif any(k in text for k in ["derma", "apteek", "pharmacy", "sensitive"]):
        return "Dermacosmetics"
    elif any(k in text for k in ["luxury", "luksus", "exclusive"]):
        return "Luxury"
    
    return "Facial care"

def save_product(title, fallback_cat, store, current_price, original_price, img, url, volume=""):
    bad_titles = ["ALLAHINDLUS!", "UUS!", "SALE", "ALE", "SOODUSTUS", "OSTA", "PRIVACY", "COOKIES", "NÕUSTUN"]
    if not DATABASE_URL or not title or len(title) < 3 or title.strip().upper() in bad_titles:
        return

    category = categorize_product(title, url)

    discount_pct = 0
    if original_price and original_price > current_price:
        discount_pct = round(((original_price - current_price) / original_price) * 100)

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO beauty_products 
            (title, category, store_name, current_price, original_price, discount_percentage, image_url, product_url, volume_size, is_discounted)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (store_name, title, volume_size) 
            DO UPDATE SET 
                category = EXCLUDED.category,
                current_price = EXCLUDED.current_price,
                original_price = EXCLUDED.original_price,
                discount_percentage = EXCLUDED.discount_percentage,
                scraped_at = NOW();
        """, (title, category, store, current_price, original_price, discount_pct, img, url, volume, discount_pct > 0))
        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ DB Saved: [{store}] [{category}] {title} - €{current_price} (-{discount_pct}%)")
    except Exception as e:
        print(f"❌ DB Error saving '{title}': {e}")

# 1. NOTINO (UNCHANGED)
async def scrape_notino(page):
    print("\n📂 Scraping Notino.ee...")
    try:
        await page.goto("https://www.notino.ee/special-promo/", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)

        items = await page.query_selector_all("a[href*='.ee/'], a[href*='/']")
        saved = 0
        for item in items:
            if saved >= 20:
                break
            try:
                href = await item.get_attribute("href")
                text_content = await item.inner_text()
                prices = re.findall(r"(\d+[\.,]\d{2})\s*€", text_content)

                lines = [l.strip() for l in text_content.split("\n") if l.strip() and "€" not in l and "%" not in l]
                title = lines[0] if lines else ""

                if prices and title and len(title) > 3 and href and "cookie" not in href.lower():
                    curr_val = float(prices[0].replace(",", "."))
                    orig_val = float(prices[1].replace(",", ".")) if len(prices) > 1 else curr_val
                    img_el = await item.query_selector("img")
                    img = await img_el.get_attribute("src") if img_el else ""

                    full_url = href if href.startswith("http") else f"https://www.notino.ee{href}"
                    save_product(
                        title=title, fallback_cat="", store="Notino",
                        current_price=curr_val, original_price=orig_val if orig_val > curr_val else curr_val,
                        img=img, url=full_url
                    )
                    saved += 1
            except Exception:
                continue
    except Exception as e:
        print(f"⚠️ Notino error: {e}")

# 2. LOVERTE (NETWORK INTERCEPTOR FOR API PAYLOADS)
async def scrape_loverte(page, max_pages=3):
    print("\n📂 Scraping Loverte.com (API Network Interceptor)...")
    captured_products = []

    # Listen to background XHR/GraphQL/API JSON responses
    async def handle_response(response):
        if "graphql" in response.url or "api" in response.url or "catalog" in response.url or "products" in response.url:
            try:
                data = await response.json()
                if isinstance(data, dict):
                    # Traverse common JSON response paths
                    items = (
                        data.get("products", {}).get("items") or
                        data.get("data", {}).get("products", {}).get("items") or
                        data.get("items") or
                        []
                    )
                    if isinstance(items, list) and len(items) > 0:
                        captured_products.extend(items)
            except Exception:
                pass

    page.on("response", handle_response)

    for current_page in range(1, max_pages + 1):
        url = f"https://www.loverte.com/et/eripakkumised?page={current_page}"
        print(f"  --> Fetching Loverte Page {current_page}: {url}")
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.evaluate("window.scrollBy(0, 1000)")
            await page.wait_for_timeout(2000)
        except Exception as e:
            print(f"⚠️ Loverte network navigation error: {e}")
            break

    # Process captured JSON products or fallback to direct link query
    print(f"  --> Intercepted {len(captured_products)} raw JSON product records from Loverte API")
    saved = 0

    if captured_products:
        for item in captured_products:
            if isinstance(item, dict):
                title = item.get("name") or item.get("title")
                price_info = item.get("price_range", {}).get("minimum_price", {}) or item.get("price", {})
                
                curr_val = None
                orig_val = None

                if isinstance(price_info, dict):
                    curr_val = price_info.get("final_price", {}).get("value") or price_info.get("value") or price_info.get("price")
                    orig_val = price_info.get("regular_price", {}).get("value") or curr_val

                url_key = item.get("url_key") or item.get("slug") or ""
                image_info = item.get("image", {})
                img = image_info.get("url") if isinstance(image_info, dict) else item.get("small_image", {}).get("url", "")

                if title and curr_val:
                    product_url = f"https://www.loverte.com/et/{url_key}" if url_key else "https://www.loverte.com/et/eripakkumised"
                    save_product(
                        title=str(title).strip(), fallback_cat="", store="Loverte",
                        current_price=float(curr_val), original_price=float(orig_val or curr_val),
                        img=str(img or ""), url=product_url
                    )
                    saved += 1
    
    # Fallback to general DOM link query if API payload structure varies
    if saved == 0:
        print("  --> API intercept empty, falling back to full DOM evaluation...")
        links = await page.query_selector_all("a")
        for link in links:
            try:
                href = await link.get_attribute("href")
                text_content = await link.inner_text()
                prices = re.findall(r"(\d+[\.,]\d{2})\s*€", text_content)

                if href and prices and len(href) > 5 and "privacy" not in href:
                    lines = [l.strip() for l in text_content.split("\n") if l.strip() and "€" not in l and "%" not in l]
                    title = lines[0] if lines else ""

                    if title and len(title) > 3:
                        curr_val = float(prices[0].replace(",", "."))
                        orig_val = float(prices[1].replace(",", ".")) if len(prices) > 1 else curr_val
                        img_el = await link.query_selector("img")
                        img = await img_el.get_attribute("src") if img_el else ""

                        save_product(
                            title=title, fallback_cat="", store="Loverte",
                            current_price=curr_val, original_price=orig_val if orig_val > curr_val else curr_val,
                            img=img, url=href if href.startswith("http") else f"https://www.loverte.com{href}"
                        )
                        saved += 1
            except Exception:
                continue

# 3. MYLOOK (UNCHANGED)
async def scrape_mylook(page):
    print("\n📂 Scraping MyLook.ee...")
    try:
        await page.goto("https://www.mylook.ee/campaign", wait_until="commit", timeout=60000)
        await page.wait_for_timeout(3000)

        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 600)")
            await page.wait_for_timeout(800)

        links = await page.query_selector_all("a")
        saved = 0
        for link in links:
            if saved >= 20:
                break
            try:
                href = await link.get_attribute("href")
                if not href or (".html" not in href and "/p/" not in href):
                    continue

                text = await link.inner_text()
                prices = re.findall(r"(\d+[\.,]\d{2})\s*€", text)
                lines = [l.strip() for l in text.split("\n") if l.strip() and "€" not in l and "%" not in l and "SALE" not in l]
                title = lines[0] if lines else ""

                if prices and title and len(title) > 3:
                    curr_val = float(prices[0].replace(",", "."))
                    orig_val = float(prices[1].replace(",", ".")) if len(prices) > 1 else curr_val
                    img_el = await link.query_selector("img")
                    img = await img_el.get_attribute("src") if img_el else ""

                    save_product(
                        title=title, fallback_cat="", store="MyLook",
                        current_price=curr_val, original_price=orig_val if orig_val > curr_val else curr_val,
                        img=img, url=href if href.startswith("http") else f"https://www.mylook.ee{href}"
                    )
                    saved += 1
            except Exception:
                continue
    except Exception as e:
        print(f"⚠️ MyLook error: {e}")

# 4. IDEAAL KOSMEETIKA (UNCHANGED)
async def scrape_ideaal(page):
    print("\n📂 Scraping IdeaalKosmeetika.ee...")
    try:
        await page.goto("https://www.ideaalkosmeetika.ee/tooted-e-pood/?min_discount=7", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        items = await page.query_selector_all("li.product, div.product-grid-item")

        for item in items:
            try:
                title_el = await item.query_selector(".woocommerce-loop-product__title, .product-title, h2, h3")
                price_el = await item.query_selector(".price")
                link_el = await item.query_selector("a")
                img_el = await item.query_selector("img")

                if title_el and price_el and link_el:
                    title = await title_el.inner_text()
                    price_text = await price_el.inner_text()
                    href = await link_el.get_attribute("href")
                    img = await img_el.get_attribute("src") if img_el else ""

                    prices = re.findall(r"(\d+[\.,]\d{2})\s*€", price_text)
                    if prices and title:
                        curr_val = float(prices[0].replace(",", "."))
                        orig_val = float(prices[1].replace(",", ".")) if len(prices) > 1 else curr_val

                        save_product(
                            title=title.strip().replace("\n", " "),
                            fallback_cat="", store="IdeaalKosmeetika",
                            current_price=curr_val, original_price=orig_val if orig_val > curr_val else curr_val,
                            img=img, url=href
                        )
            except Exception:
                continue
    except Exception as e:
        print(f"⚠️ IdeaalKosmeetika error: {e}")

# 5. TRADEHOUSE (UNCHANGED)
async def scrape_tradehouse(page):
    print("\n📂 Scraping Tradehouse.ee...")
    try:
        await page.goto("https://tradehouse.ee/campaigns/summerhits?lang=en", wait_until="commit", timeout=60000)
        await page.wait_for_timeout(3000)
        links = await page.query_selector_all("a")

        for link in links:
            try:
                href = await link.get_attribute("href")
                if not href or ("product" not in href and "/p/" not in href):
                    continue
                text = await link.inner_text()
                prices = re.findall(r"(\d+[\.,]\d{2})\s*€", text)
                if prices:
                    curr_val = float(prices[0].replace(",", "."))
                    orig_val = float(prices[1].replace(",", ".")) if len(prices) > 1 else curr_val
                    lines = [l.strip() for l in text.split("\n") if l.strip() and "€" not in l and "%" not in l]
                    title = lines[0] if lines else ""
                    img_el = await link.query_selector("img")
                    img = await img_el.get_attribute("src") if img_el else ""

                    if title and len(title) > 3:
                        save_product(
                            title=title, fallback_cat="", store="Tradehouse",
                            current_price=curr_val, original_price=orig_val if orig_val > curr_val else curr_val,
                            img=img, url=href if href.startswith("http") else f"https://tradehouse.ee{href}"
                        )
            except Exception:
                continue
    except Exception as e:
        print(f"⚠️ Tradehouse error: {e}")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        await scrape_notino(page)
        await scrape_loverte(page, max_pages=3)
        await scrape_mylook(page)
        await scrape_ideaal(page)
        await scrape_tradehouse(page)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
