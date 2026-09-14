import os
import requests
import psycopg2

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres.ocxnykaqirzvwimyvdtt:Rosamund6498%21%40%23@aws-0-eu-central-1.pooler.supabase.com:6543/postgres")

# Multiple dynamic OpenStreetMap Overpass servers
OVERPASS_MIRRORS = [
    "https://overpass.khtml.org/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
]

# Query OpenStreetMap dynamically for all shopping malls in Tallinn
OVERPASS_QUERY = """
[out:json][timeout:25];
area["name"="Tallinn"]->.searchArea;
(
  node["shop"="mall"](area.searchArea);
  way["shop"="mall"](area.searchArea);
  relation["shop"="mall"](area.searchArea);
);
out center;
"""

def seed_malls_dynamically():
    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor()

    # 1. Ensure DB tables and constraints exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS public.shopping_malls (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(100) NOT NULL UNIQUE,
            city_zone VARCHAR(100) DEFAULT 'Tallinn',
            latitude NUMERIC(9,6) NOT NULL,
            longitude NUMERIC(9,6) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS public.mall_stores (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            mall_id UUID REFERENCES public.shopping_malls(id) ON DELETE CASCADE,
            store_name VARCHAR(100) NOT NULL,
            floor_level VARCHAR(50) DEFAULT '1st Floor',
            max_discount_pct INT DEFAULT 0,
            category VARCHAR(50) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS public.store_products (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id UUID REFERENCES public.mall_stores(id) ON DELETE CASCADE,
            sku VARCHAR(50) UNIQUE NOT NULL,
            title VARCHAR(255) NOT NULL,
            regular_price NUMERIC(6,2) NOT NULL,
            discount_price NUMERIC(6,2) NOT NULL,
            discount_pct INT GENERATED ALWAYS AS (
                ROUND(((regular_price - discount_price) / regular_price) * 100)
            ) STORED,
            stock_count INT DEFAULT 1,
            stock_status_label VARCHAR(100) DEFAULT 'In Stock',
            image_url TEXT,
            is_active BOOLEAN DEFAULT true,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)

    print("🌐 Querying live OpenStreetMap API for Tallinn shopping complexes...")
    
    fetched_elements = []
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

    # Iterate over mirrors to fetch live data
    for mirror_url in OVERPASS_MIRRORS:
        try:
            print(f"📡 Trying server: {mirror_url}")
            res = requests.post(mirror_url, data={'data': OVERPASS_QUERY}, headers=headers, timeout=30)
            if res.status_code == 200:
                fetched_elements = res.json().get('elements', [])
                if fetched_elements:
                    print(f"✅ Success! Received live data from {mirror_url}")
                    break
        except Exception as e:
            print(f"⚠️ Server {mirror_url} unavailable or timed out, trying next mirror...")

    if not fetched_elements:
        print("❌ Could not connect to any OpenStreetMap mirror. Check your local internet or proxy connection.")
        return

    count = 0
    for el in fetched_elements:
        tags = el.get('tags', {})
        name = tags.get('name')
        
        # Get lat/lon coordinates dynamically from the node/way center
        lat = el.get('lat') or el.get('center', {}).get('lat')
        lon = el.get('lon') or el.get('center', {}).get('lon')

        if name and lat and lon:
            cursor.execute("""
                INSERT INTO public.shopping_malls (name, latitude, longitude, city_zone)
                VALUES (%s, %s, %s, 'Tallinn')
                ON CONFLICT (name) DO NOTHING;
            """, (name, lat, lon))
            count += 1

    conn.commit()
    cursor.close()
    conn.close()
    print(f"🎉 Successfully inserted {count} dynamic shopping malls directly into Supabase!")

if __name__ == "__main__":
    seed_malls_dynamically()