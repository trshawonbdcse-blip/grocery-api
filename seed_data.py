import os
import psycopg2

DB_URL = os.getenv("DATABASE_URL")

SAMPLE_PRODUCTS = [
    # Dairy & Eggs
    ("Alma Piim 2.5% 1L", "Dairy & Eggs", "Maxima EE", 0.79),
    ("Rimi Piim 2.5% 1L", "Dairy & Eggs", "Rimi Baltic", 0.85),
    ("Selver Piim 2.5% 1L", "Dairy & Eggs", "Selver", 0.89),
    ("Tere Või 82% 200g", "Dairy & Eggs", "Maxima EE", 2.19),
    ("Rimi Või 82% 200g", "Dairy & Eggs", "Rimi Baltic", 2.29),
    ("Selver Või 82% 200g", "Dairy & Eggs", "Selver", 2.49),
    ("Muna L 10tk", "Dairy & Eggs", "Maxima EE", 1.89),
    ("Muna L 10tk", "Dairy & Eggs", "Rimi Baltic", 1.99),
    ("Muna L 10tk", "Dairy & Eggs", "Selver", 2.09),

    # Bakery
    ("Eesti Pagar Formileib 600g", "Bakery", "Maxima EE", 0.95),
    ("Eesti Pagar Formileib 600g", "Bakery", "Rimi Baltic", 0.99),
    ("Eesti Pagar Formileib 600g", "Bakery", "Selver", 1.15),
    ("Fazer Kodusai 500g", "Bakery", "Maxima EE", 1.05),
    ("Fazer Kodusai 500g", "Bakery", "Rimi Baltic", 1.12),
    ("Fazer Kodusai 500g", "Bakery", "Selver", 1.20),

    # Fruits & Vegetables
    ("Õun Jonagold 1kg", "Fruits & Vegetables", "Maxima EE", 1.29),
    ("Õun Jonagold 1kg", "Fruits & Vegetables", "Rimi Baltic", 1.39),
    ("Õun Jonagold 1kg", "Fruits & Vegetables", "Selver", 1.49),
    ("Banaan 1kg", "Fruits & Vegetables", "Maxima EE", 1.19),
    ("Banaan 1kg", "Fruits & Vegetables", "Rimi Baltic", 1.25),
    ("Banaan 1kg", "Fruits & Vegetables", "Selver", 1.29),
]

def seed_database():
    if not DB_URL:
        print("❌ Error: DATABASE_URL environment variable is missing.")
        return

    try:
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()

        print("🌱 Seeding database with initial grocery data...")

        for title, category, store, price in SAMPLE_PRODUCTS:
            cursor.execute(
                """
                INSERT INTO grocery_products (product_name, category, store_name, price)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (product_name, store_name) 
                DO UPDATE SET price = EXCLUDED.price, category = EXCLUDED.category, updated_at = CURRENT_TIMESTAMP;
                """,
                (title, category, store, price)
            )

        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Successfully seeded database with store data!")

    except Exception as e:
        print(f"❌ Database error: {e}")

if __name__ == "__main__":
    seed_database()