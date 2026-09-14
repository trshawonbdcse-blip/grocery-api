import os
import json
import re
import psycopg2
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from store_url_resolver import resolve_store_ecommerce_url

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/postgres")

def find_dynamic_sale_page(page, base_url: str) -> str:
    """Scans DOM dynamically while filtering out host traps, terms pages, blog posts, and fragment anchors."""
    try:
        links = page.eval_on_selector_all(
            "a[href]",
            """nodes => nodes.map(n => ({
                text: n.innerText.toLowerCase(),
                href: n.href
            }))"""
        )
        for link in links:
            href = link.get("href", "").strip()
            text = link.get("text", "").strip()
            href_lower = href.lower()
            
            # Skip hosting traps, terms of sale, privacy policies, blog posts, return forms, and # fragment links
            if "#" in href or any(trap in href_lower for trap in [
                "zone.ee", "veebimajutus", "domain", "account", "login", "register",
                "history", "cart", "checkout", "minu-konto", "ostukorv", "terms", 
                "tingimused", "privaatsus", "tagastus", "blogi", "uudised", "pages/",
                "help", "koti", "tarne"
            ]):
                continue

            if any(kw in text or kw in href_lower for kw in ["sooduspakkumised", "soodustused", "outlet", "sale", "kampaania", "prices"]):
                if href.startswith("http") and href != base_url:
                    return href
    except Exception:
        pass
    return base_url

def extract_products_from_dom(html_content: str, base_url: str):
    soup = BeautifulSoup(html_content, "html.parser")
    products = []
    seen_titles = set()

    # 1. Inspect Schema.org JSON-LD microdata
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict) and (item.get("@type") in ["Product", "IndividualProduct"] or "offers" in item):
                    title = item.get("name")
                    if not title or title in seen_titles:
                        continue

                    offers = item.get("offers", {})
                    if isinstance(offers, list) and offers:
                        offers = offers[0]

                    disc_price = float(offers.get("price", 0) or 0)
                    reg_price = float(offers.get("highPrice", 0) or 0)
                    if reg_price <= disc_price:
                        reg_price = round(disc_price * 1.25, 2)

                    image = item.get("image")
                    if isinstance(image, list) and image:
                        image = image[0]
                    elif isinstance(image, dict):
                        image = image.get("url", "")

                    if title and disc_price > 0:
                        seen_titles.add(title)
                        products.append({
                            "title": title.strip(),
                            "discount_price": disc_price,
                            "regular_price": reg_price,
                            "image_url": image or "",
                            "product_url": offers.get("url") or base_url
                        })
        except Exception:
            continue

    # 2. Extract DOM product cards dynamically (Expanded for React/Vue/Angular component grids)
    if not products:
        card_selectors = [
            "article", "div[class*='product']", "li[class*='product']", 
            "div[class*='item']", "a[class*='product-card']", ".product-tile",
            "div[class*='card']", "div[data-qa*='product']", "[class*='grid-item']",
            "section[class*='product']", "[class*='media-card']"
        ]
        
        for sel in card_selectors:
            cards = soup.select(sel)
            if len(cards) < 2:
                continue

            for card in cards:
                title_el = card.select_one("h2, h3, h4, .title, [class*='name'], [class*='title'], [class*='heading']")
                price_els = card.select("[class*='price'], span, strong, p")
                img_el = card.select_one("img")
                link_el = card if card.name == "a" else card.select_one("a[href]")

                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                if not title or len(title) < 3 or title in seen_titles:
                    continue

                prices = []
                for p_el in price_els:
                    text = p_el.get_text()
                    match = re.search(r"(\d+[\.,]\d{2})\s*€?", text)
                    if match:
                        try:
                            val = float(match.group(1).replace(",", "."))
                            if 0.50 <= val <= 5000:
                                prices.append(val)
                        except ValueError:
                            pass

                if prices:
                    prices = sorted(list(set(prices)))
                    disc_price = prices[0]
                    reg_price = prices[-1] if len(prices) > 1 else round(disc_price * 1.25, 2)

                    img_url = ""
                    if img_el:
                        img_url = img_el.get("src") or img_el.get("data-src") or img_el.get("srcset", "").split(" ")[0]

                    href = link_el.get("href", "") if link_el else ""
                    product_url = href if href.startswith("http") else (base_url.rstrip("/") + "/" + href.lstrip("/")) if href else base_url

                    seen_titles.add(title)
                    products.append({
                        "title": title[:200],
                        "discount_price": disc_price,
                        "regular_price": reg_price,
                        "image_url": img_url,
                        "product_url": product_url
                    })

            if len(products) >= 2:
                break

    return products

def run_universal_deal_extractor():
    if not DB_URL:
        print("❌ DATABASE_URL missing.")
        return

    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor()

    # Filter out floor numbers, layout noise, and invalid DNS target rows
    cursor.execute("""
        SELECT id, store_name, website_url 
        FROM public.mall_stores 
        WHERE store_name IS NOT NULL
          AND store_name !~* '(korrus|floor|täna|kell|lähemalt|vaata|iseteenindus|pakiautomaat)'
          AND length(store_name) BETWEEN 2 AND 35;
    """)
    stores = cursor.fetchall()

    print(f"🔄 Network-Interception Extractor active for {len(stores)} database stores...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True
        )

        for store_id, store_name, website_url in stores:
            # Explicit override for Zara to use Zara Estonia regional domain
            if "zara" in store_name.lower():
                target_url = "https://www.zara.com/ee/"
            else:
                target_url = website_url or resolve_store_ecommerce_url(store_name)

            if not target_url or not target_url.startswith("http") or "zone.ee" in target_url:
                target_url = resolve_store_ecommerce_url(store_name)

            if not target_url or not target_url.startswith("http"):
                continue

            print(f"🌐 Crawling target: {target_url} ('{store_name}')...")
            
            page = context.new_page()
            api_captured_products = []

            # Background Listener: Intercepts JSON responses for client-rendered SPA apps (Zara, Bershka, Kaubamaja)
            def handle_response(response):
                try:
                    if "application/json" in response.headers.get("content-type", ""):
                        data = response.json()
                        str_data = json.dumps(data)
                        matches = re.findall(r'"name"\s*:\s*"([^"]+)"[^{}]*?"price"\s*:\s*(\d+)', str_data)
                        for m_title, m_price in matches:
                            price_val = float(m_price) / (100 if float(m_price) > 5000 else 1)
                            if 1.0 <= price_val <= 3000 and len(m_title) > 2:
                                api_captured_products.append({
                                    "title": m_title,
                                    "discount_price": price_val,
                                    "regular_price": round(price_val * 1.25, 2),
                                    "image_url": "",
                                    "product_url": target_url
                                })
                except Exception:
                    pass

            page.on("response", handle_response)

            try:
                response = page.goto(target_url, timeout=16000, wait_until="domcontentloaded")
                if response and response.status < 400:
                    sale_url = find_dynamic_sale_page(page, target_url)
                    if sale_url and sale_url != target_url and not sale_url.endswith("#"):
                        print(f"  └─ 🎯 Found deep sale page dynamically: {sale_url}")
                        page.goto(sale_url, timeout=16000, wait_until="domcontentloaded")

                    page.wait_for_timeout(2500)

                    # Multi-stage incremental scrolling for SPA infinite lists
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
                    page.wait_for_timeout(800)
                    page.evaluate("window.scrollTo(0, (document.body.scrollHeight / 3) * 2)")
                    page.wait_for_timeout(800)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1200)

                    rendered_html = page.content()
                    extracted_deals = extract_products_from_dom(rendered_html, page.url)
                    
                    # Merge network-intercepted API deals if HTML card parsing yielded 0
                    if not extracted_deals and api_captured_products:
                        extracted_deals = api_captured_products[:30]
                        print(f"  └─ ⚡ Intercepted {len(extracted_deals)} API background products")

                    saved_count = 0
                    cursor.execute("UPDATE public.mall_stores SET website_url = %s WHERE id = %s;", (page.url, store_id))

                    for p_data in extracted_deals:
                        sku = f"AUTO-{abs(hash(p_data['title'])) % 10000000}"
                        cursor.execute("""
                            INSERT INTO public.store_products 
                                (store_id, sku, title, regular_price, discount_price, stock_count, stock_status_label, image_url, product_url, is_active)
                            VALUES (%s, %s, %s, %s, %s, 5, 'In Stock', %s, %s, true)
                            ON CONFLICT (sku) DO UPDATE SET 
                                discount_price = EXCLUDED.discount_price,
                                regular_price = EXCLUDED.regular_price,
                                product_url = EXCLUDED.product_url,
                                image_url = EXCLUDED.image_url;
                        """, (store_id, sku, p_data["title"], p_data["regular_price"], p_data["discount_price"], p_data["image_url"], p_data["product_url"]))
                        saved_count += 1

                    conn.commit()
                    if saved_count > 0:
                        print(f"  └─ ✅ Extracted {saved_count} deals dynamically for {store_name}")

            except Exception as e:
                conn.rollback()
                print(f"  └─ ⚠️ Skipping {store_name}: {e}")
            finally:
                page.close()

        browser.close()

    cursor.close()
    conn.close()

if __name__ == "__main__":
    run_universal_deal_extractor()