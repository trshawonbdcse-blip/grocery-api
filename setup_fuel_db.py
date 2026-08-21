import os
import json
import ssl
import urllib.request
import urllib.parse
import psycopg2

DB_URL = os.getenv("DATABASE_URL")

if not DB_URL:
    raise ValueError("DATABASE_URL environment variable is missing!")

# Disable macOS local SSL verification requirements
SSL_CTX = ssl._create_unverified_context()

def get_db_connection():
    return psycopg2.connect(DB_URL)

def init_tables():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS fuel_stations (
            id SERIAL PRIMARY KEY,
            chain_name VARCHAR(50) NOT NULL,
            station_name VARCHAR(100) NOT NULL,
            latitude DOUBLE PRECISION NOT NULL,
            longitude DOUBLE PRECISION NOT NULL,
            address VARCHAR(255),
            osm_id BIGINT UNIQUE
        );

        CREATE TABLE IF NOT EXISTS fuel_prices (
            id SERIAL PRIMARY KEY,
            station_id INT REFERENCES fuel_stations(id) ON DELETE CASCADE,
            fuel_type VARCHAR(10) NOT NULL, -- '95', '98', 'Diesel', 'LPG'
            price_per_liter NUMERIC(4,3) NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(station_id, fuel_type)
        );
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Fuel database tables created successfully.")

def seed_fallback_stations():
    print("📌 Injecting baseline Tallinn fuel stations...")
    conn = get_db_connection()
    cur = conn.cursor()

    FALLBACK = [
        ("Neste", "Neste Kadaka Express", 59.4072, 24.6625, "Kadaka tee 60, Tallinn", 10001),
        ("Circle K", "Circle K Mustamäe", 59.4085, 24.6712, "A. H. Tammsaare tee 116, Tallinn", 10002),
        ("Olerex", "Olerex Kristiine (LPG)", 59.4211, 24.7208, "Sõpruse pst 31, Tallinn", 10003),
        ("Alexela", "Alexela Sikupilli (LPG)", 59.4278, 24.7812, "Tartu mnt 87, Tallinn", 10004),
        ("Terminal", "Terminal Mustamäe", 59.4012, 24.6543, "Paldiski mnt 98, Tallinn", 10005),
        ("Alexela", "Alexela Õismäe (LPG)", 59.4180, 24.6430, "Ehitajate tee 114c, Tallinn", 10006),
        ("Circle K", "Circle K Sikupilli", 59.4265, 24.7780, "Tartu mnt 80, Tallinn", 10007),
        ("Neste", "Neste Ülemiste", 59.4195, 24.7910, "Suur-Sõjamäe 2, Tallinn", 10008)
    ]

    for chain, name, lat, lng, addr, fid in FALLBACK:
        cur.execute("""
            INSERT INTO fuel_stations (chain_name, station_name, latitude, longitude, address, osm_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (osm_id) DO NOTHING;
        """, (chain, name, lat, lng, addr, fid))

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Baseline Tallinn gas stations successfully added!")

def discover_and_seed_stations():
    print("\n🌐 Querying OpenStreetMap mirror for full Tallinn coverage...")
    
    query_str = """[out:json][timeout:25];(node["amenity"="fuel"](59.32,24.50,59.55,24.95););out body;"""
    
    # Overpass public mirrors avoiding 406 restrictions
    endpoints = [
        "https://overpass.kumi.systems/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter"
    ]

    headers = {
        "User-Agent": "TallinnGroceryApp/1.0 (contact@tallinn-grocery-app.ee)",
        "Referer": "https://www.openstreetmap.org/",
        "Accept": "*/*"
    }

    elements = []
    for ep in endpoints:
        try:
            url = f"{ep}?data={urllib.parse.quote(query_str)}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
                elements = data.get("elements", [])
                if elements:
                    print(f"📍 Connected to {ep}! Captured {len(elements)} stations.")
                    break
        except Exception as err:
            print(f"  ⚠️ Warning: Mirror {ep} failed: {err}")
            continue

    if not elements:
        print("⚠️ OSM mirrors unavailable. Proceeding with baseline stations.")
        return

    conn = get_db_connection()
    cur = conn.cursor()

    inserted_count = 0
    for el in elements:
        osm_id = el.get("id")
        tags = el.get("tags", {})
        lat = el.get("lat")
        lon = el.get("lon")

        if not lat or not lon:
            continue

        brand = tags.get("brand") or tags.get("operator") or tags.get("name") or "Tankla"
        station_name = tags.get("name") or f"{brand} Tallinn"
        street = tags.get("addr:street", "")
        housenumber = tags.get("addr:housenumber", "")
        address = f"{street} {housenumber}".strip() if street else "Tallinn, Estonia"

        cur.execute("""
            INSERT INTO fuel_stations (chain_name, station_name, latitude, longitude, address, osm_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (osm_id) DO UPDATE 
            SET chain_name = EXCLUDED.chain_name,
                station_name = EXCLUDED.station_name,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                address = EXCLUDED.address;
        """, (brand, station_name, lat, lon, address, osm_id))

        inserted_count += 1

    conn.commit()
    cur.close()
    conn.close()

    print(f"✅ Successfully inserted/updated {inserted_count} OSM stations in PostgreSQL!")

if __name__ == "__main__":
    init_tables()
    seed_fallback_stations()
    discover_and_seed_stations()
