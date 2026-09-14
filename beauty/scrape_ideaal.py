import asyncio
import re
from playwright.async_api import async_playwright
from beauty_utils import save_product

async def run():
    print("\n📂 Scraping IdeaalKosmeetika.ee...")
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
            # We filter by minimum 7% discount based on your original target
            current_url = "https://www.ideaalkosmeetika.ee/tooted-e-pood/?min_discount=7"
            await page.goto(current_url, wait_until="domcontentloaded", timeout=60000)
            
            total_saved = 0
            seen_urls = set()
            current_page = 1
            
            while True:
                print(f"\n  --> Processing IdeaalKosmeetika Page {current_page}...")
                
                try:
                    # Wait for WooCommerce product grid
                    await page.wait_for_selector('li.product, div.product-grid-item', timeout=15000)
                except Exception:
                    print("  --> No products found. The catalog might be empty.")
                    break

                # Scroll progressively to ensure images and prices fully render
                for _ in range(4):
                    await page.evaluate("window.scrollBy(0, 800)")
                    await page.wait_for_timeout(800)

                items = await page.query_selector_all("li.product, div.product-grid-item")
                page_saved = 0
                
                for item in items:
                    try:
                        title_el = await item.query_selector(".woocommerce-loop-product__title, .product-title, h2, h3")
                        price_el = await item.query_selector(".price")
                        link_el = await item.query_selector("a")
                        img_el = await item.query_selector("img")

                        if not (title_el and price_el and link_el):
                            continue

                        title = await title_el.inner_text()
                        price_text = await price_el.inner_text()
                        href = await link_el.get_attribute("href")
                        img = await img_el.get_attribute("src") if img_el else ""

                        if not href: 
                            continue
                            
                        full_url = href if href.startswith("http") else f"https://www.ideaalkosmeetika.ee{href}"

                        if full_url in seen_urls:
                            continue

                        # Extract EUR prices
                        prices = re.findall(r"(\d+[\.,]\d{2})", price_text)
                        
                        if prices and title:
                            curr_val = float(prices[0].replace(",", "."))
                            orig_val = float(prices[1].replace(",", ".")) if len(prices) > 1 else curr_val

                            save_product(
                                title=title.strip().replace("\n", " "),
                                fallback_cat="", 
                                store="IdeaalKosmeetika",
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

                # Handle WooCommerce Pagination (Next Arrow)
                next_button = await page.query_selector('a.next.page-numbers, a.next')
                if next_button:
                    next_url = await next_button.get_attribute("href")
                    if next_url:
                        print(f"  --> Moving to: {next_url}")
                        await page.goto(next_url, wait_until="domcontentloaded", timeout=60000)
                        current_page += 1
                    else:
                        print("  --> No valid next page link found.")
                        break
                else:
                    print("  --> Reached the last page.")
                    break
                    
            print(f"🏁 IdeaalKosmeetika finished. Processed {total_saved} total items.")
        except Exception as e:
            print(f"⚠️ IdeaalKosmeetika connection error: {e}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())