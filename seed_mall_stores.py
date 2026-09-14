import os
import psycopg2
import httpx
from dynamic_outlet_engine import fetch_malls_by_radius

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/postgres")

def init_db():
    print("🔌 Initializing PostgreSQL database schema...")
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
    print("✅ Database schema created successfully.")

def fetch_stores_inside_mall(mall_lat: float, mall_lon: float) -> list:
    """Queries OpenStreetMap Overpass API for shop nodes near the mall coordinates."""
    bbox_size = 0.004  # ~400m radius bounding box
    south, north = mall_lat - bbox_size, mall_lat + bbox_size
    west, east = mall_lon - bbox_size, mall_lon + bbox_size
    
    query = f"""
    [out:json][timeout:10];
    (
      nwr["shop"]({south:.4f},{west:.4f},{north:.4f},{east:.4f});
    );
    out tags;
    """
    headers = {"User-Agent": "TallinnOutletEngine/1.0"}
    try:
        res = httpx.post("https://overpass-api.de/api/interpreter", data={"data": query}, headers=headers, timeout=10.0)
        if res.status_code == 200:
            elements = res.json().get("elements", [])
            stores = []
            for el in elements:
                tags = el.get("tags", {})
                name = tags.get("name")
                shop_type = tags.get("shop", "Retail").capitalize()
                website = tags.get("website") or tags.get("url") or ""
                if name:
                    stores.append({"name": name, "category": shop_type, "website": website})
            return stores
    except Exception:
        pass
    return []

def seed_malls_and_stores_dynamically():
    init_db()
    
    print("🌐 Querying physical malls dynamically via OpenStreetMap...")
    malls = fetch_malls_by_radius(59.4365, 24.7532, 10.0)
    
    if not malls:
        print("❌ No malls found via OSM.")
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

        discovered_stores = fetch_stores_inside_mall(mall["lat"], mall["lon"])
        print(f"   Discovered {len(discovered_stores)} shops inside {mall['name']}.")

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
    print("\n✅ Dynamic seeding completed successfully.")

if __name__ == "__main__":
    seed_malls_and_stores_dynamically()