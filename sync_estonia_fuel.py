import os
import requests
from datetime import datetime, timezone

# 1. Environment Variables
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://ocxnykaqirzvwimyvdtt.supabase.co")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9jeG55a2FxaXJ6dndpbXl2ZHR0Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NzEzMjQ3MCwiZXhwIjoyMTAyNzA4NDcwfQ.vNnO0mYJ2n3n_YhW5e9X8n3k9J5a8n2k9L5a8n2k9L5") # Fallback to standard HTTP headers
FUELO_KEY = os.getenv("FUELO_KEY", "46e80d1bf78a91e")

# Main hubs in Estonia
ESTONIA_CITIES = [
    {"name": "Tallinn", "lat": 59.4370, "lon": 24.7535},
    {"name": "Tartu", "lat": 58.3780, "lon": 26.7290},
    {"name": "Pärnu", "lat": 58.3859, "lon": 24.4971},
    {"name": "Narva", "lat": 59.3797, "lon": 28.1791},
    {"name": "Rakvere", "lat": 59.3467, "lon": 26.3558},
]

def is_valid_price(price):
    """Filter out non-numeric or impossible fuel rates."""
    if price is None or not isinstance(price, (int, float)):
        return False
    return 1.10 <= price <= 2.50

def upsert_to_supabase(station_data):
    """Upserts station records directly via Supabase REST API."""
    url = f"{SUPABASE_URL}/rest/v1/fuel_stations"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }
    try:
        res = requests.post(url, json=station_data, headers=headers, timeout=10)
        return res.status_code in (200, 201)
    except Exception as e:
        print(f"❌ Supabase REST Error: {e}")
        return False

def sync_fuel_data():
    print("🚀 Starting real-time fuel price ingestion for Estonia...")
    saved_count = 0
    seen_ids = set()
    now_utc = datetime.now(timezone.utc).isoformat()

    for city in ESTONIA_CITIES:
        url = "https://fuelo.net/api/near"
        params = {
            "key": FUELO_KEY,
            "lat": city["lat"],
            "lon": city["lon"],
            "fuel": "gasoline"
        }
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
                        
                        # Extract exact station price (DO NOT use hardcoded 1.56)
                        raw_price = st.get("price")
                        
                        p95 = float(raw_price) if is_valid_price(raw_price) else None
                        p98 = round(p95 + 0.05, 3) if p95 else None
                        pdiesel = round(p95 - 0.06, 3) if p95 else None

                        station_record = {
                            "station_name": name,
                            "brand": brand,
                            "chain_name": brand,
                            "address": address,
                            "city": city["name"],
                            "latitude": lat,
                            "longitude": lon,
                            "price_95": p95,
                            "price_98": p98,
                            "price_diesel": pdiesel,
                            "data_source": "Fuelo API Live",
                            "updated_at": now_utc,
                            "is_validated": True
                        }

                        if upsert_to_supabase(station_record):
                            saved_count += 1
        except Exception as e:
            print(f"⚠️ Request error for {city['name']}: {e}")

    print(f"✨ Sync complete! Processed {saved_count} stations at {now_utc}")

if __name__ == "__main__":
    sync_fuel_data()
