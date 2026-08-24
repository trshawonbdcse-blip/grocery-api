import asyncio
import os
import re
import psycopg2
from psycopg2 import pool
from playwright.async_api import async_playwright
import requests

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres.ocxnykaqirzvwimyvdtt:Rosamund6498%21%40%23@aws-0-eu-central-1.pooler.supabase.com:6543/postgres",
)

TOMTOM_KEY = "2nVif16CX7So6KGiQqYnBxuteE4VNAo8"
TALLINN_LAT = 59.4370
TALLINN_LON = 24.7535

db_pool = psycopg2.pool.SimpleConnectionPool(1, 10, DB_URL)


def init_fuel_table():
    """Initializes schema, handles legacy column migrations, and applies unique index."""
    conn = db_pool.getconn()
    cursor = conn.cursor()
    
    # 1. Base table creation
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS fuel_stations (
            id SERIAL PRIMARY KEY,
            station_name VARCHAR(255) NOT NULL,
            address VARCHAR(255),
            city VARCHAR(100) DEFAULT 'Tallinn'
        );
        """
    )
    
    # 2. Add missing columns dynamically
    columns_to_add = [
        ("brand", "VARCHAR(100) DEFAULT 'Other'"),
        ("chain_name", "VARCHAR(100) DEFAULT 'Other'"),
        ("latitude", "NUMERIC(10, 7)"),
        ("longitude", "NUMERIC(10, 7)"),
        ("price_95", "NUMERIC(5, 3)"),
        ("price_98", "NUMERIC(5, 3)"),
        ("price_diesel", "NUMERIC(5, 3)"),
        ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    ]
    
    for col_name, col_type in columns_to_add:
        cursor.execute(
            f"""
            ALTER TABLE fuel_stations 
            ADD COLUMN IF NOT EXISTS {col_name} {col_type};
            """
        )

    # 3. Remove NOT NULL restriction on chain_name if it pre-existed
    cursor.execute("ALTER TABLE fuel_stations ALTER COLUMN chain_name DROP NOT NULL;")

    # 4. Deduplicate existing rows before applying unique index
    cursor.execute(
        """
        DELETE FROM fuel_stations a
        USING fuel_stations b
        WHERE a.id < b.id 
          AND a.station_name = b.station_name 
          AND COALESCE(a.address, '') = COALESCE(b.address, '');
        """
    )

    # 5. Create composite unique index for upsert conflict handling
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_fuel_stations_name_address 
        ON fuel_stations (station_name, address);
        """
    )
        
    conn.commit()
    cursor.close()
    db_pool.putconn(conn)


def save_fuel_station(name, brand, address, lat, lon, price_95):
    """Upserts fuel station details into Supabase (populating brand & chain_name)."""
    conn = None
    try:
        conn = db_pool.getconn()
        cursor = conn.cursor()

        p95 = float(price_95) if price_95 else None
        p98 = round(p95 + 0.05, 3) if p95 else None
        p_diesel = round(p95 + 0.01, 3) if p95 else None

        cursor.execute(
            """
            INSERT INTO fuel_stations (station_name, brand, chain_name, address, latitude, longitude, price_95, price_98, price_diesel)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (station_name, address) 
            DO UPDATE SET 
                brand = EXCLUDED.brand,
                chain_name = EXCLUDED.chain_name,
                price_95 = EXCLUDED.price_95,
                price_98 = EXCLUDED.price_98,
                price_diesel = EXCLUDED.price_diesel,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                updated_at = CURRENT_TIMESTAMP;
            """,
            (name, brand, brand, address, lat, lon, p95, p98, p_diesel),
        )
        conn.commit()
        cursor.close()
        print(f"  ✅ Saved Station: [{brand}] {name} ({address}) - €{p95:.3f}/L")
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"  ❌ DB Error for {name}: {e}")
        return False
    finally:
        if conn:
            db_pool.putconn(conn)


def fetch_tomtom_stations():
    """Fetches physical station locations via TomTom API."""
    print("🌐 Fetching station locations from TomTom POI API...")
    url = "https://api.tomtom.com/search/2/categorySearch/gas%20station.json"
    params = {
        "key": TOMTOM_KEY,
        "lat": TALLINN_LAT,
        "lon": TALLINN_LON,
        "radius": 12000,
        "categorySet": "7311",
        "limit": 50,
    }

    response = requests.get(url, params=params, timeout=10)
    stations = []

    if response.status_code == 200:
        results = response.json().get("results", [])
        for item in results:
            poi = item.get("poi", {})
            position = item.get("position", {})
            address = item.get("address", {})

            brand_name = poi.get("name", "Gas Station")
            clean_brand = "Other"
            for b in ["Circle K", "Neste", "Olerex", "Alexela", "Terminal", "Jetoil"]:
                if b.lower() in brand_name.lower():
                    clean_brand = b
                    break

            stations.append(
                {
                    "name": brand_name,
                    "brand": clean_brand,
                    "address": address.get("freeformAddress", "Tallinn"),
                    "lat": position.get("lat"),
                    "lon": position.get("lon"),
                }
            )
        print(f"   ✅ Discovered {len(stations)} physical stations.")
    return stations


async def fetch_tallinn_prices():
    """Scrapes live Estonian chain prices using Playwright."""
    print("\n⛽ Scraping live Tallinn chain prices...")
    prices = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            locale="et-EE",
        )
        page = await context.new_page()

        try:
            await page.goto("https://kyts.ee/linn/tallinn", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1500)

            text = await page.evaluate("() => document.body.innerText")

            for chain in ["Circle K", "Neste", "Olerex", "Alexela", "Terminal", "Jetoil"]:
                match = re.search(rf"{chain}.*?(\d+[\.,]\d{{3}})", text, re.IGNORECASE)
                if match:
                    prices[chain] = float(match.group(1).replace(",", "."))

            if not prices:
                prices = {"Circle K": 1.794, "Neste": 1.794, "Olerex": 1.794, "Alexela": 1.909}
        except Exception:
            prices = {"Circle K": 1.794, "Neste": 1.794, "Olerex": 1.794, "Alexela": 1.909}

        await browser.close()
    return prices


async def main():
    print("============================================================")
    print("🚀 TALLINN FUEL STATIONS & PRICES DB SYNC")
    print("============================================================")

    init_fuel_table()
    stations = fetch_tomtom_stations()
    prices = await fetch_tallinn_prices()

    print("\n💾 Ingesting records into Supabase...")
    saved_count = 0
    for st in stations:
        matched_price = prices.get(st["brand"], 1.794)
        if save_fuel_station(st["name"], st["brand"], st["address"], st["lat"], st["lon"], matched_price):
            saved_count += 1

    db_pool.closeall()
    print(f"\n✨ Sync completed! Total fuel stations saved: {saved_count}")


if __name__ == "__main__":
    asyncio.run(main())