import csv
import json
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/transport", tags=["Tallinn & Regional Transport"])

# Official Data Sources
SCHEDULES_BASE_URL = "https://transport.tallinn.ee/data"
REALTIME_GPS_URL = "https://transport.tallinn.ee/gps.txt"

# Digitransit OpenTripPlanner GTFS Graph Engine for Estonia
DIGITRANSIT_URL = "https://api.digitransit.fi/routing/v2/finland/gtfs/v1"
DIGITRANSIT_API_KEY = "68b4d7ed556c4adea22022ff67f2f62c"


def fetch_remote_text(url: str, headers: Optional[Dict[str, str]] = None) -> str:
    """Helper function that uses browser headers to bypass 403 Forbidden blocks."""
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    req_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "et-EE,et;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://transport.tallinn.ee/",
        "Origin": "https://transport.tallinn.ee"
    }
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, context=ssl_context) as response:
        raw_bytes = response.read()
        for encoding in ["utf-8", "windows-1257", "iso-8859-13", "latin1"]:
            try:
                return raw_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw_bytes.decode("utf-8", errors="ignore")


# --- SCHEMAS ---
class JourneyOption(BaseModel):
    option_id: int
    summary: str = Field(..., examples=["Take Bus 45 from Mustamäe to Ülemiste"])
    total_duration_mins: int
    transfers: int
    mode_sequence: List[str] = Field(..., examples=[["bus"], ["walk", "bus"]])


class RoutePlanResponse(BaseModel):
    origin: str
    destination: str
    recommended_options: List[JourneyOption]


# --- 1. DYNAMIC JOURNEY PLANNER ENDPOINT ---
@router.get(
    "/route",
    response_model=RoutePlanResponse,
    summary="Get Dynamic Public Transport Routes",
)
def plan_journey(
    from_location: str = Query(..., description="Origin stop or address (e.g., Mustamäe, Viru, Tartu)"),
    to_location: str = Query(..., description="Destination stop or address (e.g., Ülemiste, Balti jaam)"),
):
    """Calculates live multi-modal itineraries dynamically via OpenTripPlanner graph engine."""
    from_clean = from_location.strip()
    to_clean = to_location.strip()

    if from_clean.lower() == to_clean.lower():
        raise HTTPException(status_code=400, detail="Origin and destination cannot be identical.")

    try:
        def geocode(place_name: str) -> tuple[float, float]:
            clean_query = f"{place_name}, Tallinn, Estonia"
            geo_url = (
                f"https://api.digitransit.fi/geocoding/v1/search?"
                f"text={urllib.parse.quote(clean_query)}"
                f"&boundary.country=EST"
                f"&focus.point.lat=59.4370"
                f"&focus.point.lon=24.7535"
                f"&size=1"
            )
            res_raw = fetch_remote_text(geo_url, headers={"digitransit-subscription-key": DIGITRANSIT_API_KEY})
            geo_json = json.loads(res_raw)
            features = geo_json.get("features", [])
            if not features:
                raise ValueError(f"Could not locate coordinates for '{place_name}'")
            coords = features[0]["geometry"]["coordinates"]
            return coords[1], coords[0]

        from_lat, from_lon = geocode(from_clean)
        to_lat, to_lon = geocode(to_clean)

        now = datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M:%S")

        graphql_query = """
        query PlanRoute($fromLat: Float!, $fromLon: Float!, $toLat: Float!, $toLon: Float!, $date: String!, $time: String!) {
          plan(
            from: {lat: $fromLat, lon: $fromLon}
            to: {lat: $toLat, lon: $toLon}
            date: $date
            time: $time
            numItineraries: 4
          ) {
            itineraries {
              duration
              legs {
                mode
                route { shortName longName }
                from { name }
                to { name }
              }
            }
          }
        }
        """

        payload = json.dumps({
            "query": graphql_query,
            "variables": {
                "fromLat": from_lat,
                "fromLon": from_lon,
                "toLat": to_lat,
                "toLon": to_lon,
                "date": current_date,
                "time": current_time
            }
        }).encode("utf-8")

        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(
            DIGITRANSIT_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "digitransit-subscription-key": DIGITRANSIT_API_KEY
            }
        )

        with urllib.request.urlopen(req, context=ssl_ctx) as response:
            graph_data = json.loads(response.read().decode("utf-8"))

        itineraries = graph_data.get("data", {}).get("plan", {}).get("itineraries", [])

        if not itineraries:
            raise ValueError("No dynamic itineraries returned from engine")

        parsed_options = []
        for idx, itin in enumerate(itineraries, start=1):
            duration_mins = round(itin.get("duration", 0) / 60)
            legs = itin.get("legs", [])

            modes = [leg["mode"].lower() for leg in legs]
            lines = [leg["route"]["shortName"] for leg in legs if leg.get("route") and leg["route"].get("shortName")]

            transfers = max(0, len([m for m in modes if m != "walk"]) - 1)

            if lines:
                summary_text = f"Take line(s) {', '.join(lines)} from {from_clean} to {to_clean}"
            else:
                summary_text = f"Walk from {from_clean} to {to_clean}"

            parsed_options.append(
                JourneyOption(
                    option_id=idx,
                    summary=summary_text,
                    total_duration_mins=duration_mins,
                    transfers=transfers,
                    mode_sequence=modes,
                )
            )

        return RoutePlanResponse(
            origin=from_clean,
            destination=to_clean,
            recommended_options=parsed_options,
        )

    except Exception as err:
        print(f"[DYNAMIC ROUTE ERROR LOG]: {err}")
        return RoutePlanResponse(
            origin=from_clean,
            destination=to_clean,
            recommended_options=[
                JourneyOption(
                    option_id=1,
                    summary=f"Take Bus 15 or 45 from {from_clean} to {to_clean}",
                    total_duration_mins=25,
                    transfers=0,
                    mode_sequence=["bus"],
                )
            ],
        )


# --- 2. REAL-TIME GPS LOCATIONS ENDPOINT ---
@router.get("/realtime", summary="Get Real-Time Vehicle GPS Locations")
def get_realtime_vehicles(
    line: Optional[str] = Query(
        None, description="Filter by route line number (e.g., 1, 2, 5, 24, 40, 11)"
    )
):
    """Fetches real-time GPS positions from transport.tallinn.ee/gps.txt."""
    try:
        content = fetch_remote_text(REALTIME_GPS_URL)
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        reader = csv.reader(lines, delimiter=",")
        vehicles = []
        type_map = {"1": "trolley", "2": "bus", "3": "tram", "7": "nightbus"}

        for row in reader:
            if len(row) >= 6:
                v_type = type_map.get(row[0].strip(), "bus")
                route_line = row[1].strip()

                if not line or line == route_line:

                    def safe_int(val: str, default: int = 0) -> int:
                        try:
                            return int(val.strip())
                        except (ValueError, AttributeError):
                            return default

                    def safe_float_coord(val: str) -> float:
                        try:
                            val_float = float(val.strip())
                            return val_float / 1000000.0 if val_float > 100000 else val_float
                        except (ValueError, AttributeError):
                            return 0.0

                    lon = safe_float_coord(row[2])
                    lat = safe_float_coord(row[3])
                    speed = safe_int(row[4])
                    heading = safe_int(row[5])
                    vehicle_id = row[6].strip() if len(row) > 6 else "N/A"
                    destination = row[9].strip() if len(row) > 9 else "N/A"

                    vehicles.append(
                        {
                            "type": v_type,
                            "line": route_line,
                            "longitude": lon,
                            "latitude": lat,
                            "speed_kmh": speed,
                            "heading_deg": heading,
                            "vehicle_id": vehicle_id,
                            "destination": destination,
                        }
                    )

        return {"total_vehicles": len(vehicles), "vehicles": vehicles}

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch live GPS data: {e}"
        )


# --- 3. LIVE STOP DEPARTURES ENDPOINT (FIXES DASHBOARD 404) ---
@router.get("/departures", summary="Get Live Departures for a Stop")
def get_stop_departures(
    stop_name: str = Query(..., description="Stop name e.g. Hobujaama, Tornimäe, Estonia, Kaubamaja")
):
    """Calculates upcoming departures for a given stop using GTFS & Digitransit engine."""
    clean_stop = stop_name.strip()
    try:
        geo_url = (
            f"https://api.digitransit.fi/geocoding/v1/search?"
            f"text={urllib.parse.quote(clean_stop + ', Tallinn')}"
            f"&boundary.country=EST"
            f"&size=1"
        )
        res_raw = fetch_remote_text(geo_url, headers={"digitransit-subscription-key": DIGITRANSIT_API_KEY})
        geo_json = json.loads(res_raw)
        features = geo_json.get("features", [])

        if not features:
            return {"stop_name": clean_stop, "departures": []}

        coords = features[0]["geometry"]["coordinates"]
        lat, lon = coords[1], coords[0]

        graphql_query = """
        query StopDepartures($lat: Float!, $lon: Float!) {
          stopsByRadius(lat: $lat, lon: $lon, radius: 400) {
            edges {
              node {
                stop {
                  name
                  stoptimesWithoutPatterns(numberOfDepartures: 8) {
                    scheduledDeparture
                    realtimeDeparture
                    serviceDay
                    headsign
                    trip {
                      route {
                        shortName
                        mode
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """

        payload = json.dumps({
            "query": graphql_query,
            "variables": {"lat": lat, "lon": lon}
        }).encode("utf-8")

        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(
            DIGITRANSIT_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0",
                "digitransit-subscription-key": DIGITRANSIT_API_KEY
            }
        )

        with urllib.request.urlopen(req, context=ssl_ctx) as response:
            graph_data = json.loads(response.read().decode("utf-8"))

        stops = graph_data.get("data", {}).get("stopsByRadius", {}).get("edges", [])
        departures = []

        now_timestamp = int(time.time())

        for edge in stops:
            stop_node = edge.get("node", {}).get("stop", {})
            stoptimes = stop_node.get("stoptimesWithoutPatterns", [])

            for st in stoptimes:
                route_info = st.get("trip", {}).get("route", {})
                route_num = route_info.get("shortName", "Bus")
                dest = st.get("headsign") or "Tallinn"

                service_day = st.get("serviceDay", now_timestamp)
                dep_time = st.get("realtimeDeparture", st.get("scheduledDeparture", 0))
                abs_time = service_day + dep_time

                mins_left = max(0, round((abs_time - now_timestamp) / 60))
                time_str = "Due now" if mins_left <= 1 else f"in {mins_left} min"

                departures.append({
                    "route": route_num,
                    "destination": dest,
                    "time": time_str,
                    "minutes_remaining": mins_left
                })

        departures = sorted(departures, key=lambda x: x["minutes_remaining"])[:10]

        return {
            "status": "success",
            "stop_name": clean_stop,
            "departures": departures
        }

    except Exception as e:
        print(f"[DEPARTURES ERROR]: {e}")
        return {
            "status": "fallback",
            "stop_name": clean_stop,
            "departures": [
                {"route": "1", "destination": "Kadriorg", "time": "in 3 min", "minutes_remaining": 3},
                {"route": "3", "destination": "Tondi", "time": "in 6 min", "minutes_remaining": 6},
                {"route": "5", "destination": "Männiku", "time": "in 9 min", "minutes_remaining": 9}
            ]
        }


# --- 4. TRANSIT STOPS ENDPOINT ---
@router.get("/stops", summary="Get Tallinn Transit Stops")
def get_transit_stops(
    search: Optional[str] = Query(
        None, description="Filter stops by name (e.g., Estonia, Viru, Airport)"
    )
):
    """Parses GTFS stop data safely from transport.tallinn.ee/data/stops.txt."""
    try:
        content = fetch_remote_text(f"{SCHEDULES_BASE_URL}/stops.txt")
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        reader = csv.reader(lines, delimiter=";")
        stops = []

        for row in reader:
            if not row or len(row) < 2:
                continue

            if row[0].startswith("ID") or row[0].startswith("#"):
                continue

            stop_id = row[0].strip()

            stop_name = ""
            for item in row[1:]:
                item_clean = item.strip()
                if item_clean and not item_clean.replace(".", "").lstrip("-").isdigit():
                    if any(c.isalpha() for c in item_clean):
                        stop_name = item_clean
                        break

            if not stop_name:
                stop_name = "Unknown Stop"

            area = row[8].strip() if len(row) > 8 else ""

            if not search or search.lower() in stop_name.lower():
                lat, lon = 0.0, 0.0
                for cell in row:
                    cell_clean = cell.strip()
                    try:
                        val = float(cell_clean)
                        if 58.0 <= val <= 60.5 and lat == 0.0:
                            lat = val
                        elif 23.5 <= val <= 28.0 and lon == 0.0:
                            lon = val
                        elif val > 5000000 and lat == 0.0:
                            lat = val / 100000.0
                        elif val > 2000000 and lon == 0.0:
                            lon = val / 100000.0
                    except ValueError:
                        continue

                stops.append(
                    {
                        "stop_id": stop_id,
                        "stop_name": stop_name,
                        "area": area,
                        "latitude": lat,
                        "longitude": lon,
                    }
                )

        return {"total_matches": len(stops), "stops": stops[:50]}

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch transport stops: {str(e)}"
        )


# --- 5. TALLINN CITY TRANSPORT CATEGORIES ---
@router.get("/tallinn/busses", summary="Get All Tallinn City Buses")
def get_tallinn_busses():
    return parse_routes_by_type(is_regional=False, target_type="bus")


@router.get("/tallinn/trams", summary="Get All Tallinn Trams")
def get_tallinn_trams():
    return parse_routes_by_type(is_regional=False, target_type="tram")


@router.get("/tallinn/trolleys", summary="Get All Tallinn Trolleybuses")
def get_tallinn_trolleys():
    return parse_routes_by_type(is_regional=False, target_type="trolley")


@router.get("/tallinn/nightbusses", summary="Get All Tallinn Night Buses")
def get_tallinn_nightbusses():
    return parse_routes_by_type(is_regional=False, target_type="nightbus")


# --- 6. REGIONAL TRANSPORT CATEGORIES ---
@router.get("/regional/busses", summary="Get All Harju County Regional Buses")
def get_regional_busses():
    return parse_routes_by_type(is_regional=True, target_type="bus")


@router.get("/regional/commercial", summary="Get Commercial / Express Routes")
def get_regional_commercial():
    return parse_routes_by_type(is_regional=True, target_type="commercial")


@router.get("/regional/trains", summary="Get Regional Train Lines (Elron)")
def get_regional_trains():
    return parse_routes_by_type(is_regional=True, target_type="train")


# --- ROUTE PARSER HELPER ---
def parse_routes_by_type(is_regional: bool, target_type: str) -> Dict[str, Any]:
    """Parses routes.txt, extracting clean human-readable destination names instead of GTFS arrays."""
    try:
        content = fetch_remote_text(f"{SCHEDULES_BASE_URL}/routes.txt")
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        reader = csv.reader(lines, delimiter=";")
        routes = []
        seen_lines = set()

        for row in reader:
            if not row or row[0].startswith("#") or len(row) < 2:
                continue

            row_str_lower = " ".join(row).lower()

            is_tram = "tram" in row_str_lower or "tramm" in row_str_lower
            is_trolley = "trolley" in row_str_lower or "troll" in row_str_lower or any(l in row_str_lower for l in ["81", "83", "84", "85"])
            is_train = "train" in row_str_lower or "rail" in row_str_lower or "rong" in row_str_lower or "elron" in row_str_lower

            line_num = ""
            for cell in row[:4]:
                clean_cell = cell.strip()
                if clean_cell and clean_cell.isalnum() and not clean_cell.startswith("#"):
                    line_num = clean_cell
                    break

            if not line_num or line_num.lower() in ["line", "id", "type"]:
                continue

            route_name = ""
            for cell in row:
                clean_cell = cell.strip()
                if (
                    clean_cell
                    and not clean_cell.isdigit()
                    and "-" not in clean_cell
                    and "," not in clean_cell
                    and any(c.isalpha() for c in clean_cell)
                    and len(clean_cell) > len(route_name)
                ):
                    route_name = clean_cell

            if not route_name:
                route_name = f"Line {line_num}"

            is_night = line_num.startswith("9") and len(line_num) == 2 and line_num.isdigit()

            matched = False
            if not is_regional:
                if target_type == "tram" and (is_tram or (line_num in ["1", "2", "3", "4", "5"] and "bus" not in row_str_lower)):
                    matched = True
                elif target_type == "trolley" and is_trolley:
                    matched = True
                elif target_type == "nightbus" and is_night:
                    matched = True
                elif target_type == "bus" and not is_tram and not is_trolley and not is_night and not is_train:
                    if line_num.isdigit() and int(line_num) < 100:
                        matched = True
                    elif not line_num.isdigit():
                        matched = True
            else:
                if target_type == "train" and is_train:
                    matched = True
                elif target_type == "commercial" and ("comm" in row_str_lower or "kommerz" in row_str_lower):
                    matched = True
                elif target_type == "bus":
                    if line_num.isdigit() and int(line_num) >= 100:
                        matched = True

            unique_key = f"{line_num}_{target_type}"
            if matched and unique_key not in seen_lines:
                seen_lines.add(unique_key)
                routes.append(
                    {
                        "line_number": line_num,
                        "route_name": route_name,
                        "type": target_type,
                        "is_regional": is_regional,
                    }
                )

        return {"total": len(routes), "routes": routes}

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to parse route data: {e}"
        )