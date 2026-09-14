import asyncio
from playwright.async_api import async_playwright

async def debug_douglas_api():
    print("🔍 Starting Douglas Network API Interceptor...")
    async with async_playwright() as p:
        # Running headful to easily pass any basic bot checks
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        
        async def handle_response(response):
            # Listen to all API/JSON calls
            if "api" in response.url or "graphql" in response.url or "products" in response.url or "search" in response.url:
                try:
                    if "application/json" in response.headers.get("content-type", ""):
                        data = await response.json()
                        
                        # Print the exact URL of the data source
                        print(f"\n📦 Intercepted JSON from: {response.url}")
                        
                        if isinstance(data, dict):
                            print("   Top-level keys:", list(data.keys()))
                            
                            # Guessing where the products live in the dictionary
                            items = data.get("products") or data.get("items") or data.get("data", {}).get("products") or data.get("results")
                            if items and isinstance(items, list) and len(items) > 0:
                                print(f"   ✅ Found {len(items)} products inside! First product structure:")
                                print("   ", list(items[0].keys()))
                except Exception:
                    pass

        # Attach the network listener
        page.on("response", handle_response)
        
        print("🌐 Navigating to Douglas Outlet...")
        await page.goto("https://www.douglas.ee/ee/outlet/", wait_until="networkidle", timeout=60000)
        
        # Scroll down a few times to trigger any lazy-loaded API calls
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 1000)")
            await page.wait_for_timeout(2000)
        
        print("\n🏁 Done listening.")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_douglas_api())