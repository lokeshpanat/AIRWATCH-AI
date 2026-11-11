import os, sqlite3, math, time
from datetime import datetime, timezone
from flask import Flask, jsonify, request, render_template
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
from ml_model import predict_demo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))

app = Flask(__name__)
DB = os.path.join(os.path.dirname(__file__), "airwatch.db")
OPENAQ_API_KEY = os.getenv("OPENAQ_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()
GEMINI_FALLBACK_MODELS = [
    item.strip() for item in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite").split(",")
    if item.strip()
]
GEMINI_LAST_ERROR = "No Gemini request has been tested in this server session."

# Reuse a session and retry transient TLS/network/provider errors. Certificate
# verification remains enabled; never use verify=False as an SSL workaround.
_retry = Retry(
    total=3, connect=3, read=2, status=2,
    backoff_factor=0.7,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "POST"]),
    respect_retry_after_header=True,
)
http = requests.Session()
_adapter = HTTPAdapter(max_retries=_retry, pool_connections=20, pool_maxsize=20)
http.mount("https://", _adapter)
http.mount("http://", _adapter)

# Gemini requests use a separate session with zero adapter retries; the route
# controls the single short retry explicitly, avoiding hidden long waits.
gemini_http = requests.Session()
gemini_adapter = HTTPAdapter(max_retries=0, pool_connections=4, pool_maxsize=4)
gemini_http.mount("https://", gemini_adapter)

def init_db():
    with sqlite3.connect(DB) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS predictions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT,
            city TEXT, pm25 REAL, pm10 REAL, no2 REAL, o3 REAL, predicted_aqi REAL, category TEXT)""")

def category(aqi):
    if aqi <= 50: return "Good"
    if aqi <= 100: return "Satisfactory"
    if aqi <= 200: return "Moderate"
    if aqi <= 300: return "Poor"
    if aqi <= 400: return "Very Poor"
    return "Severe"

# CPCB-style breakpoint interpolation for commonly used pollutants.
BREAKPOINTS = {
 "pm25":[(0,30,0,50),(31,60,51,100),(61,90,101,200),(91,120,201,300),(121,250,301,400),(251,500,401,500)],
 "pm10":[(0,50,0,50),(51,100,51,100),(101,250,101,200),(251,350,201,300),(351,430,301,400),(431,600,401,500)],
 "no2":[(0,40,0,50),(41,80,51,100),(81,180,101,200),(181,280,201,300),(281,400,301,400),(401,1000,401,500)],
 "so2":[(0,40,0,50),(41,80,51,100),(81,380,101,200),(381,800,201,300),(801,1600,301,400),(1601,2000,401,500)],
 "co":[(0,1,0,50),(1.1,2,51,100),(2.1,10,101,200),(10.1,17,201,300),(17.1,34,301,400),(34.1,50,401,500)],
 "o3":[(0,50,0,50),(51,100,51,100),(101,168,101,200),(169,208,201,300),(209,748,301,400),(749,1000,401,500)]
}
def sub_index(p, value):
    if value is None: return None
    for lo, hi, ilo, ihi in BREAKPOINTS[p]:
        if lo <= value <= hi:
            return round((ihi-ilo)/(hi-lo)*(value-lo)+ilo)
    return None

def calculate_aqi(values):
    # AQI is the maximum valid pollutant sub-index; official CPCB calculation
    # also has pollutant-specific averaging windows and minimum data sufficiency.
    indices = [sub_index(k, values.get(k)) for k in BREAKPOINTS]
    valid = [x for x in indices if x is not None]
    return max(valid) if valid else None

@app.route("/")
def home():
    return render_template("index.html")


def resolve_location_args():
    """Return coordinates and a display label from browser GPS or a typed city."""
    lat = request.args.get("lat")
    lon = request.args.get("lon")
    if lat is not None and lon is not None:
        try:
            lat_f, lon_f = float(lat), float(lon)
            if not (-90 <= lat_f <= 90 and -180 <= lon_f <= 180):
                raise ValueError()
            return lat_f, lon_f, request.args.get("label", "Your current location"), ""
        except ValueError:
            raise ValueError("Invalid latitude/longitude")
    city = request.args.get("city", "Delhi")
    geo = http.get("https://geocoding-api.open-meteo.com/v1/search",
                       params={"name": city, "count": 1, "language": "en", "format": "json"},
                       timeout=10).json()
    if not geo.get("results"):
        raise LookupError("City not found")
    place = geo["results"][0]
    return place["latitude"], place["longitude"], place["name"], place.get("country", "")


@app.get("/api/reverse-geocode")
def reverse_geocode():
    # Called only after the user explicitly clicks the live-location button.
    try:
        lat, lon = float(request.args["lat"]), float(request.args["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError()
        r = http.get("https://nominatim.openstreetmap.org/reverse",
            params={"lat":lat,"lon":lon,"format":"jsonv2","zoom":18,"addressdetails":1},
            headers={"User-Agent":"AirWatchAI-StudentProject/1.0 contact: project-owner"},
            timeout=12)
        r.raise_for_status()
        d = r.json()
        return jsonify({"address":d.get("display_name","Address unavailable"),
                        "latitude":lat,"longitude":lon,
                        "source":"© OpenStreetMap contributors"})
    except (KeyError, ValueError, requests.RequestException):
        return jsonify({"error":"Address lookup unavailable; GPS coordinates are still available."}), 502

@app.get("/api/weather")
def weather():
    try:
        lat, lon, label, country = resolve_location_args()
        data = http.get("https://api.open-meteo.com/v1/forecast",
            params={"latitude":lat,"longitude":lon,
                    "current":"temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m,wind_direction_10m",
                    "hourly":"temperature_2m,precipitation_probability",
                    "forecast_days":1,"timezone":"auto"}, timeout=10).json()
        return jsonify({"city":label,"country":country,"current":data.get("current",{}),
                        "hourly":data.get("hourly",{}),"source":"Open-Meteo",
                        "updated_at":datetime.now(timezone.utc).isoformat()})
    except requests.exceptions.SSLError:
        return jsonify({"error":"Secure connection to the weather provider failed after retries. Check your internet connection, VPN/proxy or antivirus HTTPS scanning, then refresh. Certificate checks are still enabled."}), 502
    except requests.RequestException:
        return jsonify({"error":"Weather provider could not be reached after automatic retries. Check your internet connection and try again in a moment."}), 502
    except ValueError as e:
        return jsonify({"error":str(e) or "Invalid location"}), 400
    except LookupError as e:
        return jsonify({"error":str(e)}), 404


@app.get("/api/air-quality-live")
def air_quality_live():
    try:
        lat, lon, label, country = resolve_location_args()
        params = {"latitude":lat, "longitude":lon,
                  "current":"us_aqi,pm2_5,pm10,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone",
                  "timezone":"auto"}
        data = http.get("https://air-quality-api.open-meteo.com/v1/air-quality",
                            params=params, timeout=15).json()
        current = data.get("current")
        if not current or current.get("us_aqi") is None:
            return jsonify({"error":"Air-quality model has no current result for this location"}), 502
        aqi = int(current["us_aqi"])
        if aqi <= 50:
            level, color = "Good", "good"
            advice = ["Enjoy normal outdoor activities.", "Keep rooms ventilated when outdoor conditions are comfortable."]
            manage = ["Continue regular cleaning to reduce indoor dust.", "Avoid unnecessary vehicle idling and burning waste."]
        elif aqi <= 100:
            level, color = "Moderate", "moderate"
            advice = ["Unusually sensitive people may reduce prolonged or heavy outdoor exertion.", "Most people can continue normal activities."]
            manage = ["Close windows during nearby smoke or traffic peaks.", "Prefer walking routes away from busy roads."]
        elif aqi <= 150:
            level, color = "Unhealthy for sensitive groups", "sensitive"
            advice = ["Children, older adults and people with asthma or heart/lung disease should reduce prolonged outdoor exertion.", "Keep prescribed medicines available and follow your clinician's advice."]
            manage = ["Choose indoor exercise instead of outdoor running.", "Use a well-fitted N95/KN95 outdoors if exposure cannot be avoided."]
        elif aqi <= 200:
            level, color = "Unhealthy", "unhealthy"
            advice = ["Everyone should reduce prolonged or heavy outdoor exertion.", "Sensitive groups should avoid outdoor exertion."]
            manage = ["Keep windows closed when outdoor air is polluted.", "Use a correctly sized HEPA air cleaner indoors if available.", "Wear a well-fitted N95/KN95 if you must go outside."]
        elif aqi <= 300:
            level, color = "Very Unhealthy", "very-unhealthy"
            advice = ["Avoid outdoor exercise and reduce time outside.", "Sensitive groups should remain indoors in cleaner air."]
            manage = ["Run a HEPA air cleaner in a closed room if available.", "Use recirculation mode in vehicles and avoid traffic-heavy routes.", "Wear a well-fitted N95/KN95 for essential outdoor trips."]
        else:
            level, color = "Hazardous", "hazardous"
            advice = ["Avoid outdoor activity; stay in a cleaner indoor environment.", "Follow local public-health and emergency advisories."]
            manage = ["Keep doors and windows closed; use HEPA filtration if available.", "Avoid indoor sources such as smoking, candles and frying.", "Seek medical help for severe breathlessness, chest pain or worsening symptoms."]
        pollutants = {"PM2.5":current.get("pm2_5"),"PM10":current.get("pm10"),
                      "CO":current.get("carbon_monoxide"),"NO2":current.get("nitrogen_dioxide"),
                      "SO2":current.get("sulphur_dioxide"),"O3":current.get("ozone")}
        return jsonify({"status":"available","city":label,"country":country,"aqi":aqi,
            "category":level,"category_class":color,"pollutants":pollutants,
            "timestamp":current.get("time"),"source":"Open-Meteo Air Quality API / CAMS atmospheric composition model",
            "aqi_scale":"US AQI (modelled estimate)","advice":advice,"manage":manage,
            "limitations":"This is a gridded model estimate for your browser-provided location, not a nearby CPCB monitoring-station reading. It is US AQI, not official Indian CPCB AQI."})
    except (requests.RequestException, ValueError) as e:
        return jsonify({"error":str(e) or "Air-quality provider is temporarily unavailable"}),502
    except LookupError as e:
        return jsonify({"error":str(e)}),404



@app.get("/api/openaq-status")
def openaq_status():
    """Safe diagnostic: never returns the API key."""
    key = os.getenv("OPENAQ_API_KEY", "").strip()
    return jsonify({
        "configured": bool(key),
        "key_length": len(key),
        "message": "OpenAQ key loaded by Flask backend." if key else
                   "No key loaded. Add OPENAQ_API_KEY to the .env file beside app.py, then restart Flask."
    })

@app.get("/api/nearest-station")
def nearest_station():
    """Find the closest OpenAQ location within 25 km and fetch its latest readings."""
    key = os.getenv("OPENAQ_API_KEY", "").strip()
    if not key:
        return jsonify({"status":"key_required",
            "message":"OpenAQ API key is not loaded. Add it to .env beside app.py and restart Flask.",
            "radius_km":25}), 200
    try:
        lat=float(request.args["lat"]); lon=float(request.args["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError()
        headers={"X-API-Key":key,"Accept":"application/json"}
        # OpenAQ supports coordinates=lat,lon and radius<=25000.
        # Its locations order_by only supports 'id', not 'distance'.
        loc_resp=http.get("https://api.openaq.org/v3/locations",
            params={"coordinates":f"{lat:.4f},{lon:.4f}",
                    "radius":25000,"limit":100,"page":1},
            headers=headers,timeout=20)
        if loc_resp.status_code in (401,403):
            return jsonify({"status":"auth_error","message":
                f"OpenAQ rejected the API key (HTTP {loc_resp.status_code})."}),200
        if loc_resp.status_code == 429:
            return jsonify({"status":"rate_limited","message":"OpenAQ rate limit reached. Wait and retry."}),200
        loc_resp.raise_for_status()
        locations=loc_resp.json().get("results",[])
        if not locations:
            return jsonify({"status":"no_station",
                "message":"No OpenAQ station was found within 25 km of this GPS point.",
                "radius_km":25}),200

        # API returns distance in meters for geospatial location results.
        locations=sorted(locations,key=lambda x:
            x.get("distance") if x.get("distance") is not None else float("inf"))
        chosen=locations[0]
        location_id=chosen.get("id")
        if not location_id:
            return jsonify({"status":"api_error","message":"OpenAQ returned a location without an ID."}),200

        # Fetch sensors explicitly; don't assume the /locations list embeds them.
        sensors_resp=http.get(
            f"https://api.openaq.org/v3/locations/{location_id}/sensors",
            params={"limit":100,"page":1},headers=headers,timeout=20)
        sensors_resp.raise_for_status()
        sensors=sensors_resp.json().get("results",[])
        sensor_map={}
        for sensor in sensors:
            param=sensor.get("parameter") or {}
            sensor_map[sensor.get("id")]={
                "parameter":param.get("name") or param.get("displayName") or "unknown",
                "units":param.get("units") or ""
            }

        latest_resp=http.get(
            f"https://api.openaq.org/v3/locations/{location_id}/latest",
            params={"limit":100,"page":1},headers=headers,timeout=20)
        latest_resp.raise_for_status()
        latest=latest_resp.json().get("results",[])
        readings=[]
        for item in latest:
            meta=sensor_map.get(item.get("sensorsId"),{})
            dt=item.get("datetime") or {}
            readings.append({
                "parameter":meta.get("parameter","unknown"),
                "value":item.get("value"),"unit":meta.get("units",""),
                "datetime":dt.get("local") or dt.get("utc"),
                "sensor_id":item.get("sensorsId")
            })
        distance=chosen.get("distance")
        return jsonify({"status":"available","station":{
            "id":location_id,"name":chosen.get("name"),
            "city":chosen.get("locality") or chosen.get("city"),
            "distance_m":distance,"coordinates":chosen.get("coordinates"),
            "last_updated":chosen.get("datetimeLast")},
            "readings":readings,"source":"OpenAQ",
            "note":"These are the nearest station's reported sensor measurements, not measurements at the exact GPS point. Check timestamps and pollutant coverage."}),200
    except (KeyError,ValueError):
        return jsonify({"status":"error","message":"Valid GPS coordinates are required."}),400
    except requests.HTTPError as e:
        code=e.response.status_code if e.response is not None else "unknown"
        # Return provider response detail where safe, without headers/secrets.
        detail=""
        try:
            payload=e.response.json()
            detail=str(payload.get("detail",""))[:500]
        except Exception:
            pass
        return jsonify({"status":"api_error",
            "message":f"OpenAQ returned HTTP {code}. {detail}".strip()}),200
    except requests.RequestException:
        return jsonify({"status":"network_error",
            "message":"Could not reach OpenAQ. Check internet and retry."}),200
    except (TypeError,ValueError):
        return jsonify({"status":"api_error",
            "message":"OpenAQ returned an unexpected response format."}),200

@app.get("/api/air-quality")
def air_quality():
    city = request.args.get("city","Delhi")
    if not OPENAQ_API_KEY:
        return jsonify({"status":"unavailable","message":"Add OPENAQ_API_KEY on the server to enable OpenAQ readings. No live pollution values are being fabricated.","source":"OpenAQ"})
    try:
        headers={"X-API-Key":OPENAQ_API_KEY}
        # Search monitoring locations; API key is only sent server-side.
        locs=http.get("https://api.openaq.org/v3/locations",
            params={"city":city,"limit":5},headers=headers,timeout=12).json()
        return jsonify({"status":"connected","locations":locs.get("results",[]),"source":"OpenAQ",
                        "message":"Locations retrieved. Select a station to retrieve its latest measurements."})
    except requests.RequestException:
        return jsonify({"status":"error","message":"OpenAQ request failed","source":"OpenAQ"}),502

@app.post("/api/predict")
def predict():
    body=request.get_json(force=True)
    required=["pm25","pm10","no2","o3"]
    try:
        vals={k:float(body[k]) for k in required}
        weather_vals={k:float(body.get(k,0)) for k in ["temperature","humidity","wind_speed","rainfall"]}
    except (KeyError,TypeError,ValueError):
        return jsonify({"error":"Enter valid numeric values for PM2.5, PM10, NO2 and O3."}),400
    aqi=calculate_aqi({**vals,"so2":body.get("so2"),"co":body.get("co")})
    # Demo estimate is explicitly labelled; AQI from pollutant subindices is shown separately.
    model=predict_demo({**vals,**weather_vals})
    final_aqi=aqi if aqi is not None else model["aqi"]
    cat=category(final_aqi)
    with sqlite3.connect(DB) as con:
        con.execute("INSERT INTO predictions(created_at,city,pm25,pm10,no2,o3,predicted_aqi,category) VALUES(?,?,?,?,?,?,?,?)",
                    (datetime.now(timezone.utc).isoformat(),body.get("city","Manual input"),vals["pm25"],vals["pm10"],vals["no2"],vals["o3"],final_aqi,cat))
    return jsonify({"aqi":final_aqi,"category":cat,"pollutant_subindex_aqi":aqi,
                    "model_estimate":model["aqi"],"model_status":"demonstration baseline, not a trained forecast model",
                    "advisory": advisory(cat)})

def advisory(cat):
    return {
      "Good":"Air quality is satisfactory. Enjoy normal outdoor activities.",
      "Satisfactory":"Sensitive people should consider reducing prolonged heavy outdoor exertion.",
      "Moderate":"People with asthma or respiratory conditions should limit prolonged outdoor exertion.",
      "Poor":"Reduce prolonged outdoor exertion; sensitive groups should avoid strenuous activity outdoors.",
      "Very Poor":"Avoid strenuous outdoor activity. Keep windows closed when outdoor air is polluted.",
      "Severe":"Avoid outdoor physical activity; follow local public-health advisories."
    }[cat]



def local_aero_guidance(aqi, location="your selected location"):
    """Reliable AQI-aware fallback used when OpenAI is not configured or unreachable."""
    try:
        n = int(float(aqi)) if aqi is not None else None
    except (TypeError, ValueError):
        n = None
    if n is None:
        return ("I don't have a current AQI reading for this location yet. Refresh the air report "
                "or allow GPS access. Until then, avoid smoke and waste burning, and check your "
                "local official air-quality bulletin before strenuous outdoor activity.")
    if n <= 50:
        return (f"The displayed AQI near {location} is {n} — Good. Normal outdoor activities are generally fine. "
                "Keep avoiding waste burning and unnecessary vehicle idling.")
    if n <= 100:
        return (f"The displayed AQI near {location} is {n} — Satisfactory/Moderate. Most people can continue "
                "normal activities; unusually sensitive people may reduce prolonged heavy outdoor exertion. "
                "Choose routes away from busy traffic where practical.")
    if n <= 150:
        return (f"The displayed AQI near {location} is {n} — Unhealthy for sensitive groups. Children, older adults "
                "and people with heart or lung conditions should reduce prolonged outdoor exertion. "
                "Consider indoor exercise and check local health guidance.")
    if n <= 200:
        return (f"The displayed AQI near {location} is {n} — Unhealthy. Everyone should reduce prolonged or heavy "
                "outdoor activity; sensitive groups should avoid outdoor exertion. Keep windows closed during "
                "pollution peaks and use a suitable HEPA air cleaner if available.")
    if n <= 300:
        return (f"The displayed AQI near {location} is {n} — Very Unhealthy. Avoid outdoor exercise and reduce time "
                "outside. Stay in cleaner indoor air, use HEPA filtration if available, and follow local public-health advisories.")
    return (f"The displayed AQI near {location} is {n} — Hazardous. Avoid outdoor activity and stay in cleaner indoor "
            "air. Follow local emergency/public-health advice; seek medical help for severe breathing difficulty or chest pain.")

@app.post("/api/assistant")
def assistant():
    """Aero: Gemini first, optional OpenAI second, local AQI guidance always available."""
    global GEMINI_LAST_ERROR
    body = request.get_json(silent=True) or {}
    question = str(body.get("message", "")).strip()[:1200]
    if not question:
        return jsonify({"error":"Type a question for Aero first."}), 400

    context = body.get("context") or {}
    aqi = context.get("aqi")
    category_name = str(context.get("category", "not available"))[:80]
    location = str(context.get("location", "your selected location"))[:180]
    fallback = local_aero_guidance(aqi, location)

    system_context = (
        "You are Aero, a friendly environmental health assistant inside AirWatch AI, a college air-pollution project. "
        "Answer in concise, helpful language (3-6 short sentences). Use the supplied AQI and location context; never invent readings. "
        "Tailor precautions to the displayed AQI category. Explain that a modelled estimate can differ from official monitoring stations. "
        "Do not diagnose illness or replace local public-health advice. If AQI is unavailable, say so.\n\n"
        f"Selected location: {location}\nDisplayed AQI: {aqi} ({category_name})."
    )

    # Fast Gemini model failover. Quotas are model-specific, so a 429 on
    # one model may still allow a different model on the same project.
    if GEMINI_API_KEY:
        configured_models = [GEMINI_MODEL] + GEMINI_FALLBACK_MODELS + ["gemini-3.1-flash-lite"]
        models_to_try = []
        for model_name in configured_models:
            if model_name and model_name not in models_to_try:
                models_to_try.append(model_name)

        last_gemini_issue = "Gemini request was not completed."
        gemini_payload = {
            "system_instruction": {"parts": [{"text": system_context}]},
            "contents": [{"role": "user", "parts": [{"text": question}]}],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 320}
        }

        # One short request per model, no hidden HTTP retries or long backoff.
        for model_name in models_to_try[:3]:
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
            try:
                gemini_started = time.monotonic()
                resp = gemini_http.post(
                    gemini_url,
                    headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
                    json=gemini_payload,
                    timeout=(8, 30)
                )
                gemini_elapsed = round(time.monotonic() - gemini_started, 2)
                if not resp.ok:
                    detail = ""
                    try:
                        err_data = resp.json().get("error", {})
                        detail = str(err_data.get("message", ""))[:220]
                    except (ValueError, AttributeError):
                        pass
                    last_gemini_issue = f"{model_name} HTTP {resp.status_code} after {gemini_elapsed}s" + (f": {detail}" if detail else "")
                    app.logger.warning("Aero Gemini model %s failed: %s", model_name, last_gemini_issue)

                    # Try another model for model-specific quota/capacity errors.
                    if resp.status_code in (404, 429, 500, 502, 503, 504):
                        continue
                    # Invalid key / permission / malformed request will not be fixed by changing model.
                    break

                data = resp.json()
                answer = "".join(
                    part.get("text", "")
                    for candidate in data.get("candidates", [])[:1]
                    for part in candidate.get("content", {}).get("parts", [])
                ).strip()
                if answer:
                    GEMINI_LAST_ERROR = f"Last Gemini request succeeded with {model_name} in {gemini_elapsed}s."
                    return jsonify({
                        "answer": answer,
                        "mode": f"Gemini-powered Aero ({model_name})",
                        "provider": "Gemini",
                        "model": model_name,
                        "fallback": False
                    })
                last_gemini_issue = f"{model_name} returned no text."
            except requests.Timeout:
                last_gemini_issue = f"{model_name} timed out (connect 8s / read 30s)."
                continue
            except requests.RequestException as exc:
                last_gemini_issue = f"{model_name} network error: {type(exc).__name__}."
                continue
            except (KeyError, TypeError, ValueError):
                last_gemini_issue = f"{model_name} returned an unreadable response."
                continue

        GEMINI_LAST_ERROR = last_gemini_issue
        app.logger.warning("Aero Gemini failover exhausted: %s", last_gemini_issue)

    # Optional secondary provider if user already has an OpenAI key configured.
    if OPENAI_API_KEY:
        try:
            resp = http.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type":"application/json"},
                json={"model":OPENAI_MODEL,"messages":[
                    {"role":"system","content":system_context},
                    {"role":"user","content":question}
                ],"temperature":0.4,"max_tokens":350},
                timeout=(8, 20)
            )
            resp.raise_for_status()
            answer = resp.json()["choices"][0]["message"]["content"].strip()
            if answer:
                return jsonify({"answer":answer,"mode":"OpenAI-powered Aero","provider":"OpenAI",
                                "model":OPENAI_MODEL,"fallback":False})
        except (requests.RequestException, KeyError, TypeError, ValueError):
            pass

    return jsonify({
        "answer": fallback + (
            " (Gemini is temporarily unavailable or returned an API error; showing local AQI guidance instead.)"
            if GEMINI_API_KEY or OPENAI_API_KEY else
            " (Local AQI guidance is active. Add a Gemini API key to enable Gemini-powered conversations.)"
        ),
        "mode":"Aero local AQI fallback","provider":"Local","fallback":True
    })


@app.get("/api/assistant-status")
def assistant_status():
    provider = "Gemini" if GEMINI_API_KEY else ("OpenAI" if OPENAI_API_KEY else "Local AQI")
    return jsonify({
        "gemini_configured": bool(GEMINI_API_KEY),
        "gemini_model": GEMINI_MODEL if GEMINI_API_KEY else None,
        "gemini_fallback_models": GEMINI_FALLBACK_MODELS if GEMINI_API_KEY else [],
        "openai_configured": bool(OPENAI_API_KEY),
        "active_provider": provider,
        "provider_status": "configured_not_yet_verified" if GEMINI_API_KEY else "not_configured",
        "fallback_available": True,
        "gemini_last_test": GEMINI_LAST_ERROR,
        "message": f"{provider} selected; local AQI guidance is always available."
    })


@app.get("/api/history")
def history():
    with sqlite3.connect(DB) as con:
        rows=con.execute("SELECT created_at,city,predicted_aqi,category FROM predictions ORDER BY id DESC LIMIT 20").fetchall()
    return jsonify([{"created_at":r[0],"city":r[1],"aqi":r[2],"category":r[3]} for r in rows])

init_db()
if __name__ == "__main__":
    app.run(debug=True, port=5000)
