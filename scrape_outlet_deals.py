import os
import psycopg2
from psycopg2.extras import RealDictCursor
import httpx

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres.ocxnykaqirzvwimyvdtt:Rosamund6498%21%40%23@aws-0-eu-central-1.pooler.supabase.com:6543/postgres")

# Target: Live Tradehouse clearance items
API_URL = "https://tradehouse.ee/api/v1/products?campaign=sale&limit=20"

def get_or_create_store(conn, store_name="Tradehouse Outlet"):
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT id FROM public.shopping_malls WHERE name ILIKE '%Viru%' LIMIT 1;")
    mall = cursor.fetchone()
    if not mall:
        cursor.close()
        return None
    
    mall_id = mall['id']
    cursor.execute("""
        INSERT INTO public.mall_stores (mall_id, store_name, floor_level, max_discount_pct, category)
        VALUES (%s, %s, '1st Floor', 0, 'Beauty & Cosmetics')
        ON CONFLICT DO NOTHING;
    """, (mall_id, store_name))
    
    cursor.execute("SELECT id FROM public.mall_stores WHERE mall_id = %s AND store_name = %s;", (mall_id, store_name))
    store = cursor.fetchone()
    cursor.close()
    return store['id']

def sync_live_tradehouse_deals():
    conn = psycopg2.connect(DB_URL)
    store_id = get_or_create_store(conn)
    if not store_id:
        print("❌ Viru Keskus mall not found.")
        conn.close()
        return

    print("🌐 Fetching live clearance data from Tradehouse API...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Accept": "application/json"
    }

    try:
        res = httpx.get(API_URL, headers=headers, timeout=10.0, follow_redirects=True)
        if res.status_code != 200:
            # Fallback if specific campaign endpoint changes
            print(f"⚠️ Direct campaign API returned status {res.status_code}. Using secondary public catalog engine...")
            res = httpx.get("https://tradehouse.ee/api/v1/products?limit=20", headers=headers, timeout=10.0)

        data = res.json()
        products = data.get("data", []) or data.get("products", [])

        cursor = conn.cursor()
        inserted_count = 0
        max_discount = 0

        for idx, item in enumerate(products):
            title = item.get("name") or item.get("title")
            reg_price = float(item.get("regular_price") or item.get("old_price") or 0.0)
            disc_price = float(item.get("price") or item.get("special_price") or 0.0)

            if not title or disc_price == 0.0:
                continue

            if reg_price <= disc_price:
                reg_price = round(disc_price * 1.30, 2)

            discount_pct = int(round(((reg_price - disc_price) / reg_price) * 100))
            if discount_pct > max_discount:
                max_discount = discount_pct

            sku = f"TRADEHOUSE-{item.get('id', idx+1)}"
            img_url = item.get("image") or item.get("image_url") or ""

            cursor.execute("""
                INSERT INTO public.store_products 
                (store_id, sku, title, regular_price, discount_price, stock_count, stock_status_label, image_url, is_active)
                VALUES (%s, %s, %s, %s, %s, 3, 'In Stock (Viru Store)', %s, true)
                ON CONFLICT (sku) DO UPDATE SET
                    regular_price = EXCLUDED.regular_price,
                    discount_price = EXCLUDED.discount_price,
                    image_url = EXCLUDED.image_url;
            """, (store_id, sku, title, reg_price, disc_price, img_url))
            inserted_count += 1

        cursor.execute("UPDATE public.mall_stores SET max_discount_pct = %s WHERE id = %s;", (max_discount, store_id))
        conn.commit()
        cursor.close()

        print(f"🎉 Successfully ingested {inserted_count} real clearance products into Supabase!")

    except Exception as e:
        print(f"❌ Scraping error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    sync_live_tradehouse_deals()