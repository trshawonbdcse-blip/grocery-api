import asyncio
from playwright.async_api import async_playwright

async def debug_mylook_api():
    print("🔍 Starting MyLook Network API Interceptor...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        
        async def handle_response(response):
            # Nuxt APIs usually pull data via GraphQL or a dedicated API endpoint
            if "api" in response.url or "graphql" in response.url or "campaign" in response.url:
                try:
                    # Only look at JSON responses
                    if "application/json" in response.headers.get("content-type", ""):
                        data = await response.json()
                        
                        # Print the URL so we know which endpoint is supplying the products
                        print(f"\n📦 Intercepted JSON from: {response.url}")
                        
                        # Print a small snippet of the dictionary keys to understand the structure
                        if isinstance(data, dict):
                            print("   Top-level keys:", list(data.keys()))
                            
                            # Guessing common paths for GraphQL/Magento Headless
                            items = data.get("data", {}).get("products", {}).get("items") or data.get("items")
                            if items and len(items) > 0:
                                print(f"   ✅ Found {len(items)} products inside! First product structure:")
                                # Print the first product's keys so we know how to extract the price/title
                                print("   ", list(items[0].keys()))
                except Exception:
                    pass

        # Attach the network listener
        page.on("response", handle_response)
        
        print("🌐 Navigating to MyLook...")
        await page.goto("https://www.mylook.ee/campaign", wait_until="networkidle", timeout=60000)
        
        # Scroll down to trigger the API calls
        await page.evaluate("window.scrollBy(0, 1000)")
        await page.wait_for_timeout(4000)
        
        print("\n🏁 Done listening.")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_mylook_api())