import asyncio
from playwright.async_api import async_playwright
from beauty_utils import save_product

async def run():
    print("\n📂 Scraping Loverte.com (Dynamic API Interceptor)...")
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

        captured_products = []

        async def handle_response(response):
            # Listen specifically for Loverte's GraphQL/JSON endpoints
            if any(k in response.url for k in ["graphql", "api", "catalog", "products"]):
                try:
                    if "application/json" in response.headers.get("content-type", ""):
                        data = await response.json()
                        if isinstance(data, dict):
                            items = (
                                data.get("products", {}).get("items") or
                                data.get("data", {}).get("products", {}).get("items") or
                                data.get("items") or []
                            )
                            if isinstance(items, list) and len(items) > 0:
                                captured_products.extend(items)
                except Exception:
                    pass

        # Attach the network listener to the page
        page.on("response", handle_response)
        
        current_page = 1
        total_saved = 0
        seen_urls = set()

        while True:
            print(f"\n  --> Processing Loverte Page {current_page}...")
            captured_products.clear() # Reset interceptor cache for the new page
            
            url = f"https://www.loverte.com/et/eripakkumised?page={current_page}"
            try:
                # networkidle is safe here because we need the GraphQL payload to finish downloading
                await page.goto(url, wait_until="networkidle", timeout=60000)
                await page.evaluate("window.scrollBy(0, 1000)")
                await page.wait_for_timeout(3000)
            except Exception as e:
                print(f"⚠️ Loverte network navigation error: {e}")
                break

            # If the API returned nothing, we reached the end of the catalog
            if not captured_products:
                print("  --> No JSON products intercepted. Ending pagination.")
                break

            page_saved = 0
            for item in captured_products:
                if isinstance(item, dict):
                    title = item.get("name") or item.get("title")
                    price_info = item.get("price_range", {}).get("minimum_price", {}) or item.get("price", {})
                    
                    curr_val = None
                    orig_val = None

                    if isinstance(price_info, dict):
                        curr_val = price_info.get("final_price", {}).get("value") or price_info.get("value") or price_info.get("price")
                        orig_val = price_info.get("regular_price", {}).get("value") or curr_val

                    url_key = item.get("url_key") or item.get("slug") or ""
                    image_info = item.get("image", {})
                    img = image_info.get("url") if isinstance(image_info, dict) else item.get("small_image", {}).get("url", "")

                    if title and curr_val:
                        product_url = f"https://www.loverte.com/et/{url_key}" if url_key else url
                        
                        if product_url in seen_urls:
                            continue

                        save_product(
                            title=str(title).strip(), 
                            fallback_cat="", 
                            store="Loverte",
                            current_price=float(curr_val), 
                            original_price=float(orig_val or curr_val),
                            img=str(img or ""), 
                            url=product_url
                        )
                        seen_urls.add(product_url)
                        page_saved += 1
                        total_saved += 1
            
            print(f"      Extracted {page_saved} items from API on this page.")
            
            # Failsafe: if we processed items but didn't save any new ones, break the loop
            if page_saved == 0:
                print("  --> No new unique items found. Ending pagination.")
                break
                
            current_page += 1

        print(f"🏁 Loverte finished. Processed {total_saved} total items.")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())