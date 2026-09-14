import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from bs4 import BeautifulSoup
import psycopg2
from playwright.async_api import async_playwright

# --- DATABASE CONNECTION ---
DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres.ocxnykaqirzvwimyvdtt:Rosamund6498%21%40%23@aws-0-eu-central-1.pooler.supabase.com:6543/postgres",
)


def save_product(title: str, category: str, store: str, price: float, ean: str = None):
    """Inserts or updates scraped products in PostgreSQL with EAN barcode indexing."""
    if not title or price <= 0:
        return
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
            (title.strip(), category, store, price, ean),
        )
        conn.commit()
        cursor.close()
        conn.close()
        ean_str = f" [EAN: {ean}]" if ean else " [NO EAN]"
        print(f"  ✅ DB Saved: [{store}] [{category}] {title.strip()}{ean_str} - €{price:.2f}")
    except Exception as e:
        print(f"  ❌ DB Write Error for '{title}': {e}")


# ==========================================
# 1. PRISMA SCRAPER
# ==========================================
PRISMA_CATEGORIES = [
    ("Piimatooted ja munad", "https://www.prismamarket.ee/products/16398"),
    ("Leivad, saiad, kondiitritooted", "https://www.prismamarket.ee/products/16399"),
    ("Puuviljad ja köögiviljad", "https://www.prismamarket.ee/products/16400"),
    ("Liha ja linnuliha", "https://www.prismamarket.ee/products/16401"),
    ("Joogid", "https://www.prismamarket.ee/products/16404"),
]


async def scrape_prisma(context):
    print("\n🌐 Starting Prisma EE Scraper...")
    page = await context.new_page()

    for cat_name, cat_url in PRISMA_CATEGORIES:
        print(f"📂 [Prisma EE] Category: '{cat_name}'")
        try:
            await page.goto(cat_url, wait_until="domcontentloaded", timeout=30000)
            await page.mouse.wheel(0, 1500)
            await page.wait_for_timeout(1500)

            cards = await page.query_selector_all("article, [class*='product-card']")
            for card in cards[:25]:
                name_el = await card.query_selector("div[class*='name'], h3, [class*='title']")
                price_el = await card.query_selector("span[class*='price'], [class*='price']")
                ean_val = await card.get_attribute("data-ean") or await card.get_attribute("data-gtin")

                if name_el and price_el:
                    title = await name_el.inner_text()
                    price_text = await price_el.inner_text()
                    match = re.search(r"(\d+[\.,]\d{2})", price_text.replace(" ", ""))
                    if match and title.strip():
                        save_product(title, cat_name, "Prisma EE", float(match.group(1).replace(",", ".")), ean_val)
        except Exception as e:
            print(f"  ⚠️ Error crawling Prisma '{cat_name}': {e}")

    await page.close()


# ==========================================
# 2. RIMI BALTIC SCRAPER
# ==========================================
RIMI_CATEGORIES = [
    ("Piimatooted ja munad", "https://www.rimi.ee/epood/ee/tooted/piimatooted-ja-munad/c/SH-1"),
    ("Leivad, saiad, kondiitritooted", "https://www.rimi.ee/epood/ee/tooted/leivad-saiad-konditooted/c/SH-2"),
    ("Puuviljad ja köögiviljad", "https://www.rimi.ee/epood/ee/tooted/puuviljad-ja-koogiviljad/c/SH-15"),
    ("Liha ja linnuliha", "https://www.rimi.ee/epood/ee/tooted/liha-ja-linnuliha/c/SH-3"),
    ("Joogid", "https://www.rimi.ee/epood/ee/tooted/joogid/c/SH-5"),
]

ALCOHOL_KEYWORDS = ["viin", "vein", "õlu", "gin", "liköör", "vahuvein", "prosecco", "rumm", "viski", "konjak", "siider"]


async def scrape_rimi(context):
    print("\n🌐 Starting Rimi Baltic Scraper...")
    page = await context.new_page()

    for cat_name, cat_url in RIMI_CATEGORIES:
        print(f"📂 [Rimi Baltic] Category: '{cat_name}'")
        try:
            await page.goto(cat_url, wait_until="networkidle", timeout=30000)

            try:
                cookie_btn = await page.wait_for_selector("#onetrust-accept-btn-handler", timeout=2000)
                if cookie_btn:
                    await cookie_btn.click()
            except Exception:
                pass

            try:
                age_btn = await page.wait_for_selector("button:has-text('Olen vähemalt 18-aastane')", timeout=2000)
                if age_btn:
                    await age_btn.click()
            except Exception:
                pass

            await page.mouse.wheel(0, 1500)
            await page.wait_for_timeout(1500)

            cards = await page.query_selector_all("ul.product-grid > li.product-grid__item, .product-grid__item")

            for card in cards[:25]:
                name_el = await card.query_selector(".card__name, [class*='name']")
                price_el = await card.query_selector(".price-badge, [class*='price']")
                link_el = await card.query_selector("a.card__url, a[href*='/p/']")

                ean_val = None
                if link_el:
                    href = await link_el.get_attribute("href")
                    if href:
                        code_match = re.search(r"/p/(\d{8,14})", href)
                        if code_match:
                            ean_val = code_match.group(1)

                if name_el and price_el:
                    title = await name_el.inner_text()
                    title_clean = title.strip()

                    if cat_name != "Joogid" and any(k in title_clean.lower() for k in ALCOHOL_KEYWORDS):
                        continue

                    price_raw = await price_el.inner_text()
                    match = re.search(r"(\d+[\.,]\d{2})", price_raw.replace("\n", "").replace(" ", ""))

                    if match and title_clean:
                        save_product(title_clean, cat_name, "Rimi Baltic", float(match.group(1).replace(",", ".")), ean_val)
        except Exception as e:
            print(f"  ⚠️ Error crawling Rimi '{cat_name}': {e}")

    await page.close()


# ==========================================
# 3. SELVER SCRAPER
# ==========================================
SELVER_CATEGORIES = [
    ("Piimatooted ja munad", "https://www.selver.ee/piimatooted-munad-ja-void"),
    ("Leivad, saiad, kondiitritooted", "https://www.selver.ee/leivad-saiad-ja-kondiitritooted"),
    ("Puuviljad ja köögiviljad", "https://www.selver.ee/puuviljad-ja-koogiviljad"),
    ("Liha ja linnuliha", "https://www.selver.ee/lihatooted-ja-linnuliha"),
    ("Joogid", "https://www.selver.ee/joogid"),
]


async def scrape_selver(context):
    print("\n🌐 Starting Selver EE Scraper...")
    page = await context.new_page()

    for cat_name, cat_url in SELVER_CATEGORIES:
        print(f"📂 [Selver EE] Category: '{cat_name}'")
        try:
            await page.goto(cat_url, wait_until="domcontentloaded", timeout=30000)

            try:
                cookie_btn = await page.wait_for_selector("#btn-cookie-accept", timeout=2500)
                if cookie_btn:
                    await cookie_btn.click()
            except Exception:
                pass

            await page.mouse.wheel(0, 1500)
            await page.wait_for_timeout(1500)

            cards = await page.query_selector_all(".ProductCard, [data-gtm-product], .product-item")

            for card in cards[:25]:
                name_el = await card.query_selector(".ProductCard__title, .product-name, a[class*='title']")
                price_el = await card.query_selector(".ProductPrice, .price, [class*='price']")

                gtm_data = await card.get_attribute("data-gtm-product") or await card.get_attribute("data-ean")
                ean_val = None
                if gtm_data:
                    try:
                        parsed_gtm = json.loads(gtm_data)
                        ean_val = parsed_gtm.get("ean") or parsed_gtm.get("id")
                    except Exception:
                        match_ean = re.search(r"\b\d{8,14}\b", gtm_data)
                        if match_ean:
                            ean_val = match_ean.group(0)

                if name_el and price_el:
                    title = await name_el.inner_text()
                    price_text = await price_el.inner_text()
                    match = re.search(r"(\d+[\.,]\d{2})", price_text.replace(" ", ""))
                    if match and title.strip():
                        save_product(title.strip(), cat_name, "Selver", float(match.group(1).replace(",", ".")), ean_val)
        except Exception as e:
            print(f"  ⚠️ Error crawling Selver '{cat_name}': {e}")

    await page.close()


# ==========================================
# 4. MAXIMA / BARBORA SCRAPER
# ==========================================
BARBORA_CATEGORIES = [
    ("Piimatooted ja munad", "https://barbora.ee/piimatooted-ja-munad"),
    ("Leivad, saiad, kondiitritooted", "https://barbora.ee/leivatooted-ja-kondiitritooted"),
    ("Puuviljad ja köögiviljad", "https://barbora.ee/puuviljad-ja-koogiviljad"),
    ("Liha ja linnuliha", "https://barbora.ee/lihatooted-ja-linnuliha"),
    ("Joogid", "https://barbora.ee/joogid"),
]


async def scrape_maxima(context):
    print("\n🌐 Starting Maxima (Barbora) Scraper...")
    page = await context.new_page()

    for cat_name, cat_url in BARBORA_CATEGORIES:
        print(f"📂 [Maxima EE] Category: '{cat_name}'")
        try:
            await page.goto(cat_url, wait_until="domcontentloaded", timeout=30000)

            try:
                cookie_btn = await page.wait_for_selector("#onetrust-accept-btn-handler", timeout=2500)
                if cookie_btn:
                    await cookie_btn.click()
            except Exception:
                pass

            await page.mouse.wheel(0, 1500)
            await page.wait_for_timeout(1500)

            cards = await page.query_selector_all("[itemtype*='Product'], .b-product--item")

            for card in cards[:25]:
                name_el = await card.query_selector("[itemprop='name'], .b-product-title")
                price_el = await card.query_selector("[itemprop='price'], .b-product-price")
                ean_val = await card.get_attribute("data-product-id") or await card.get_attribute("data-gtin")

                if name_el and price_el:
                    title = await name_el.inner_text()
                    price_text = await price_el.inner_text()
                    match = re.search(r"(\d+[\.,]\d{2})", price_text.replace(" ", ""))
                    if match and title.strip():
                        save_product(title.strip(), cat_name, "Maxima EE", float(match.group(1).replace(",", ".")), ean_val)
        except Exception as e:
            print(f"  ⚠️ Error crawling Maxima '{cat_name}': {e}")

    await page.close()


# ==========================================
# 5. LIDL ESTONIA SCRAPER
# ==========================================
async def scrape_lidl(context):
    print("\n🌐 Starting Lidl Estonia Scraper...")
    page = await context.new_page()

    try:
        await page.goto("https://www.lidl.ee/et/hinnapomm", wait_until="domcontentloaded", timeout=30000)

        try:
            cookie_btn = await page.wait_for_selector("button:has-text('Nõustu')", timeout=2500)
            if cookie_btn:
                await cookie_btn.click()
        except Exception:
            pass

        await page.mouse.wheel(0, 1500)
        await page.wait_for_timeout(1500)

        cards = await page.query_selector_all(".product-grid-box, article, [data-grid-item]")

        for card in cards[:25]:
            name_el = await card.query_selector(".product-grid-box__title, [class*='title'], h3, h4")
            price_el = await card.query_selector(".pricebox__price, [class*='price']")
            ean_val = await card.get_attribute("data-ean") or await card.get_attribute("data-grid-id")

            if name_el and price_el:
                title = await name_el.inner_text()
                price_text = await price_el.inner_text()
                match = re.search(r"(\d+[\.,]\d{2})", price_text.replace(" ", ""))
                if match and title.strip():
                    save_product(title.strip(), "Sooduspakkumised", "Lidl EE", float(match.group(1).replace(",", ".")), ean_val)
    except Exception as e:
        print(f"  ⚠️ Error crawling Lidl: {e}")

    await page.close()


# ==========================================
# 6. COOP ESTONIA SCRAPER
# ==========================================
COOP_CATEGORIES = [
    ("Piimatooted ja munad", "https://ecoop.ee/et/tooted/piimatooted-munad-void/"),
    ("Leivad, saiad, kondiitritooted", "https://ecoop.ee/et/tooted/leivad-saiad-kondiitritooted/"),
    ("Puuviljad ja köögiviljad", "https://ecoop.ee/et/tooted/puuviljad-koogiviljad/"),
    ("Liha ja linnuliha", "https://ecoop.ee/et/tooted/liha-ja-linnuliha/"),
    ("Joogid", "https://ecoop.ee/et/tooted/joogid/"),
]


async def scrape_coop(context):
    print("\n🌐 Starting Coop Estonia (eCoop) Scraper...")
    page = await context.new_page()

    for cat_name, cat_url in COOP_CATEGORIES:
        print(f"📂 [Coop EE] Category: '{cat_name}'")
        try:
            await page.goto(cat_url, wait_until="domcontentloaded", timeout=30000)

            try:
                cookie_btn = await page.wait_for_selector("button:has-text('Nõustun')", timeout=2500)
                if cookie_btn:
                    await cookie_btn.click()
            except Exception:
                pass

            await page.mouse.wheel(0, 1500)
            await page.wait_for_timeout(1500)

            cards = await page.query_selector_all("[class*='product-card'], .item-card, article")

            for card in cards[:25]:
                name_el = await card.query_selector("a[class*='name'], [class*='title'], h3")
                price_el = await card.query_selector("[class*='price'], .amount")
                ean_val = await card.get_attribute("data-gtin") or await card.get_attribute("data-code")

                if name_el and price_el:
                    title = await name_el.inner_text()
                    price_text = await price_el.inner_text()
                    match = re.search(r"(\d+[\.,]\d{2})", price_text.replace(" ", ""))
                    if match and title.strip():
                        save_product(title.strip(), cat_name, "Coop EE", float(match.group(1).replace(",", ".")), ean_val)
        except Exception as e:
            print(f"  ⚠️ Error crawling Coop '{cat_name}': {e}")

    await page.close()


# ==========================================
# 7. GROSSI TOIDUKAUBAD SCRAPER
# ==========================================
async def scrape_grossi(context):
    print("\n🌐 Starting Grossi Toidukaubad Scraper...")
    page = await context.new_page()

    try:
        await page.goto("https://www.grossi.ee/kliendileht/", wait_until="domcontentloaded", timeout=30000)
        await page.mouse.wheel(0, 1500)
        await page.wait_for_timeout(1500)

        cards = await page.query_selector_all(".product, .offer-card, [class*='item']")

        for card in cards[:25]:
            name_el = await card.query_selector(".title, .name, h3, h4")
            price_el = await card.query_selector(".price, [class*='price']")
            ean_val = await card.get_attribute("data-code") or await card.get_attribute("data-ean")

            if name_el and price_el:
                title = await name_el.inner_text()
                price_text = await price_el.inner_text()
                match = re.search(r"(\d+[\.,]\d{2})", price_text.replace(" ", ""))
                if match and title.strip():
                    save_product(title.strip(), "Sooduspakkumised", "Grossi", float(match.group(1).replace(",", ".")), ean_val)
    except Exception as e:
        print(f"  ⚠️ Error crawling Grossi: {e}")

    await page.close()


# ==========================================
# MASTER RUNNER ENGINE
# ==========================================
async def main():
    print("============================================================")
    print("🛒 UNIFIED TALLINN GROCERY SCRAPER ENGINE (all_grocery.py)")
    print(f"📅 Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("============================================================")

    overall_start = time.time()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
        )

        scrapers = [
            ("Prisma EE", scrape_prisma),
            ("Rimi Baltic", scrape_rimi),
            ("Selver EE", scrape_selver),
            ("Maxima EE", scrape_maxima),
            ("Lidl EE", scrape_lidl),
            ("Coop EE", scrape_coop),
            ("Grossi Toidukaubad", scrape_grossi),
        ]

        summary = []
        for name, func in scrapers:
            start_t = time.time()
            try:
                await func(context)
                duration = round(time.time() - start_t, 2)
                summary.append({"store": name, "status": "SUCCESS", "duration": f"{duration}s"})
            except Exception as err:
                duration = round(time.time() - start_t, 2)
                summary.append({"store": name, "status": f"FAILED ({err})", "duration": f"{duration}s"})

        await browser.close()

    total_duration = round(time.time() - overall_start, 2)

    print("\n" + "=" * 60)
    print("📊 ALL-GROCERY SCRAPE COMPLETE SUMMARY")
    print("=" * 60)
    for res in summary:
        print(f"  • {res['store']:<20} | Status: {res['status']:<15} | Took: {res['duration']}")
    print("-" * 60)
    print(f"🏁 Total Execution Time: {total_duration} seconds")
    print("============================================================\n")


if __name__ == "__main__":
    asyncio.run(main())