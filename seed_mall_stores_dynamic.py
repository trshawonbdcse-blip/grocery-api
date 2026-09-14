import os
import re
import json
import psycopg2
import httpx
from bs4 import BeautifulSoup
from dynamic_outlet_engine import fetch_malls_by_radius

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/postgres")

def init_db():
    print("🔌 Connecting to PostgreSQL & Initializing Schema...")
    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS public.shopping_malls (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) UNIQUE NOT NULL,
            latitude NUMERIC(10, 6) NOT NULL,
            longitude NUMERIC(10, 6) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS public.mall_stores (
            id SERIAL PRIMARY KEY,
            mall_id INT REFERENCES public.shopping_malls(id) ON DELETE CASCADE,
            store_name VARCHAR(255) NOT NULL,
            category VARCHAR(100) DEFAULT 'Retail',
            floor_level VARCHAR(50) DEFAULT '1st Floor',
            max_discount_pct INT DEFAULT 50,
            website_url TEXT,
            UNIQUE(mall_id, store_name)
        );

        CREATE TABLE IF NOT EXISTS public.store_products (
            id SERIAL PRIMARY KEY,
            store_id INT REFERENCES public.mall_stores(id) ON DELETE CASCADE,
            sku VARCHAR(100) UNIQUE NOT NULL,
            title VARCHAR(255) NOT NULL,
            regular_price NUMERIC(10, 2) NOT NULL,
            discount_price NUMERIC(10, 2) NOT NULL,
            discount_pct INT GENERATED ALWAYS AS (ROUND(((regular_price - discount_price) / regular_price) * 100)) STORED,
            stock_count INT DEFAULT 5,
            stock_status_label VARCHAR(50) DEFAULT 'In Stock',
            image_url TEXT,
            product_url TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            last_scraped_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)
    conn.commit()
    cursor.close()
    conn.close()
    print("✅ Schema initialized.")

def extract_stores_from_json_state(soup: BeautifulSoup) -> list:
    """Extracts tenant listings embedded inside frontend JSON state objects (__NEXT_DATA__, __NUXT__, JSON-LD)."""
    extracted = []
    
    # 1. Inspect Next.js / Nuxt.js hydration payloads
    for script in soup.find_all("script"):
        script_id = script.get("id", "")
        content = script.string or ""
        
        if script_id in ["__NEXT_DATA__", "__NUXT__"] or "window.__INITIAL_STATE__" in content:
            # Extract store names using regex search across state string
            matches = re.findall(r'"title"\s*:\s*"([^"]+)"|"name"\s*:\s*"([^"]+)"|"store_name"\s*:\s*"([^"]+)"', content)
            for m in matches:
                name = next((item for item in m if item), "").strip()
                if 2 < len(name) < 35 and not any(w in name.lower() for w in ["avatud", "keskus", "kaardid", "cookies", "otsing"]):
                    extracted.append(name)

    # 2. Extract Schema.org LocalBusiness / ShoppingCenter microdata
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict):
                    departments = item.get("department", []) or item.get("containsPlace", [])
                    for dept in departments:
                        if isinstance(dept, dict) and dept.get("name"):
                            extracted.append(dept["name"])
        except Exception:
            continue

    return extracted

def scrape_mall_stores_dynamic(mall_name: str) -> list:
    """Applies multi-strategy dynamic crawling to resolve JavaScript-heavy mall directories."""
    clean_brand = re.sub(r"(?i)\b(keskus|shopping|mall|turg)\b", "", mall_name).strip()
    slug = re.sub(r"[^\w]", "", clean_brand).lower()
    
    candidate_urls = [
        f"https://www.{slug}keskus.ee/et/kauplused",
        f"https://www.{slug}keskus.ee/kauplused",
        f"https://www.{slug}.ee/et/kauplused",
        f"https://www.{slug}.ee/kauplused",
        f"https://www.{slug}.ee/shops",
        f"https://www.{slug}.ee/en/shops"
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "et-EE,et;q=0.9,en-US;q=0.8,en;q=0.7"
    }

    discovered_names = []

    with httpx.Client(follow_redirects=True, timeout=8.0, headers=headers) as client:
        for url in candidate_urls:
            try:
                res = client.get(url)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")

                    # Strategy A: Extract state scripts (CSR SPA payload)
                    json_stores = extract_stores_from_json_state(soup)
                    discovered_names.extend(json_stores)

                    # Strategy B: Broad DOM query matching directory item patterns
                    selectors = [
                        "a[href*='kauplus']", "a[href*='shop']", "a[href*='tenant']",
                        "div[class*='shop']", "div[class*='tenant']", "div[class*='store']",
                        ".directory-item", ".shop-card", ".tenant-card", "h3", "h4"
                    ]
                    
                    for sel in selectors:
                        for el in soup.select(sel):
                            text = el.get_text(strip=True)
                            if 2 < len(text) < 35 and not any(w in text.lower() for w in ["avatud", "kontakt", "otsi", "kaardid", "liitu", "uudised", "üritused", "menüü"]):
                                discovered_names.append(text)

                    if len(discovered_names) > 0:
                        break
            except Exception:
                continue

    # Clean duplicates and normalize results
    unique_stores = []
    seen = set()
    for name in discovered_names:
        norm = name.strip()
        if norm.lower() not in seen and len(norm) > 2:
            seen.add(norm.lower())
            unique_stores.append({"name": norm, "category": "Retail", "website": ""})

    return unique_stores

def seed_malls_and_stores_dynamically():
    init_db()
    
    print("🌐 Discovering physical malls dynamically...")
    malls = fetch_malls_by_radius(59.4365, 24.7532, 10.0)
    
    if not malls:
        print("❌ No malls found.")
        return

    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor()

    for mall in malls:
        print(f"\n🏢 Processing Mall: {mall['name']}...")
        cursor.execute("""
            INSERT INTO public.shopping_malls (name, latitude, longitude)
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO UPDATE 
            SET latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude
            RETURNING id;
        """, (mall["name"], mall["lat"], mall["lon"]))
        mall_id = cursor.fetchone()[0]

        discovered_stores = scrape_mall_stores_dynamic(mall["name"])
        print(f"   Discovered {len(discovered_stores)} dynamic stores for {mall['name']}.")

        for store in discovered_stores:
            cursor.execute("""
                INSERT INTO public.mall_stores (mall_id, store_name, category, website_url)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (mall_id, store_name) DO UPDATE 
                SET website_url = COALESCE(EXCLUDED.website_url, public.mall_stores.website_url);
            """, (mall_id, store["name"], store["category"], store["website"]))

    conn.commit()
    cursor.close()
    conn.close()
    print("\n✅ Multi-strategy dynamic seeding finished!")

if __name__ == "__main__":
    seed_malls_and_stores_dynamically()