import os
import math
import psycopg2
from psycopg2.extras import RealDictCursor

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres.ocxnykaqirzvwimyvdtt:Rosamund6498%21%40%23@aws-0-eu-central-1.pooler.supabase.com:6543/postgres")

def haversine_km(lat1, lon1, lat2, lon2):
    """Calculates distance between two GPS coordinates in kilometers."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 1)

def get_outlet_data(user_lat=59.4365, user_lon=24.7532, radius_km=10.0):
    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # Fetch all malls
    cursor.execute("SELECT id, name, city_zone, latitude, longitude FROM public.shopping_malls;")
    malls = cursor.fetchall()

    result = []
    for mall in malls:
        dist = haversine_km(user_lat, user_lon, float(mall['latitude']), float(mall['longitude']))
        if dist <= radius_km:
            # Fetch stores inside this mall
            cursor.execute("""
                SELECT s.id, s.store_name, s.floor_level, s.max_discount_pct, s.category,
                       COUNT(p.id) as item_count
                FROM public.mall_stores s
                LEFT JOIN public.store_products p ON p.store_id = s.id AND p.is_active = true
                WHERE s.mall_id = %s
                GROUP BY s.id;
            """, (mall['id'],))
            stores = cursor.fetchall()

            result.append({
                "mall_id": mall['id'],
                "name": mall['name'],
                "distance_km": dist,
                "distance_label": f"{dist} km",
                "stores": stores
            })

    cursor.close()
    conn.close()

    # Sort malls by nearest distance
    result.sort(key=lambda x: x['distance_km'])
    return result

if __name__ == "__main__":
    # Quick terminal test (Default coordinates set to Viru Keskus)
    data = get_outlet_data(59.4365, 24.7532)
    print(f"✅ Found {len(data)} nearby shopping complexes.")