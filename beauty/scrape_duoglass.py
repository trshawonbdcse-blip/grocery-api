import asyncio
import re
from playwright.async_api import async_playwright
from beauty_utils import save_product

async def run():
    print("\n📂 Scraping Douglas.ee (Kampaania)...")
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
            current_page = 1
            total_saved = 0
            seen_urls = set()
            
            # 1. Load the first page
            current_url = f"https://www.douglas.ee/ee/kampaania/?page={current_page}"
            await page.goto(current_url, wait_until="networkidle", timeout=60000)
            
            # 2. Attempt to dismiss the Usercentrics Cookie Banner if it blocks clicks
            try:
                cookie_btn = page.locator('button:has-text("Nõustu"), button:has-text("Accept"), button:has-text("Nõustun")')
                if await cookie_btn.count() > 0:
                    await cookie_btn.first.click()
                    await page.wait_for_timeout(2000)
            except Exception:
                pass

            while True:
                print(f"\n  --> Processing Douglas Page {current_page}...")
                
                # Scroll heavily to trigger all lazy-loaded product grids
                for _ in range(6):
                    await page.evaluate("window.scrollBy(0, 800)")
                    await page.wait_for_timeout(800)

                # Target ALL links generically
                links = await page.query_selector_all('a')
                page_saved = 0
                
                for link in links:
                    try:
                        href = await link.get_attribute("href")
                        if not href or href.startswith("javascript") or "#" in href:
                            continue
                            
                        full_url = href if href.startswith("http") else f"https://www.douglas.ee{href}"
                        
                        if full_url in seen_urls:
                            continue

                        text = await link.inner_text()
                        if "€" not in text:
                            continue

                        # It must have an image to be a real product card
                        img_el = await link.query_selector('img')
                        if not img_el:
                            continue
                            
                        img = await img_el.get_attribute("src") or ""

                        # Extract Prices (e.g., 12,99 €)
                        prices = re.findall(r"(\d+[\.,]\d{2})", text)
                        if not prices:
                            continue
                            
                        # Clean up text to extract Brand and Title
                        bad_words = ["€", "%", "LISA KORVI", "UUS", "SOODUS", "OUTLET", "KINGITUS", "KAMPAANIA"]
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
                                store="Douglas",
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

                if page_saved == 0:
                    print("  --> No new items found. Ending pagination.")
                    break

                # Navigate to the exact URL structure you provided
                current_page += 1
                next_url = f"https://www.douglas.ee/ee/kampaania/?page={current_page}"
                
                print(f"  --> Moving to next URL: {next_url}")
                await page.goto(next_url, wait_until="domcontentloaded", timeout=60000)
                    
            print(f"🏁 Douglas finished. Processed {total_saved} total items.")
        except Exception as e:
            print(f"⚠️ Douglas connection error: {e}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())