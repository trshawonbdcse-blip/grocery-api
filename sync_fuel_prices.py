import os
import psycopg2

DB_URL = os.getenv("DATABASE_URL")

if not DB_URL:
    raise ValueError("DATABASE_URL environment variable is missing!")

# Current market rates in Estonia
CHAIN_PRICES = {
    "Neste": {"95": 1.710, "98": 1.770, "Diesel": 1.830},
    "Circle K": {"95": 1.714, "98": 1.840, "Diesel": 1.830, "LPG": 0.958},
    "Olerex": {"95": 1.729, "98": 1.794, "Diesel": 1.834, "LPG": 0.978},
    "Alexela": {"95": 1.719, "98": 1.769, "Diesel": 1.824, "LPG": 0.949},
    "Terminal": {"95": 1.709, "98": 1.759, "Diesel": 1.814, "LPG": 0.939}
}

DEFAULT_PRICES = {"95": 1.719, "98": 1.779, "Diesel": 1.829, "LPG": 0.959}

def sync_prices():
    print("\n🚀 Ingesting prices into fuel_prices table...")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    cur.execute("SELECT id, chain_name FROM fuel_stations;")
    stations = cur.fetchall()

    updated_count = 0
    for st_id, chain in stations:
        # Match chain prices or default to base rate
        prices = CHAIN_PRICES.get(chain, DEFAULT_PRICES)
        for f_type, price in prices.items():
            cur.execute("""
                INSERT INTO fuel_prices (station_id, fuel_type, price_per_liter, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (station_id, fuel_type) DO UPDATE
                SET price_per_liter = EXCLUDED.price_per_liter,
                    updated_at = NOW();
            """, (st_id, f_type, price))
            updated_count += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ Successfully updated {updated_count} fuel price entries in PostgreSQL!")

if __name__ == "__main__":
    sync_prices()
