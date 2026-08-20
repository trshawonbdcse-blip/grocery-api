import os
from typing import List, Optional
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
    version="1.4.0",
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)