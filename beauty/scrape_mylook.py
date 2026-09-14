import asyncio
import re
from playwright.async_api import async_playwright
from beauty_utils import save_product

async def run():
    print("\n📂 Scraping MyLook.ee (Dynamic Nuxt Headless)...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, 
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            current_url = "https://www.mylook.ee/campaign"
            await page.goto(current_url, wait_until="domcontentloaded", timeout=60000)
            
            total_saved = 0
            seen_urls = set()
            current_page = 1
            
            while True:
                print(f"\n  --> Processing MyLook Page {current_page}...")
                
                # Allow Nuxt time to hydrate the frontend DOM with the API data
                await page.wait_for_timeout(4000)
                
                # Scroll heavily to trigger all lazy-loaded images
                for _ in range(6):
                    await page.evaluate("window.scrollBy(0, 800)")
                    await page.wait_for_timeout(800)

                # Target ALL links generically
                links = await page.query_selector_all('a')
                page_saved = 0
                
                for link in links:
                    try:
                        href = await link.get_attribute("href")
                        if not href or href.startswith("javascript") or "/info/" in href or "kliendid-meist" in href:
                            continue
                            
                        full_url = href if href.startswith("http") else f"https://www.mylook.ee{href}"
                        
                        # Avoid duplicates
                        if full_url in seen_urls:
                            continue

                        text = await link.inner_text()
                        if "€" not in text:
                            continue

                        img_el = await link.query_selector('img')
                        if not img_el:
                            continue
                            
                        img = await img_el.get_attribute("src") or ""

                        # Extract Prices
                        prices = re.findall(r"(\d+[\.,]\d{2})", text)
                        if not prices:
                            continue
                            
                        # Clean up the text to extract just the Title and Brand
                        bad_words = ["€", "%", "LISA OSTUKORVI", "UUS", "SOODUS", "MÜÜDUD", "OUT OF STOCK"]
                        lines = [l.strip() for l in text.split("\n") if l.strip() and not any(b in l.upper() for b in bad_words)]
                        
                        if len(lines) >= 2:
                            title = f"{lines[0]} {lines[1]}"
                        elif len(lines) == 1:
                            title = lines[0]
                        else:
                            continue

                        if len(title) > 3:
                            curr_val = float(prices[0].replace(",", "."))
                            orig_val = float(prices[1].replace(",", ".")) if len(prices) > 1 else curr_val

                            save_product(
                                title=title, 
                                fallback_cat="", 
                                store="MyLook",
                                current_price=curr_val, 
                                original_price=orig_val if orig_val > curr_val else curr_val,
                                img=img, 
                                url=full_url
                            )
                            seen_urls.add(full_url)
                            page_saved += 1
                            total_saved += 1
                    except Exception as e:
                        continue
                        
                print(f"      Extracted {page_saved} items on this page.")

                # Dynamic Stop Condition: Break the loop if we extracted 0 products
                if page_saved == 0:
                    print("  --> No new items found. Ending pagination.")
                    break

                # Increment page and navigate
                current_page += 1
                next_full_url = f"https://www.mylook.ee/campaign?page={current_page}"
                print(f"  --> Moving to: {next_full_url}")
                await page.goto(next_full_url, wait_until="domcontentloaded", timeout=60000)
                    
            print(f"🏁 MyLook finished. Processed {total_saved} total items.")
        except Exception as e:
            print(f"⚠️ MyLook connection error: {e}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())