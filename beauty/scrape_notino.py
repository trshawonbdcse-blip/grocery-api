import asyncio
import re
from playwright.async_api import async_playwright
from beauty_utils import save_product

async def run(max_scrolls=10):
    print("\n📂 Scraping Notino.ee (Soodustus) via Infinite Scroll...")
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
            current_url = "https://www.notino.ee/soodustus/"
            await page.goto(current_url, wait_until="domcontentloaded", timeout=60000)
            
            # Wait for the initial product grid
            await page.wait_for_selector('[data-testid="product-container"]', timeout=15000)
            
            total_saved = 0
            seen_urls = set()
            scroll_attempts_without_new_items = 0
            
            for scroll_step in range(1, max_scrolls + 1):
                print(f"  --> Scroll Pass {scroll_step}/{max_scrolls}...")
                
                # Scroll to the absolute bottom of the page
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)
                
                # Check for and click the "Load More" / "Näita rohkem" button if Notino is hiding it behind a click
                try:
                    load_more_btn = page.locator('button:has-text("Näita rohkem"), button:has-text("Load more")')
                    if await load_more_btn.count() > 0 and await load_more_btn.first.is_visible():
                        await load_more_btn.first.click()
                        await page.wait_for_timeout(2000)
                except Exception:
                    pass # Normal if button isn't there and it auto-scrolls

                # Grab all currently loaded products
                items = await page.query_selector_all('[data-testid="product-container"]')
                new_items_this_pass = 0
                
                for item in items:
                    try:
                        link_el = await item.query_selector('a')
                        if not link_el: continue
                        
                        href = await link_el.get_attribute("href")
                        full_url = href if href.startswith("http") else f"https://www.notino.ee{href}"
                        
                        # Skip if we already processed it on a previous scroll
                        if full_url in seen_urls:
                            continue
                            
                        title_el = await item.query_selector('[data-testid="product-card-name"]')
                        brand_el = await item.query_selector('[data-testid="product-card-brand"]')
                        price_el = await item.query_selector('[data-testid="product-price"]')
                        img_el = await item.query_selector('img')

                        if not (title_el and price_el): continue

                        raw_title = await title_el.inner_text()
                        raw_brand = await brand_el.inner_text() if brand_el else ""
                        full_title = f"{raw_brand} {raw_title}".strip()

                        price_text = await price_el.inner_text()
                        img = await img_el.get_attribute("src") if img_el else ""

                        prices = re.findall(r"(\d+[\.,]\d{2})", price_text)

                        if prices and full_title and len(full_title) > 3:
                            curr_val = float(prices[0].replace(",", "."))
                            orig_val = float(prices[1].replace(",", ".")) if len(prices) > 1 else curr_val
                            
                            save_product(
                                title=full_title, 
                                fallback_cat="", 
                                store="Notino",
                                current_price=curr_val, 
                                original_price=orig_val if orig_val > curr_val else curr_val,
                                img=img, 
                                url=full_url
                            )
                            seen_urls.add(full_url)
                            new_items_this_pass += 1
                            total_saved += 1
                    except Exception as e:
                        continue
                        
                print(f"      Extracted {new_items_this_pass} new items on this scroll pass.")
                
                # Stop scrolling if we've hit the true bottom of the catalog
                if new_items_this_pass == 0:
                    scroll_attempts_without_new_items += 1
                    if scroll_attempts_without_new_items >= 2:
                        print("  --> Reached the end of the product feed.")
                        break
                else:
                    scroll_attempts_without_new_items = 0
                    
            print(f"🏁 Notino finished. Processed {total_saved} total items.")
        except Exception as e:
            print(f"⚠️ Notino connection error: {e}")

        await browser.close()

if __name__ == "__main__":
    # You can safely increase max_scrolls to 20 or 50 if you want the entire catalog
    asyncio.run(run(max_scrolls=15))