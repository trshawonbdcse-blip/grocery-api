import os
import psycopg2

# Added Supabase connection string fallback
DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres.ocxnykaqirzvwimyvdtt:Rosamund6498%21%40%23@aws-0-eu-central-1.pooler.supabase.com:6543/postgres")

def sync_deals():
    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor()

    # Dynamic lookup: find any mall with "Viru" in the title
    cursor.execute("SELECT id, name FROM public.shopping_malls WHERE name ILIKE '%Viru%' LIMIT 1;")
    mall = cursor.fetchone()

    if not mall:
        print("❌ Viru mall not found in database.")
        conn.close()
        return

    mall_id, mall_name = mall
    print(f"🔗 Linking stores to: {mall_name} ({mall_id})")

    # Insert Store tied to dynamic mall_id
    cursor.execute("""
        INSERT INTO public.mall_stores (mall_id, store_name, floor_level, max_discount_pct, category)
        VALUES (%s, 'Samsonite & Bags', '1st Floor', 50, 'Bags')
        RETURNING id;
    """, (mall_id,))
    store_id = cursor.fetchone()[0]

    # Insert Clearance Items
    products = [
        ("#BAG-8821", "Leather Crossbody Bag (Black)", 120.00, 60.00, 3, "3 units available in Viru Store"),
        ("#BAG-8822", "Lightweight Spinner Suitcase 55cm", 180.00, 108.00, 1, "In Stock (Floor 1 Display)"),
        ("#BAG-8823", "Women's Daily Tote Bag (Tan)", 95.00, 66.50, 1, "Last Unit on Display")
    ]

    for sku, title, reg_price, disc_price, stock, label in products:
        cursor.execute("""
            INSERT INTO public.store_products 
            (store_id, sku, title, regular_price, discount_price, stock_count, stock_status_label, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, true)
            ON CONFLICT (sku) DO UPDATE SET
                store_id = EXCLUDED.store_id,
                regular_price = EXCLUDED.regular_price,
                discount_price = EXCLUDED.discount_price,
                stock_count = EXCLUDED.stock_count;
        """, (store_id, sku, title, reg_price, disc_price, stock, label))

    conn.commit()
    cursor.close()
    conn.close()
    print("🎉 Successfully populated store deals!")

if __name__ == "__main__":
    sync_deals()