import asyncio
import re
from playwright.async_api import async_playwright
from beauty_utils import save_product

async def run():
    print("\n📂 Scraping Tradehouse.ee...")
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
            current_url = "https://tradehouse.ee/campaigns/soodus-50-70?lang=et" 
            await page.goto(current_url, wait_until="domcontentloaded", timeout=60000)
            
            total_saved = 0
            seen_urls = set()
            current_page = 1
            
            while True:
                print(f"\n  --> Processing Tradehouse Page {current_page}...")
                
                try:
                    await page.wait_for_selector('a.product-preview__wrapper', timeout=15000)
                except Exception:
                    print("  --> No product cards found. Catalog finished.")
                    break

                # Scroll down to trigger lazy loading for imagekit CDN assets
                for _ in range(5):
                    await page.evaluate("window.scrollBy(0, 800)")
                    await page.wait_for_timeout(800)

                items = await page.query_selector_all('a.product-preview__wrapper')
                page_saved = 0
                
                for item in items:
                    try:
                        href = await item.get_attribute("href")
                        if not href:
                            continue
                            
                        full_url = href if href.startswith("http") else f"https://tradehouse.ee{href}"
                        
                        if full_url in seen_urls:
                            continue

                        brand_el = await item.query_selector('.product-preview__brand-name')
                        name_el = await item.query_selector('.product-preview__name')
                        price_el = await item.query_selector('.product-preview__price')
                        old_price_el = await item.query_selector('.product-preview__old-price')
                        img_el = await item.query_selector('img.product-preview__image-inner, img')

                        if not (name_el and price_el):
                            continue

                        brand = await brand_el.inner_text() if brand_el else ""
                        name = await name_el.inner_text()
                        
                        brand_clean = brand.strip()
                        name_clean = name.strip()
                        
                        if brand_clean and not name_clean.lower().startswith(brand_clean.lower()):
                            title = f"{brand_clean} {name_clean}"
                        else:
                            title = name_clean

                        price_text = await price_el.inner_text()
                        old_price_text = await old_price_el.inner_text() if old_price_el else ""
                        img = await img_el.get_attribute("src") if img_el else ""

                        # Parse current vs old price
                        curr_prices = re.findall(r"(\d+[\.,]\d{2})", price_text.replace(old_price_text, ""))
                        orig_prices = re.findall(r"(\d+[\.,]\d{2})", old_price_text) if old_price_text else []

                        if not curr_prices:
                            curr_prices = re.findall(r"(\d+[\.,]\d{2})", price_text)

                        if curr_prices and title:
                            curr_val = float(curr_prices[0].replace(",", "."))
                            if orig_prices:
                                orig_val = float(orig_prices[0].replace(",", "."))
                            elif len(curr_prices) > 1:
                                orig_val = float(curr_prices[1].replace(",", "."))
                            else:
                                orig_val = curr_val

                            save_product(
                                title=title, 
                                fallback_cat="", 
                                store="Tradehouse",
                                current_price=curr_val, 
                                original_price=orig_val if orig_val > curr_val else curr_val,
                                img=img, 
                                url=full_url
                            )
                            seen_urls.add(full_url)
                            page_saved += 1
                            total_saved += 1
                    except Exception:
                        continue
                        
                print(f"      Extracted {page_saved} items on this page.")

                if page_saved == 0:
                    print("  --> No new items found. Ending pagination.")
                    break

                # Pagination handling via next link or page URL parameter
                next_button = await page.query_selector('a.pagination__next, a[aria-label="Next page"]')
                if next_button:
                    next_url = await next_button.get_attribute("href")
                    if next_url:
                        full_next = next_url if next_url.startswith("http") else f"https://tradehouse.ee{next_url}"
                        print(f"  --> Moving to: {full_next}")
                        await page.goto(full_next, wait_until="domcontentloaded", timeout=60000)
                        current_page += 1
                        continue
                
                current_page += 1
                fallback_url = f"https://tradehouse.ee/campaigns/soodus-50-70?lang=et&page={current_page}"
                print(f"  --> Moving to fallback URL: {fallback_url}")
                await page.goto(fallback_url, wait_until="domcontentloaded", timeout=60000)
                    
            print(f"🏁 Tradehouse finished. Processed {total_saved} total items.")
        except Exception as e:
            print(f"⚠️ Tradehouse connection error: {e}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())