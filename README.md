# AirWatch AI — independent software prototype

## Features
- Live weather conditions and hourly forecast through Open-Meteo.
- Optional OpenAQ station lookup; requires a server-side API key.
- Manual pollutant entry and transparent AQI breakpoint interpolation.
- Prediction history stored in SQLite.
- Responsive dashboard.

## Run locally
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000

## Optional OpenAQ
Set `OPENAQ_API_KEY` as an environment variable on the server. Never put the key in browser JavaScript or commit it to source control.

Windows PowerShell:
```powershell
$env:OPENAQ_API_KEY="YOUR_KEY"
python app.py
```

## Important scientific limitations
- Open-Meteo supplies weather, not measured air pollution.
- OpenAQ station availability varies by city and pollutant.
- This prototype's model estimate is a clearly labelled demonstration baseline, not a trained/validated forecast model.
- The AQI interpolation uses commonly published CPCB breakpoints, but a production CPCB-compliant AQI needs correct pollutant averaging windows, units, data completeness rules, and validation against official calculations.
- Do not describe weather data or model estimates as live measured AQI.


## Automatic air-quality report (added)
The dashboard fetches current modelled pollutant estimates from the Open-Meteo Air Quality API using the selected city. It displays the API's **US AQI** and pollutant concentrations, then generates precaution and exposure-management guidance.

Important: this is a CAMS gridded model estimate, not a live nearby CPCB station observation and not official Indian CPCB AQI. See https://open-meteo.com/en/docs/air-quality-api for model sources, resolution, variables and attribution. The dashboard shows the data timestamp and limitations.


## Exact GPS display
After the user clicks Use my live location and grants browser permission, the app displays GPS coordinates and a reverse-geocoded nearby address using OpenStreetMap Nominatim. This address is an approximate nearest mapped address, not proof of a unit/flat number. Air-quality values remain model-grid estimates; Open-Meteo CAMS grid resolution is roughly 45 km for global coverage and 11 km for the European model. A nearby physical station API is needed for true street-nearby measured pollution.

## Nearest physical monitoring station (OpenAQ)
After GPS permission is granted, AirWatch AI searches OpenAQ within 25 km of the coordinates, selects the nearest returned station and requests its latest measurements. Actual station readings require an OpenAQ API key stored server-side as `OPENAQ_API_KEY`; do not put the key in frontend JavaScript or commit it. If no key or station is available, the dashboard explains that status instead of fabricating measurements. Station measurements are nearby observations, not the exact GPS point. The API's latest endpoint can return the last value in a sensor's series; inspect the returned timestamps for freshness.
Docs: https://docs.openaq.org/api/operations/locations_get_v3_locations_get and https://docs.openaq.org/api/operations/location_latest_get_v3_locations__locations_id__latest_get

## Configure OpenAQ API key (recommended method)
1. Revoke/regenerate any API key accidentally shared in a chat or screenshot.
2. Copy `.env.example` to a file named `.env` in the same folder as `app.py`.
3. Open `.env` and replace `PASTE_NEW_KEY_HERE` with your new key. Do not add quotes.
4. Install packages: `python -m pip install -r requirements.txt`.
5. Stop Flask with Ctrl+C and restart: `python app.py`.
6. Open `http://127.0.0.1:5000/api/openaq-status`. It should say `configured: true`. This endpoint never reveals the key.
7. Click Use my live location again in the dashboard.

The `.env` file is ignored by `.gitignore`; never share it or commit it.

## OpenAQ HTTP 422 correction
The nearby station request now uses only documented geospatial parameters (`coordinates` as latitude,longitude to 4 decimals and `radius` up to 25000 m). It does not send unsupported `order_by=distance`. The closest returned location is selected by its returned distance value. The app then fetches that location's sensors from `/v3/locations/{id}/sensors` and latest readings from `/v3/locations/{id}/latest`. Provider error details are shown without exposing the API key.

## AirWatch AI Cyber-Anime UI edition
This edition refreshes the dashboard with a dark sci-fi HUD visual system, responsive navigation, animated original anime guardian artwork, hover/focus states, scroll-aware navigation, toast feedback, a clickable Aero assistant, and pollution-management field-guide cards. Existing Flask routes, GPS flow, OpenAQ integration, weather feed, AQI report, scenario estimator and history are retained. The anime guardian is original generated artwork included at `static/airwatch-guardian.png`.
Run with the same `.env` configuration and `python app.py`. For external access, deploy behind a production WSGI server and HTTPS tunnel/host; do not expose Flask's development server directly.

## AirWatch AI — Soft Aurora + Aero Assistant
- Fixed transient TLS/network failures by using a pooled `requests.Session` with bounded retries and exponential backoff. TLS certificate verification remains enabled. If a network proxy/antivirus is intercepting HTTPS, resolve that network issue rather than disabling certificate checks.
- Added `/api/assistant`, which uses the OpenAI Chat Completions API when `OPENAI_API_KEY` is configured. The key stays server-side in `.env`; it is never sent to browser JavaScript.
- Without an OpenAI key, Aero still gives AQI-aware local guidance based on the live AQI displayed by the dashboard.
- Aero assistant chat UI is included in the page. AQI precautions are tailored to the current displayed model estimate and clearly distinguished from official CPCB station readings.
- Updated visual style to a softer midnight/aurora palette with muted mint, lavender and cyan accents.
### Optional OpenAI setup
Copy `.env.example` to `.env`, then set `OPENAI_API_KEY=your_key_here` and optionally `OPENAI_MODEL=gpt-4.1-mini`. Restart Flask after changing environment values. OpenAI API usage may incur charges under the developer account's billing terms. Never commit `.env` or share API keys.

## Aero always-on fallback fix
The `/api/assistant` endpoint now always returns AQI-aware local guidance when no OpenAI API key is configured or when the OpenAI request fails (invalid key, unavailable model, billing/quota, rate limit, TLS/network issue, or unexpected response). The browser chat therefore receives a useful answer instead of the generic service-unavailable error. The endpoint `/api/assistant-status` reports whether an OpenAI key is configured without revealing the key. For ChatGPT-powered free-form answers, configure a valid `OPENAI_API_KEY` in the server-side `.env`; local AQI precautions do not require an OpenAI key.

## Gemini-powered Aero
Gemini is now Aero's primary online AI provider. Configure `GEMINI_API_KEY` in the server-side `.env` file. Default model is `gemini-2.5-flash`; change `GEMINI_MODEL` only to a model available to your Google AI Studio project. If Gemini is unavailable or its quota is reached, the app tries the optional OpenAI provider (if configured), then falls back to local AQI-aware guidance. The API key is sent only from Flask to Google's API and is never exposed in browser JavaScript.
Get a Gemini API key from Google AI Studio: https://aistudio.google.com/app/apikey
Check current pricing and per-project rate limits before sharing the app with friends; free-tier limits are not unlimited and can change.

## Gemini diagnostics build
This build logs Gemini provider failures to the Flask terminal without logging API keys or request headers. Visit `/api/assistant-status` after sending an Aero message to inspect `gemini_last_test`. HTTP error details are truncated and intended for local debugging. Keep `.env` private and never share it.

## Gemini model compatibility update
The default Gemini model has been changed to `gemini-3.8-flash`, matching the model suggested by the HTTP 404 response shown in the user's current Google API response. If your existing `.env` explicitly contains `GEMINI_MODEL=gemini-2.5-flash`, update that line to `GEMINI_MODEL=gemini-3.8-flash`; environment values override the code default. Restart Flask after editing `.env`. Confirm that this model is listed as available for your API key/project in Google AI Studio if another model error appears.

## Gemini smart retry and model failover
Aero tries the configured primary model (`GEMINI_MODEL`, default `gemini-3.8-flash`) with bounded exponential backoff for transient 408/429/5xx/network errors. If the primary remains unavailable, it tries the configured alternate models (`GEMINI_FALLBACK_MODELS`, default `gemini-3.7-flash,gemini-3.6-flash`). Permanent 4xx errors are not repeatedly retried. If Gemini models remain unavailable, the existing optional OpenAI provider and then local AQI guidance are used. `/api/assistant-status` lists configured model names but never exposes credentials.

## Aero Fast Response update
- Gemini requests now use a dedicated HTTP session with adapter retries disabled, preventing hidden multi-minute retry chains.
- Uses the configured primary Gemini model only (`GEMINI_MODEL`, default `gemini-3.8-flash`).
- One short retry is attempted only for temporary 5xx server responses.
- Gemini connect/read timeout is bounded (3.5s/8s); failed requests immediately use the existing optional OpenAI provider, then local AQI guidance.
- Frontend prevents duplicate submissions, disables the input while a request is active, shows provider mode returned by the backend, and aborts the browser request after 18 seconds.
- The ZIP intentionally excludes `.env` and the local SQLite database. Copy your own `.env` into the extracted folder and use a newly rotated API key if the previous key was exposed in a screenshot.

## Gemini 429 failover update
- Default model is now `gemini-3.1-flash-lite`, which is listed with free-tier text input/output on Google's current pricing page.
- If the configured model returns 404/429/5xx or times out, Aero tries up to two alternate configured models, including `gemini-3.1-flash-lite`.
- Each model gets one short request; there is no long retry/backoff chain.
- If all configured Gemini models fail, Aero continues to the optional OpenAI key and then local AQI guidance.
- Update your local `.env`: set `GEMINI_MODEL=gemini-3.1-flash-lite`. This does not bypass project-wide quota restrictions; check the AI Studio Rate Limits page if the Lite model also returns 429.


## Gemini response-time diagnostic update
- Gemini connection timeout is 8 seconds and response read timeout is 30 seconds.
- Optional OpenAI fallback timeout is 8s connect / 20s read.
- Browser chat timeout is 45 seconds so it does not cancel a legitimate slower model response after 18 seconds.
- Backend logs include elapsed Gemini response time and the exact HTTP status/error detail (without logging API keys).
- If the request still times out, investigate network/firewall/DNS connectivity or Google's service availability; increasing the timeout cannot fix a blocked connection.
