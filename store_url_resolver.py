import re
import urllib.parse
import httpx
from bs4 import BeautifulSoup

def clean_store_name_dynamically(raw_name: str) -> str:
    """Dynamically removes floor levels, room numbers, and layout noise using regex patterns."""
    text = raw_name.lower()
    
    # Dynamic regex filters for floor numbers, floor levels, and layout directions
    text = re.sub(r"\d+[\.\/]?\s*(korrus|floor|fl|k)\b", "", text)
    text = re.sub(r"\b(1st|2nd|3rd|4th|\d+th)\s*(floor)?\b", "", text)
    text = re.sub(r"\b(viru|kristiine|ülemiste|solaris|nautica|rocca|t1|keskus|turg|tunnel|center|mall)\b", "", text)
    
    # Strip non-alphanumeric noise except spaces
    cleaned = re.sub(r"[^\w\s]", " ", text)
    return " ".join(cleaned.split())

def discover_url_via_live_search(brand_name: str) -> str:
    """Dynamically searches the live web for a brand's Estonian e-commerce or sale URL."""
    query = f"{brand_name} Estonia e-commerce outlet sale"
    search_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    
    try:
        with httpx.Client(follow_redirects=True, timeout=6.0, headers=headers) as client:
            res = client.get(search_url)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                for link in soup.select("a.result__url"):
                    href = link.get("href", "")
                    # Extract target URL from DuckDuckGo redirect link
                    match = re.search(r"uddg=(https?://[^&]+)", href)
                    actual_url = urllib.parse.unquote(match.group(1)) if match else href
                    
                    if actual_url.startswith("http") and not any(x in actual_url for x in ["facebook.com", "instagram.com", "wikipedia.org", "map", "zone.ee"]):
                        return actual_url
    except Exception:
        pass
        
    return ""

def resolve_store_ecommerce_url(store_name: str) -> str:
    """Pure dynamic URL resolver with zero static hardcoded brand dictionaries."""
    clean_name = clean_store_name_dynamically(store_name)
    if not clean_name or len(clean_name) < 2:
        return ""

    # Attempt standard domain pattern first
    slug = re.sub(r"[^\w]", "", clean_name).lower()
    candidate_url = f"https://www.{slug}.ee/"

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    try:
        with httpx.Client(follow_redirects=True, timeout=3.0, headers=headers, verify=False) as client:
            res = client.head(candidate_url)
            if res.status_code < 400:
                return str(res.url)
    except Exception:
        pass

    # Fallback: Live search discovery for global or non-.ee brand domains
    return discover_url_via_live_search(clean_name)