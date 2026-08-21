import os
import re
import time
import httpx
from bs4 import BeautifulSoup
import psycopg2
from psycopg2.extras import RealDictCursor

# Selenium imports for JavaScript rendering
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

DB_URL = os.getenv("DATABASE_URL")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "et,en-US;q=0.9,en;q=0.8",
}


def scrape_fuelest_headless():
    """Renders FuelEst.ee#latestPrices using Headless Chrome to capture JS-hydrated pricing elements."""
    scraped_prices = {}
    url = "https://fuelest.ee/en#latestPrices"

    print(f"🌐 [Primary] Launching Headless Browser for FuelEst: {url}...")

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument(f"user-agent={HEADERS['User-Agent']}")

    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(15)
        
        driver.get(url)
        # Give JS single-page app 3 seconds to fetch dynamic pricing tables
        time.sleep(3)

        html_content = driver.page_source
        soup = BeautifulSoup(html_content, "html.parser")

        # Parse rendered elements
        for row in soup.find_all(["tr", "div", "li"]):
            text = row.get_text(separator=" ", strip=True)
            text_lower = text.lower()

            # Search for 3-decimal prices (e.g., 1.699 or 1,714)
            matches = re.findall(r"\b(1[\.,]\d{3})\b", text)
            if not matches:
                continue

            price_val = float(matches[0].replace(",", "."))

            chain = None
            if "neste" in text_lower:
                chain = "Neste"
            elif "circle" in text_lower:
                chain = "Circle K"
            elif "alexela" in text_lower:
                chain = "Alexela"
            elif "olerex" in text_lower:
                chain = "Olerex"
            elif "terminal" in text_lower:
                chain = "Terminal"
            elif "jetoil" in text_lower:
                chain = "Jetoil"

            if chain and 1.300 <= price_val <= 2.200:
                scraped_prices[chain] = price_val

        if scraped_prices:
            print(f"✅ Successfully extracted FuelEst JS Payload: {scraped_prices}")

    except Exception as e:
        print(f"⚠️ Headless Chrome FuelEst scraper error: {e}")
    finally:
        if driver:
            driver.quit()

    return scraped_prices


def scrape_eestihinnad_fallback():
    """Fallback scraper using EestiHinnad.ee if FuelEst is unavailable."""
    scraped_prices = {}
    url = "https://eestihinnad.ee/kutusehinnad"

    try:
        print("🌐 [Fallback] Querying live fuel prices from EestiHinnad.ee...")
        with httpx.Client(follow_redirects=True, timeout=12.0, verify=False) as client:
            res = client.get(url, headers=HEADERS)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                for row in soup.find_all("tr"):
                    text = row.get_text(separator=" ", strip=True)
                    text_lower = text.lower()
                    
                    matches = re.findall(r"\b(1[\.,]\d{3})\b", text)
                    if not matches:
                        continue

                    price_val = float(matches[0].replace(",", "."))
                    
                    chain = None
                    if "neste" in text_lower:
                        chain = "Neste"
                    elif "circle" in text_lower:
                        chain = "Circle K"
                    elif "alexela" in text_lower:
                        chain = "Alexela"
                    elif "olerex" in text_lower:
                        chain = "Olerex"
                    elif "terminal" in text_lower:
                        chain = "Terminal"
                    elif "jetoil" in text_lower:
                        chain = "Jetoil"

                    if chain and 1.300 <= price_val <= 2.200:
                        scraped_prices[chain] = price_val

                if scraped_prices:
                    print(f"✅ Successfully scraped EestiHinnad payload: {scraped_prices}")

    except Exception as e:
        print(f"⚠️ Fallback scraper failed: {e}")

    return scraped_prices


def sync_prices():
    if not DB_URL:
        print("❌ ERROR: DATABASE_URL environment variable is missing.")
        return

    # 1. Attempt Headless Scrape of FuelEst.ee#latestPrices
    live_data = scrape_fuelest_headless()

    # 2. Fall back to EestiHinnad if FuelEst returns empty
    if not live_data:
        print("⚠️ FuelEst returned no items. Switching to fallback provider...")
        live_data = scrape_eestihinnad_fallback()

    if not live_data:
        print("❌ All price scrapers failed to yield data. Database untouched.")
        return

    print(f"📊 Final Synced Price Payload: {live_data}")

    # 3. Update PostgreSQL Database
    conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()

    try:
        updated_count = 0
        for chain, price in live_data.items():
            cur.execute(
                """
                UPDATE fuel_prices 
                SET price_per_liter = %s, updated_at = NOW() 
                FROM fuel_stations 
                WHERE fuel_prices.station_id = fuel_stations.id 
                  AND fuel_stations.chain_name ILIKE %s 
                  AND fuel_prices.fuel_type = '95';
            """,
                (price, f"%{chain}%"),
            )
            updated_count += cur.rowcount

        conn.commit()
        print(f"✅ Successfully updated {updated_count} station records in PostgreSQL!")

    except Exception as e:
        conn.rollback()
        print(f"❌ Database update error: {e}")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    sync_prices()