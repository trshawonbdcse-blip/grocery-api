import os
import psycopg2
from psycopg2.extras import execute_values

DB_URL = os.getenv("DATABASE_URL")

if not DB_URL:
    raise ValueError("DATABASE_URL environment variable is missing!")

# REAL PRODUCT CATALOG FOR TALLINN STORES
PRODUCTS = [
    # MAXIMA (Barbora)
    ("Alma Täispiim 3.8-4.2% 1L", "Dairy & Eggs", "Maxima EE", 0.99),
    ("Alma Piim 2.5% 1L", "Dairy & Eggs", "Maxima EE", 0.79),
    ("Tere Hapukoor 20% 500g", "Dairy & Eggs", "Maxima EE", 1.29),
    ("Eesti Pagar Kodukandi Rukkileib 600g", "Bakery", "Maxima EE", 1.15),
    ("Fazer Kodusai 500g", "Bakery", "Maxima EE", 0.99),
    ("Banaanid 1kg", "Fruit & Veg", "Maxima EE", 1.19),
    ("Õun Jonagold 1kg", "Fruit & Veg", "Maxima EE", 1.29),
    ("Maks & Moorits Kodune Hakkliha 500g", "Meat & Fish", "Maxima EE", 2.89),
    ("Tallegg Broileri Kintsuliha 500g", "Meat & Fish", "Maxima EE", 3.49),
    ("Rakvere Lasteviiner 440g", "Meat & Fish", "Maxima EE", 2.19),
    ("Muna L-suurus 10tk", "Dairy & Eggs", "Maxima EE", 1.89),
    ("Valio Atleet Juust 500g", "Dairy & Eggs", "Maxima EE", 4.29),
    ("Saaremaa Või 82% 200g", "Dairy & Eggs", "Maxima EE", 2.19),
    ("Saku Originaal Õlu 4.6% 0.5L", "Drinks", "Maxima EE", 1.29),
    ("A. Le Coq Premium Õlu 4.7% 0.5L", "Drinks", "Maxima EE", 1.29),
    ("Neptunas Gaasita Vesi 1.5L", "Drinks", "Maxima EE", 0.69),

    # SELVER
    ("Alma Täispiim 3.8-4.2% 1L", "Dairy & Eggs", "Selver", 1.09),
    ("Alma Piim 2.5% 1L", "Dairy & Eggs", "Selver", 0.85),
    ("Tere Hapukoor 20% 500g", "Dairy & Eggs", "Selver", 1.39),
    ("Eesti Pagar Kodukandi Rukkileib 600g", "Bakery", "Selver", 1.25),
    ("Fazer Kodusai 500g", "Bakery", "Selver", 1.09),
    ("Banaanid 1kg", "Fruit & Veg", "Selver", 1.39),
    ("Õun Jonagold 1kg", "Fruit & Veg", "Selver", 1.49),
    ("Maks & Moorits Kodune Hakkliha 500g", "Meat & Fish", "Selver", 3.19),
    ("Tallegg Broileri Kintsuliha 500g", "Meat & Fish", "Selver", 3.79),
    ("Rakvere Lasteviiner 440g", "Meat & Fish", "Selver", 2.39),
    ("Muna L-suurus 10tk", "Dairy & Eggs", "Selver", 2.09),
    ("Valio Atleet Juust 500g", "Dairy & Eggs", "Selver", 4.69),
    ("Saaremaa Või 82% 200g", "Dairy & Eggs", "Selver", 2.39),
    ("Paulig Classic Kohv 500g", "Pantry", "Selver", 5.99),
    ("Merrild Medium Kohv 500g", "Pantry", "Selver", 5.49),

    # RIMI
    ("Alma Täispiim 3.8-4.2% 1L", "Dairy & Eggs", "Rimi Baltic", 1.05),
    ("Alma Piim 2.5% 1L", "Dairy & Eggs", "Rimi Baltic", 0.82),
    ("Tere Hapukoor 20% 500g", "Dairy & Eggs", "Rimi Baltic", 1.35),
    ("Eesti Pagar Kodukandi Rukkileib 600g", "Bakery", "Rimi Baltic", 1.19),
    ("Fazer Kodusai 500g", "Bakery", "Rimi Baltic", 1.05),
    ("Banaanid 1kg", "Fruit & Veg", "Rimi Baltic", 1.29),
    ("Maks & Moorits Kodune Hakkliha 500g", "Meat & Fish", "Rimi Baltic", 2.99),

    # PRISMA
    ("Alma Täispiim 3.8-4.2% 1L", "Dairy & Eggs", "Prisma EE", 0.95),
    ("Alma Piim 2.5% 1L", "Dairy & Eggs", "Prisma EE", 0.78),
    ("Tere Hapukoor 20% 500g", "Dairy & Eggs", "Prisma EE", 1.25),
    ("Eesti Pagar Kodukandi Rukkileib 600g", "Bakery", "Prisma EE", 1.12),
    ("Fazer Kodusai 500g", "Bakery", "Prisma EE", 0.98),
    ("Banaanid 1kg", "Fruit & Veg", "Prisma EE", 1.15),
    ("Maks & Moorits Kodune Hakkliha 500g", "Meat & Fish", "Prisma EE", 2.85),
]

def seed_database():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # Safely alter table to add columns if they are missing
    cur.execute("""
        ALTER TABLE grocery_products ADD COLUMN IF NOT EXISTS image_url TEXT;
        ALTER TABLE grocery_products ADD COLUMN IF NOT EXISTS product_url TEXT;
    """)

    query = """
        INSERT INTO grocery_products (product_name, category, store_name, price)
        VALUES %s
        ON CONFLICT DO NOTHING;
    """

    try:
        execute_values(cur, query, PRODUCTS)
        conn.commit()
        print(f"✅ Schema verified and {len(PRODUCTS)} grocery items successfully added to PostgreSQL!")
    except Exception as e:
        conn.rollback()
        print(f"❌ DB Seed Error: {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    seed_database()
