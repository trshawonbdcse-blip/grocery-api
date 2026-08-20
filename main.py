import os
import re
from typing import List, Optional
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import psycopg2
from psycopg2.extras import RealDictCursor

# --- IMPORT TRANSPORT ROUTER ---
from transport_service import router as transport_router

app = FastAPI(
    title="Tallinn Grocery, Beauty & Transport API",
    description="Unified API for grocery price comparison, beauty deals, and live Tallinn public transport tracking.",
    version="1.6.1",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Allow cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- REGISTER TRANSPORT ROUTER ---
app.include_router(transport_router)

DB_URL = os.getenv("DATABASE_URL")


def get_db():
    if not DB_URL:
        raise HTTPException(
            status_code=500, detail="DATABASE_URL environment variable missing or not set"
        )
    try:
        return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Database connection failed: {str(e)}"
        )


# --- HELPER CATEGORIZER FOR LIVE FALLBACK ---
def categorize_title(title: str, url: str) -> str:
    text = f"{title} {url}".lower()

    if any(k in text for k in ["parfüm", "perfume", "parfum", "eau de", "edt", "edp", "cologne", "lõhn"]):
        return "Perfume"
    elif any(k in text for k in ["huule", "mascara", "ripsme", "jumestus", "foundation", "lipstick", "makeup", "puder", "põsepuna", "laovärv"]):
        return "Makeup"
    elif any(k in text for k in ["šampoon", "shampoo", "palsam", "conditioner", "juukse", "hair", "mask", "õli"]):
        return "Hair care"
    elif any(k in text for k in ["näo", "facial", "face", "kreem", "cream", "seerum", "serum", "toonik", "puhastus", "cleanser"]):
        return "Facial care"
    elif any(k in text for k in ["keha", "body", "duši", "shower", "lotion", "seep", "scrub", "koorija"]):
        return "Body care"
    elif any(k in text for k in ["hamba", "oral", "tooth", "paste", "hari", "brush", "suuvesi"]):
        return "Oral care"
    elif any(k in text for k in ["laps", "beebi", "baby", "child", "mother"]):
        return "Mother and child"
    elif any(k in text for k in ["meeste", "men", "for men", "habeme", "shave"]):
        return "For men"
    elif any(k in text for k in ["päike", "sun", "spf", "päevitus"]):
        return "Sun"
    elif any(k in text for k in ["seade", "sirgendaja", "kuivati", "dryer", "trimmer", "epilaator"]):
        return "Electrical equipment"
    elif any(k in text for k in ["derma", "apteek", "pharmacy", "sensitive"]):
        return "Dermacosmetics"
    elif any(k in text for k in ["luxury", "luksus", "exclusive"]):
        return "Luxury"
    
    return "Facial care"


# --- LINK & SOURCE HEALTH CHECKER ---
def check_url_status(url: str) -> dict:
    if not url or not url.startswith("http"):
        return {
            "is_online": False, 
            "status_code": 0, 
            "status_label": "Invalid URL", 
            "badge_color": "red"
        }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    try:
        with httpx.Client(follow_redirects=True, timeout=6.0) as client:
            res = client.get(url, headers=headers)
                
            if res.status_code == 200:
                return {
                    "is_online": True, 
                    "status_code": res.status_code, 
                    "status_label": "Online", 
                    "badge_color": "green"
                }
            elif res.status_code in [403, 429]:
                # Cloudflare / Bot Protection active, but server is online
                return {
                    "is_online": True, 
                    "status_code": res.status_code, 
                    "status_label": "Online (Protected)", 
                    "badge_color": "green"
                }
            elif res.status_code in [404, 410]:
                return {
                    "is_online": False, 
                    "status_code": res.status_code, 
                    "status_label": "Broken Link (404)", 
                    "badge_color": "red"
                }
            else:
                return {
                    "is_online": False, 
                    "status_code": res.status_code, 
                    "status_label": f"Warning ({res.status_code})", 
                    "badge_color": "orange"
                }
    except httpx.TimeoutException:
        return {
            "is_online": False, 
            "status_code": 408, 
            "status_label": "Timeout", 
            "badge_color": "red"
        }
    except Exception:
        return {
            "is_online": False, 
            "status_code": 500, 
            "status_label": "Unreachable", 
            "badge_color": "red"
        }


# --- LIVE SCRAPE FALLBACK ENGINE ---
def live_search_fallback(query: str):
    results = []
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    
    try:
        with httpx.Client(follow_redirects=True, timeout=5.0) as client:
            res = client.get(f"https://www.notino.ee/search.asp?exs=1&q={query}", headers=headers)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                for card in soup.select("a[data-testid='product-card']")[:5]:
                    title_el = card.select_one("h3, strong")
                    price_el = card.select_one("span[data-testid='product-price']")
                    href = card.get("href", "")
                    img_el = card.select_one("img")
                    
                    if title_el and price_el:
                        title = title_el.get_text(strip=True)
                        price_match = re.search(r"(\d+[\.,]\d{2})", price_el.get_text())
                        price_val = float(price_match.group(1).replace(",", ".")) if price_match else 0.0
                        img = img_el.get("src", "") if img_el else ""
                        
                        full_url = href if href.startswith("http") else f"https://www.notino.ee{href}"
                        results.append({
                            "id": 0,
                            "title": title,
                            "category": categorize_title(title, href),
                            "store_name": "Notino",
                            "current_price": price_val,
                            "original_price": price_val,
                            "discount_percentage": 0,
                            "image_url": img,
                            "product_url": full_url,
                            "scraped_at": "Live External Search",
                            "is_fallback": True
                        })
    except Exception as e:
        print(f"⚠️ Live fallback search exception: {e}")

    return results


# --- SCHEMAS ---
class SuggestionItem(BaseModel):
    title: str = Field(..., examples=["Alma Piim 2.5% 1L"])
    category: str = Field(..., examples=["Dairy & Eggs"])
    price_formatted: str = Field(..., examples=["€0.79"])
    store: str = Field(..., examples=["Maxima EE"])

class AutocompleteResponse(BaseModel):
    query: str = Field(..., examples=["piim"])
    category_filter: Optional[str] = Field(None, examples=["Dairy & Eggs"])
    suggestions: List[SuggestionItem]

class BasketRequest(BaseModel):
    items: List[str] = Field(..., examples=[["Egg", "Milk", "Bread"]])

class StoreTotal(BaseModel):
    store_name: str = Field(..., examples=["Maxima EE"])
    total_formatted: str = Field(..., examples=["€2.38"])
    tier_tag: str = Field(..., examples=["Best"])
    tag_color: str = Field(..., examples=["green"])

class StrategyBanner(BaseModel):
    cheapest_store: str = Field(..., examples=["Maxima EE"])
    total_formatted: str = Field(..., examples=["€2.38"])
    savings_formatted: str = Field(..., examples=["Saved €0.82 vs Selver!"])

class BasketComparisonResponse(BaseModel):
    best_basket_strategy: StrategyBanner
    single_store_totals: List[StoreTotal]


# --- HEALTH CHECK ENDPOINT ---
@app.get("/", tags=["Health Check"])
def root():
    return {
        "status": "online",
        "service": "Tallinn Grocery, Beauty & Transport Backend",
        "swagger_docs": "http://127.0.0.1:8000/docs",
    }


# --- GROCERY ENDPOINTS ---
@app.get(
    "/api/groceries/categories",
    summary="Get Grocery Categories",
    tags=["Grocery Search"],
)
def get_grocery_categories():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT category FROM grocery_products WHERE category IS NOT NULL AND category != '' ORDER BY category ASC;"
    )
    categories = [r["category"] for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return {"categories": categories}


@app.get(
    "/api/groceries/autocomplete",
    response_model=AutocompleteResponse,
    summary="Search Autocomplete Suggestions",
    tags=["Grocery Search"],
)
def autocomplete_search(
    q: str = Query(
        ...,
        min_length=1,
        examples=["piim"],
        description="Search term (e.g. piim, leib)",
    ),
    category: Optional[str] = Query(
        None, examples=["Dairy & Eggs"], description="Optional category filter"
    ),
):
    conn = get_db()
    cursor = conn.cursor()

    where_clause = "WHERE (product_name ILIKE %s OR category ILIKE %s)"
    params = [f"%{q}%", f"%{q}%"]

    if category:
        where_clause += " AND category = %s"
        params.append(category)

    query_str = f"""
        SELECT DISTINCT ON (product_name) product_name, category, store_name, price 
        FROM grocery_products 
        {where_clause}
        ORDER BY product_name, price ASC 
        LIMIT 8;
    """

    cursor.execute(query_str, params)
    results = cursor.fetchall()
    cursor.close()
    conn.close()

    suggestions = [
        {
            "title": r["product_name"],
            "category": r["category"],
            "price_formatted": f"€{float(r['price']):.2f}",
            "store": r["store_name"],
        }
        for r in results
    ]

    return {"query": q, "category_filter": category, "suggestions": suggestions}


@app.post(
    "/api/basket/compare",
    response_model=BasketComparisonResponse,
    summary="Calculate Cheapest Supermarket Strategy",
    tags=["Basket Comparison Engine"],
)
def compare_basket(request: BasketRequest):
    if not request.items:
        raise HTTPException(
            status_code=400, detail="Shopping list cannot be empty"
        )

    conn = get_db()
    cursor = conn.cursor()

    store_totals = {}
    for item in request.items:
        cursor.execute(
            """
            SELECT store_name, price FROM grocery_products 
            WHERE product_name ILIKE %s OR category ILIKE %s 
            ORDER BY price ASC;
        """,
            (f"%{item}%", f"%{item}%"),
        )

        matches = cursor.fetchall()
        seen = set()

        for m in matches:
            store = m["store_name"]
            if store not in seen:
                store_totals[store] = store_totals.get(store, 0.0) + float(
                    m["price"]
                )
                seen.add(store)

    cursor.close()
    conn.close()

    if not store_totals:
        raise HTTPException(
            status_code=404,
            detail="No store matches found for items in your shopping list.",
        )

    sorted_stores = sorted(store_totals.items(), key=lambda x: x[1])
    cheapest_name, cheapest_price = sorted_stores[0]
    priciest_name, priciest_price = sorted_stores[-1]
    savings = round(priciest_price - cheapest_price, 2)

    rankings = []
    for idx, (store, total) in enumerate(sorted_stores):
        tag = (
            "Best"
            if idx == 0
            else "Mid" if idx in [1, 2] else "High" if idx == 3 else "Premium"
        )
        color = (
            "green"
            if idx == 0
            else "yellow"
            if idx in [1, 2]
            else "red"
            if idx == 3
            else "darkred"
        )

        rankings.append(
            {
                "store_name": store,
                "total_formatted": f"€{total:.2f}",
                "tier_tag": tag,
                "tag_color": color,
            }
        )

    return {
        "best_basket_strategy": {
            "cheapest_store": cheapest_name,
            "total_formatted": f"€{cheapest_price:.2f}",
            "savings_formatted": f"Saved €{savings:.2f} vs {priciest_name}!",
        },
        "single_store_totals": rankings,
    }


# --- BEAUTY ENDPOINTS ---
@app.get(
    "/beauty-products/categories",
    summary="Get Beauty Categories",
    tags=["Beauty Deals"],
)
def get_beauty_categories():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT category FROM beauty_products WHERE category IS NOT NULL AND category != '' ORDER BY category ASC;"
    )
    categories = [r["category"] for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return {"categories": categories}


@app.get(
    "/beauty-products/search",
    summary="Search DB First with Live Fallback",
    tags=["Beauty Deals"],
)
def search_beauty_products(
    q: str = Query(..., min_length=2, description="Product search term"),
    category: Optional[str] = Query(None, description="Optional category filter")
):
    conn = get_db()
    cursor = conn.cursor()
    
    where_clauses = ["(title ILIKE %s OR store_name ILIKE %s)"]
    params = [f"%{q}%", f"%{q}%"]

    if category and category.lower() != "all":
        where_clauses.append("category ILIKE %s")
        params.append(f"%{category}%")

    query_str = f"""
        SELECT id, title, category, store_name, current_price, original_price, discount_percentage, image_url, product_url, scraped_at
        FROM beauty_products
        WHERE {' AND '.join(where_clauses)}
        ORDER BY discount_percentage DESC, current_price ASC 
        LIMIT 50;
    """

    cursor.execute(query_str, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if rows:
        products = [
            {
                "id": r["id"],
                "title": r["title"],
                "category": r["category"],
                "store_name": r["store_name"],
                "current_price": float(r["current_price"]) if r["current_price"] else 0.0,
                "original_price": float(r["original_price"]) if r["original_price"] else 0.0,
                "discount_percentage": r["discount_percentage"],
                "image_url": r["image_url"],
                "product_url": r["product_url"],
                "scraped_at": str(r["scraped_at"]),
                "is_fallback": False
            }
            for r in rows
        ]
        return {"source": "database", "count": len(products), "products": products}

    # Fallback to live search if database yields 0 items
    fallback_items = live_search_fallback(q)
    return {
        "source": "live_fallback",
        "count": len(fallback_items),
        "products": fallback_items
    }


@app.get(
    "/beauty-products",
    summary="Get Discounted Beauty Products",
    tags=["Beauty Deals"],
)
def get_beauty_products(
    limit: int = 50, 
    store: Optional[str] = None, 
    category: Optional[str] = None
):
    conn = get_db()
    cursor = conn.cursor()
    
    where_clauses = []
    params = []

    if store:
        where_clauses.append("store_name ILIKE %s")
        params.append(f"%{store}%")

    if category:
        where_clauses.append("category ILIKE %s")
        params.append(f"%{category}%")

    where_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    params.append(limit)

    query_str = f"""
        SELECT id, title, category, store_name, current_price, original_price, discount_percentage, image_url, product_url, scraped_at
        FROM beauty_products
        {where_str}
        ORDER BY scraped_at DESC 
        LIMIT %s;
    """

    cursor.execute(query_str, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    products = [
        {
            "id": r["id"],
            "title": r["title"],
            "category": r["category"],
            "store_name": r["store_name"],
            "current_price": float(r["current_price"]) if r["current_price"] else 0.0,
            "original_price": float(r["original_price"]) if r["original_price"] else 0.0,
            "discount_percentage": r["discount_percentage"],
            "image_url": r["image_url"],
            "product_url": r["product_url"],
            "scraped_at": str(r["scraped_at"])
        }
        for r in rows
    ]
    return {"count": len(products), "products": products}


@app.get(
    "/beauty-products/stats",
    summary="Get Beauty Database Scrape Statistics",
    tags=["Beauty Deals"],
)
def get_beauty_stats():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT store_name, COUNT(*), MAX(scraped_at)
        FROM beauty_products
        GROUP BY store_name
        ORDER BY COUNT(*) DESC;
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return {
        "stores": [
            {
                "store": r["store_name"],
                "total_items": r["count"],
                "last_scraped": str(r["max"])
            }
            for r in rows
        ]
    }


# --- LINK & SOURCE HEALTH ENDPOINTS ---
@app.get(
    "/beauty-products/check-link",
    summary="Check Single Product Link Status",
    tags=["Link Health Checker"],
)
def check_single_link(url: str = Query(..., description="Product URL to test")):
    return check_url_status(url)


@app.get(
    "/beauty-products/store-health",
    summary="Get Target Store Websites Health Status",
    tags=["Link Health Checker"],
)
def check_stores_health():
    stores_to_check = {
        "Loverte": "https://www.loverte.com/et/eripakkumised",
        "MyLook": "https://www.mylook.ee/campaign",
        "Notino": "https://www.notino.ee/special-promo/",
        "IdeaalKosmeetika": "https://www.ideaalkosmeetika.ee/tooted-e-pood/",
        "Tradehouse": "https://tradehouse.ee/campaigns/summerhits"
    }
    
    results = []
    for store, target_url in stores_to_check.items():
        status = check_url_status(target_url)
        results.append({
            "store": store,
            "target_url": target_url,
            "is_online": status["is_online"],
            "status_code": status["status_code"],
            "status_label": status["status_label"],
            "badge_color": status["badge_color"]
        })
        
    return {"stores_health": results}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)