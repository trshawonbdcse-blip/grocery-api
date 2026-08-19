import os
import psycopg2
from psycopg2.extras import execute_values

DB_URL = os.getenv("DATABASE_URL")

def run_scraper_and_update_db():
    print("Starting grocery scraper job...")
    
    scraped_products = [
        ("Alma Piim 2.5% 1L", "Dairy & Eggs", "Maxima EE", 0.79),
        ("Tere Või 82% 200g", "Dairy & Eggs", "Selver", 2.19),
        ("Rukkipala Leib 330g", "Bakery", "Rimi", 1.05),
    ]

    if not DB_URL:
        raise ValueError("DATABASE_URL variable missing")

    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS grocery_products (
            id SERIAL PRIMARY KEY,
            product_name TEXT NOT NULL,
            category TEXT,
            store_name TEXT NOT NULL,
            price NUMERIC(10, 2) NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    insert_query = """
        INSERT INTO grocery_products (product_name, category, store_name, price)
        VALUES %s;
    """
    execute_values(cursor, insert_query, scraped_products)
    
    conn.commit()
    cursor.close()
    conn.close()
    print("Database updated successfully!")

if __name__ == "__main__":
    run_scraper_and_update_db()
