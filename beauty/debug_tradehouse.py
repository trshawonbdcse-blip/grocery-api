import asyncio
from playwright.async_api import async_playwright

async def debug_tradehouse():
    print("🔍 Starting Tradehouse Debugger...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print("🌐 Navigating to Tradehouse...")
        # Pointing directly to their 50-70% off Outlet section
        await page.goto("https://tradehouse.ee/campaigns/soodus-50-70?lang=et", wait_until="domcontentloaded", timeout=60000)
        
        print("⏳ Waiting 5 seconds for page to settle...")
        await page.wait_for_timeout(5000)
        
        await page.evaluate("window.scrollBy(0, 800)")
        await page.wait_for_timeout(2000)

        await page.screenshot(path="tradehouse_debug.png")
        print("📸 Screenshot saved as 'tradehouse_debug.png'")

        html = await page.evaluate("""() => {
            const links = document.querySelectorAll('a');
            
            // Try to find a link that looks like a product (contains €)
            const productLinks = Array.from(links).filter(a => a.innerText.includes('€'));
            
            if (productLinks.length > 0) {
                return `Found ${productLinks.length} product links. First item HTML:\\n\\n` + productLinks[0].outerHTML;
            }
            
            return "❌ No product links found. Page snippet:\\n\\n" + document.body.innerHTML.substring(0, 1500);
        }""")

        print("\n--- DOM INSPECTION ---")
        print(html)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_tradehouse())