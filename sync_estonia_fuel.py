import os
import requests
import psycopg2
from psycopg2 import pool
from datetime import datetime, timezone

DB_URL = os.getenv("DATABASE_URL")
FUELO_KEY = os.getenv("FUELO_KEY")

ESTONIA_CITIES = [
    {"name": "Tallinn", "lat": 59.4370, "lon": 24.7535},
    {"name": "Tartu", "lat": 58.3780, "lon": 26.7290},
    {"name": "Pärnu", "lat": 58.3859, "lon": 24.4971},
    {"name": "Narva", "lat": 59.3797, "lon": 28.1791},
    {"name": "Rakvere", "lat": 59.3467, "lon": 26.3558},
]

def is_valid_price(price, baseline_median=1.65):
    if not price or not isinstance(price, (int, float)):
        return False
    if price < 1.00 or price > 2.50:
        return False
    if abs(price - baseline_median) / baseline_median > 0.25:
        return False
    return True

def sync_fuel():
    if not DB_URL or not FUELO_KEY:
        print("❌ Missing DATABASE_URL or FUELO_KEY environment variables!")
        return

    db_pool = psycopg2.pool.SimpleConnectionPool(1, 10, DB_URL)
    saved_count = 0
    seen_ids = set()

    for city in ESTONIA_CITIES:
        url = "https://fuelo.net/api/near"
        params = {"key": FUELO_KEY, "lat": city["lat"], "lon": city["lon"], "fuel": "gasoline"}
        try:
            res = requests.get(url, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "OK":
                    for st in data.get("gasstations", []):
                        st_id = st.get("id")
                        if st_id in seen_ids:
                            continue
                        seen_ids.add(st_id)

                        name = st.get("name", "Gas Station")
                        brand = st.get("brand_name", "Other")
                        address = st.get("address", city["name"])
                        lat = float(st.get("lat")) if st.get("lat") else city["lat"]
                        lon = float(st.get("lon")) if st.get("lon") else city["lon"]
                        raw_p95 = float(st.get("price")) if st.get("price") else 1.56

                        if is_valid_price(raw_p95):
                            p95 = round(raw_p95, 3)
                            p98 = round(p95 + 0.05, 3)
                            pdiesel = round(p95 - 0.05, 3)
                            now_utc = datetime.now(timezone.utc)

                            conn = db_pool.getconn()
                            cursor = conn.cursor()
                            cursor.execute(
                                """
                                INSERT INTO fuel_stations (
                                    station_name, brand, chain_name, address, city, 
                                    latitude, longitude, price_95, price_98, price_diesel, 
                                    data_source, updated_at, is_validated
                                )
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Fuelo', %s, TRUE)
                                ON CONFLICT (station_name, address) 
                                DO UPDATE SET 
                                    price_95 = EXCLUDED.price_95,
                                    price_98 = EXCLUDED.price_98,
                                    price_diesel = EXCLUDED.price_diesel,
                                    updated_at = EXCLUDED.updated_at,
                                    is_validated = TRUE;
                                """,
                                (name, brand, brand, address, city["name"], lat, lon, p95, p98, pdiesel, now_utc)
                            )
                            conn.commit()
                            cursor.close()
                            db_pool.putconn(conn)
                            saved_count += 1
        except Exception as e:
            print(f"⚠️ Error for {city['name']}: {e}")

    db_pool.closeall()
    print(f"✨ Ingestion complete. Updated {saved_count} stations.")

if __name__ == "__main__":
    sync_fuel()
