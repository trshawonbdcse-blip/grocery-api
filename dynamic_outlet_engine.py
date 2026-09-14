import math
import httpx

# In-memory local fallback dataset for Tallinn's major shopping malls
TALLINN_MALLS_FALLBACK = [
    {"name": "Viru Keskus", "lat": 59.4365, "lon": 24.7550},
    {"name": "Kristiine Keskus", "lat": 59.4272, "lon": 24.7231},
    {"name": "Ülemiste Keskus", "lat": 59.4221, "lon": 24.7938},
    {"name": "Rocca al Mare Keskus", "lat": 59.4270, "lon": 24.6475},
    {"name": "T1 Keskus", "lat": 59.4239, "lon": 24.7932},
    {"name": "Solaris Keskus", "lat": 59.4344, "lon": 24.7508},
    {"name": "Nautica Keskus", "lat": 59.4398, "lon": 24.7645},
    {"name": "Mustamäe Keskus", "lat": 59.4086, "lon": 24.6936},
    {"name": "Magistrali Keskus", "lat": 59.4005, "lon": 24.7001},
    {"name": "Järve Keskus", "lat": 59.3942, "lon": 24.7214},
    {"name": "Postimaja Keskus", "lat": 59.4372, "lon": 24.7547},
    {"name": "Arsenal Keskus", "lat": 59.4528, "lon": 24.7431}
]

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0  # Earth radius in KM
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def fetch_malls_by_radius(user_lat: float, user_lon: float, radius_km: float = 5.0) -> list:
    """Queries OpenStreetMap Overpass endpoints with fallback to local dataset on timeout."""
    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.private.coffee/api/interpreter"
    ]
    
    # Check bounding box
    bbox_delta = radius_km / 111.0
    south, north = user_lat - bbox_delta, user_lat + bbox_delta
    west, east = user_lon - bbox_delta, user_lon + bbox_delta

    query = f"""
    [out:json][timeout:8];
    (
      nwr["shop"="mall"]({south:.4f},{west:.4f},{north:.4f},{east:.4f});
    );
    out center;
    """

    headers = {"User-Agent": "TallinnOutletEngine/3.0"}
    malls = []

    for ep in endpoints:
        try:
            res = httpx.post(ep, data={"data": query}, headers=headers, timeout=6.0)
            if res.status_code == 200:
                elements = res.json().get("elements", [])
                for el in elements:
                    tags = el.get("tags", {})
                    name = tags.get("name")
                    lat = el.get("lat") or el.get("center", {}).get("lat")
                    lon = el.get("lon") or el.get("center", {}).get("lon")
                    if name and lat and lon:
                        dist = haversine(user_lat, user_lon, lat, lon)
                        if dist <= radius_km:
                            malls.append({
                                "name": name,
                                "lat": lat,
                                "lon": lon,
                                "distance_km": round(dist, 2),
                                "distance_label": f"{dist:.1f} km away"
                            })
                if malls:
                    return malls
        except Exception:
            continue

    # --- FALLBACK IF OVERPASS SERVERS ARE DOWN ---
    print("⚠️ Overpass API servers offline/timed out. Falling back to local Tallinn mall dataset...")
    for mall in TALLINN_MALLS_FALLBACK:
        dist = haversine(user_lat, user_lon, mall["lat"], mall["lon"])
        if dist <= radius_km:
            malls.append({
                "name": mall["name"],
                "lat": mall["lat"],
                "lon": mall["lon"],
                "distance_km": round(dist, 2),
                "distance_label": f"{dist:.1f} km away"
            })

    return sorted(malls, key=lambda x: x["distance_km"])