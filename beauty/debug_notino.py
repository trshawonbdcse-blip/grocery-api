import asyncio
from playwright.async_api import async_playwright

async def debug_pagination():
    print("🔍 Hunting for Notino's pagination element...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        await page.goto("https://www.notino.ee/soodustus/", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_selector('[data-testid="product-container"]', timeout=15000)
        
        # Scroll to the absolute bottom where pagination lives
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)

        # Look for common pagination wrappers
        html = await page.evaluate("""() => {
            const pag = document.querySelector('[data-testid="pagination"], nav[aria-label*="pag"], .pagination');
            if (pag) return pag.outerHTML;
            
            // Fallback: look for the next page link directly (Page 2)
            const links = Array.from(document.querySelectorAll('a'));
            const nextPage = links.find(l => l.innerText.includes('2') || l.innerText.includes('Järgmine'));
            if (nextPage) return "Found Next Link:\\n" + nextPage.outerHTML;
            
            return "❌ Could not find pagination block.";
        }""")

        print("\n--- PAGINATION HTML ---")
        print(html)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_pagination())