import os
import re
import psycopg2
from playwright.sync_api import sync_playwright
from deep_translator import GoogleTranslator

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/postgres")
translator = GoogleTranslator(source="et", target="en")

BANNED_TITLES = {
    "et", "en", "järve selver", "selver", "prisma", "google analytics 4", 
    "usercentrics consent management platform", "consent", "cookie", "unknown"
}


def translate_to_english(text_et: str) -> str:
    """Translates Estonian product titles to English safely."""
    if not text_et or text_et.lower() in BANNED_TITLES:
        return ""
    try:
        translated = translator.translate(text_et)
        return translated.strip() if translated else text_et
    except Exception:
        return text_et


def generate_fallback_ean(title: str) -> str:
    clean_title = re.sub(r"\s+", " ", title.lower().strip())
    hash_num = abs(hash(clean_title)) % 10000000000
    return f"474{hash_num:010d}"


def is_valid_title(title: str) -> bool:
    if not title or not isinstance(title, str):
        return False
    clean = title.strip().lower()
    if clean in BANNED_TITLES or len(clean) < 3:
        return False
    if "analytics" in clean or "consent" in clean or clean == "selver" or clean == "prisma":
        return False
    return True


def save_product_to_db(item, store_name):
    ean = item.get("ean")
    title_et = item.get("title")
    price = item.get("price")

    if not ean or not price or not is_valid_title(title_et):
        return False

    title_en = translate_to_english(title_et)

    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            ALTER TABLE public.grocery_products 
            ADD COLUMN IF NOT EXISTS product_name_en TEXT;
        """)

        cursor.execute("""
            INSERT INTO public.grocery_products 
                (ean, store_name, product_name, product_name_en, price, image_url, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (ean, store_name) DO UPDATE SET
                price = EXCLUDED.price,
                product_name = EXCLUDED.product_name,
                product_name_en = EXCLUDED.product_name_en,
                image_url = EXCLUDED.image_url;
        """, (ean, store_name, title_et, title_en, price, item.get("image_url", "")))
        
        conn.commit()
        print(f"  └─ ✅ Ingested [{store_name}]: '{title_en}' ({price:.2f} € | EAN: {ean})")
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()


def scrape_store_search(page, store_name, search_url):
    print(f"\n🌐 Crawling {store_name}: {search_url}")
    captured_products = []
    seen_titles = set()

    def process_node(node):
        if isinstance(node, dict):
            title = node.get("title") or node.get("name") or node.get("product_name")
            
            price = node.get("price") or node.get("final_price") or node.get("unit_price") or node.get("price_incl_tax")
            if not price and "price_range" in node:
                price = node["price_range"].get("minimum_price", {}).get("final_price", {}).get("value")
            elif isinstance(price, dict):
                price = price.get("value") or price.get("amount")

            barcodes = node.get("barcodes") or node.get("gtin13") or node.get("ean") or node.get("sku") or node.get("code")
            ean = str(barcodes[0]) if (isinstance(barcodes, list) and barcodes) else (str(barcodes) if barcodes else None)

            if title and price:
                try:
                    price_val = float(str(price).replace(",", "."))
                    clean_title = str(title).strip()

                    if 0.10 <= price_val <= 300.0 and is_valid_title(clean_title) and clean_title not in seen_titles:
                        seen_titles.add(clean_title)
                        clean_ean = ean if (ean and ean.isdigit() and len(ean) >= 8) else generate_fallback_ean(clean_title)

                        img = node.get("image") or node.get("small_image") or node.get("image_url") or ""
                        if isinstance(img, dict):
                            img = img.get("url", "")
                        elif isinstance(img, list) and img:
                            img = img[0]

                        captured_products.append({
                            "ean": clean_ean,
                            "title": clean_title,
                            "price": price_val,
                            "image_url": str(img) if img else ""
                        })
                except ValueError:
                    pass

            for k, v in node.items():
                process_node(v)
        elif isinstance(node, list):
            for item in node:
                process_node(item)

    def handle_response(response):
        try:
            content_type = response.headers.get("content-type", "")
            if "json" in content_type or "graphql" in content_type:
                data = response.json()
                process_node(data)
        except Exception:
            pass

    page.on("response", handle_response)

    try:
        # Load page with 15s timeout
        page.goto(search_url, timeout=15000, wait_until="commit")
        page.wait_for_timeout(2500)

        # Scroll to trigger dynamic loading
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        page.wait_for_timeout(1000)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)

    except Exception as e:
        print(f"  └─ ⚠️ Timeout/Warning for {store_name}: {e}")
    finally:
        page.remove_listener("response", handle_response)

    return captured_products


def main():
    # Direct search terms across categories (Eggs, Milk, Cheese, Butter, Bread, Meat)
    search_queries = ["munad", "piim", "juust", "või", "leib", "liha"]

    total_ingested = 0
    print("🚀 Crawling all products across Selver & Prisma...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1400, "height": 900},
            extra_http_headers={"Accept-Language": "et-EE,et;q=0.9,en-US;q=0.8,en;q=0.7"}
        )

        for q in search_queries:
            targets = [
                {"store": "Selver", "url": f"https://www.selver.ee/catalogsearch/result/?q={q}"},
                {"store": "Prisma", "url": f"https://www.prismamarket.ee/s?queryString={q}"}
            ]

            for target in targets:
                page = context.new_page()
                items = scrape_store_search(page, target["store"], target["url"])

                for item in items:
                    if save_product_to_db(item, target["store"]):
                        total_ingested += 1

                page.close()

        browser.close()

    print(f"\n🎉 Finished Full Extraction! Translated & ingested {total_ingested} real products into PostgreSQL.")


if __name__ == "__main__":
    main()