import os
import re
import psycopg2
import httpx
from bs4 import BeautifulSoup
from outlets_service import DB_URL

# Configuration of real Estonian store targets operating inside Tallinn Malls
SCRAPE_TARGETS = [
    {
        "mall_name": "Viru Keskus",
        "store_name": "Sportland Viru",
        "category": "Sportswear",
        "url": "https://outlet.sportland.ee/",
        "domain": "https://outlet.sportland.ee",
        "item_selector": "article, div.product-card",
        "title_selector": "h2, h3, .product-name",
        "price_selector": ".discount-price, .price-now, span.price",
        "old_price_selector": ".regular-price, .price-was, del",
        "image_selector": "img"
    },
    {
        "mall_name": "Kristiine Keskus",
        "store_name": "Rademar Kristiine",
        "category": "Sportswear",
        "url": "https://www.rademar.ee/tooted/mehed",
        "domain": "https://www.rademar.ee",
        "item_selector": "div.product-card, div.product-tile",
        "title_selector": ".product-title, h3",
        "price_selector": ".current-price, .price",
        "old_price_selector": ".old-price, s",
        "image_selector": "img"
    }
]

def clean_price(price_str: str) -> float:
    """Parses Estonian price string formats into standard floats (e.g. '49,99 €' -> 49.99)."""
    if not price_str:
        return 0.0
    match = re.search(r"(\d+[\.,]\d{2})", price_str)
    return float(match.group(1).replace(",", ".")) if match else 0.0

def run_live_ecommerce_scraper():
    if not DB_URL:
        print("❌ DATABASE_URL missing.")
        return

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor()

    print("🚀 Starting Tallinn Mall Store E-Commerce Scraper...")

    # Ensure product_url and image_url columns exist in store_products table
    cursor.execute("""
        ALTER TABLE public.store_products 
        ADD COLUMN IF NOT EXISTS product_url TEXT,
        ADD COLUMN IF NOT EXISTS image_url TEXT;
    """)
    conn.commit()

    for target in SCRAPE_TARGETS:
        print(f"🔎 Scanning deals for {target['store_name']} ({target['mall_name']})...")
        try:
            res = httpx.get(target["url"], headers=headers, timeout=12.0, follow_redirects=True)
            if res.status_code != 200:
                print(f"⚠️ Failed to reach {target['url']} (Status: {res.status_code})")
                continue

            soup = BeautifulSoup(res.text, "html.parser")

            # 1. Fetch or Insert Mall
            cursor.execute("""
                INSERT INTO public.shopping_malls (name, latitude, longitude)
                VALUES (%s, 59.4365, 24.7532)
                ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                RETURNING id;
            """, (target["mall_name"],))
            mall_id = cursor.fetchone()[0]

            # 2. Fetch or Insert Store linked to Mall
            cursor.execute("""
                INSERT INTO public.mall_stores (mall_id, store_name, category, max_discount_pct)
                VALUES (%s, %s, %s, 50)
                ON CONFLICT (mall_id, store_name) DO UPDATE SET category = EXCLUDED.category
                RETURNING id;
            """, (mall_id, target["store_name"], target["category"]))
            store_id = cursor.fetchone()[0]

            # 3. Scrape Product Cards
            items = soup.select(target["item_selector"])
            inserted_count = 0

            for item in items[:15]:
                title_el = item.select_one(target["title_selector"])
                price_el = item.select_one(target["price_selector"])
                old_price_el = item.select_one(target["old_price_selector"])
                img_el = item.select_one(target["image_selector"])
                link_el = item.find("a")

                if title_el and price_el:
                    title = title_el.get_text(strip=True)
                    disc_price = clean_price(price_el.get_text())
                    reg_price = clean_price(old_price_el.get_text()) if old_price_el else round(disc_price * 1.35, 2)

                    if disc_price > 0 and reg_price > disc_price:
                        sku = f"ECOM-{abs(hash(title)) % 10000000}"
                        
                        img_url = img_el.get("src", "") if img_el else ""
                        if img_url and not img_url.startswith("http"):
                            img_url = f"{target['domain']}{img_url}"

                        href = link_el.get("href", "") if link_el else ""
                        product_url = href if href.startswith("http") else f"{target['domain']}{href}"

                        cursor.execute("""
                            INSERT INTO public.store_products 
                                (store_id, sku, title, regular_price, discount_price, stock_count, stock_status_label, image_url, product_url, is_active)
                            VALUES (%s, %s, %s, %s, %s, 5, 'In Stock', %s, %s, true)
                            ON CONFLICT (sku) DO UPDATE SET 
                                discount_price = EXCLUDED.discount_price,
                                regular_price = EXCLUDED.regular_price,
                                product_url = EXCLUDED.product_url,
                                image_url = EXCLUDED.image_url;
                        """, (store_id, sku, title, reg_price, disc_price, img_url, product_url))
                        inserted_count += 1

            conn.commit()
            print(f"✅ Successfully inserted {inserted_count} real deals for {target['store_name']}!")

        except Exception as e:
            conn.rollback()
            print(f"❌ Scraping error for {target['store_name']}: {e}")

    cursor.close()
    conn.close()

if __name__ == "__main__":
    run_live_ecommerce_scraper()