# SmogSafe 🫁 — breathe easier in smog season

**SmogSafe** is a GenAI assistant that helps Indian families get through winter smog. It reads the live air for your city, plans your day around the cleanest hours, gives advice for each person at home, and shows the real impact of every choice, with the maths visible.

> Every winter, cities across North India cross "Very Poor" and "Severe" AQI. Most apps show a number. SmogSafe tells a family **what to do today**, **who needs extra care**, and **how much each choice actually helps**.

---

## Problem statement → what SmogSafe does

| The brief asks for… | Where it lives in SmogSafe |
|---|---|
| Help **families** navigate winter smog | Family profiles: risk level and tips for each person (kids, elders, asthma, heart, pregnancy) |
| Help **communities** | Smog Circle: city-wide pledges with a shared CO₂ counter, plus live local advisories |
| **Low-emission daily routines** | Daily plan (commute swaps, timing errands for clean hours) and the commute-switch calculator |
| **Indoor air quality hacks** | Tonight's indoor-air checklist and indoor actions in the plan (windows, purifier, wet mopping, cooking) |
| **Sustainable alternatives** | Three "swap this for that" suggestions in every plan |
| Tailored to **location** | Auto-detects any Indian city; live AQI, 24-h forecast and cleanest/smoggiest hours for that spot |
| Tailored to **lifestyle** | Household profile: commute mode and distance, cooking fuel, purifier, busy road, outdoor exercise |
| **Clearly explain the direct impact** | Every action shows % less smog breathed, cigarettes avoided or kg CO₂ saved, with a "How we worked this out" panel showing the formula |
| **GenAI-powered** | Gemini writes the plan (structured JSON) and answers what-if questions with Google Search grounding and sources |

## Features

| | What it does |
|---|---|
| 📍 **Live air for any Indian city** | Auto-detects your location (or search any city). Shows the **Indian AQI (CPCB method)**, main pollutant, a 24-hour PM2.5 forecast, and the **cleanest and smoggiest 2-hour windows**. |
| 🚬 **Cigarette equivalent** | "Breathing this air all day ≈ 7.4 cigarettes" (Berkeley Earth's 22 µg/m³ ≈ 1 cigarette rule). |
| 🗓️ **Daily Smog Coach** | Gemini writes a step-by-step plan for *your* household: commute, workouts, cooking, windows, purifier. It works in English, Hindi or Hinglish. |
| 👨‍👩‍👧 **Family profiles** | Add elders, kids, asthma/heart/pregnancy notes. Each person gets a **risk level** (worked out in code, not guessed by the LLM) and short tips. |
| 🏠 **Indoor-air checklist** | Tonight's to-dos (wet mopping, sealing gaps, no incense…), saved on the device. |
| 💬 **What-if chat** | "What if I take the metro 3 days a week?" Answers are **grounded with Google Search** and show **numbered citations, sources and Google Search suggestions**. |
| 🧮 **Impact calculators** | Commute switch (CO₂/year, "if 1,000 people did this") and "Smog you breathe" (indoors, purifier, N95). |
| 🤝 **Smog Circle** | Anonymous city pledges (engine off at red lights, no burning, metro 2×/week…) with a shared CO₂ counter. |
| 📰 **Local advisories** | Latest GRAP stage, school and construction advisories for your city through Google Search grounding, with sources. |

## How the impact numbers work

The LLM never makes up impact numbers. All maths lives in `app/services/impact.py`. Gemini only chooses which pre-computed impact fits each action, so every badge can be explained and tested.

- **Smog breathed** = PM2.5 outside × share reaching you (setting × mask) × breathing rate × time
- **Cigarettes** = dose ÷ (22 µg/m³ × 15 m³ of air a day ≈ 330 µg)
- **Commute CO₂** = (old mode − new mode kg CO₂/passenger-km) × km per week. Factors come from TERI's Delhi per-passenger study.
- Indoor share: windows open 0.9, closed 0.6, with purifier 0.3. Mask pass-through: cloth 0.8, surgical 0.6, fitted N95 0.2.

Open **"How we calculate"** in the app footer to see the full table and sources.

## Tech stack

- **Backend:** Python, FastAPI, httpx, Pydantic
- **AI:** Google **Gemini** (`google-genai` SDK). The daily plan uses structured JSON output with a Pydantic schema; chat and advisories use **Grounding with Google Search**
- **Air data:** Open-Meteo Air Quality API (CAMS global model, free, no key). Optional **Google Air Quality API** for 500 m current readings and the official CPCB index
- **Geocoding:** Open-Meteo (city search, India only), OpenStreetMap Nominatim (reverse)
- **Frontend:** plain HTML, CSS and JavaScript. No framework, no build step, no external scripts
- **Storage:** household details in the browser's localStorage; pledges in SQLite (anonymous, salted hashes)

```
Browser (HTML/CSS/JS)
   │  /api/air  /api/plan  /api/ask  /api/advisories  /api/community  /api/impact/*
   ▼
FastAPI ──► air_quality.py ──► Open-Meteo (+ Google Air Quality API, optional)
        ├─► aqi_india.py    (CPCB sub-indices, 24-h / 8-h averages)
        ├─► impact.py       (exposure, cigarettes, CO₂: deterministic)
        ├─► household.py    (risk levels + offline fallback plan)
        ├─► context.py      (compact summaries: exactly what Gemini sees)
        ├─► gemini.py       (plan JSON · grounded chat · grounded advisories)
        ├─► planner.py      (attaches computed impacts to each action)
        └─► community.py    (SQLite pledges)
```

## Run it locally

**Windows (PowerShell)**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env      # then paste your GEMINI_API_KEY into .env
uvicorn app.main:app --reload
```

**macOS / Linux**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # add GEMINI_API_KEY
uvicorn app.main:app --reload
```

Open http://localhost:8000. API docs are at http://localhost:8000/api/docs.

No key yet? The app still works: live air data, calculators, pledges and a rule-based daily plan run without AI. If the venue Wi-Fi dies, set `DEMO_MODE=true` to use clearly labelled sample smog data.

## Deploy

**Render:** push to GitHub → New → Blueprint → pick the repo (uses `render.yaml`) → add `GEMINI_API_KEY`.

**Google Cloud Run**
```bash
gcloud run deploy smogsafe --source . --region asia-south1 --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY=YOUR_KEY,DEVICE_SALT=some-long-random-string
```

## Tests

```bash
pytest --cov=app     # 70 tests, ~96% coverage (CI fails below 90%)
ruff check . && ruff format --check .
```
Tests cover CPCB AQI breakpoints, impact maths, forecast windows, the Open-Meteo and Google Air Quality clients (network mocked with `httpx.MockTransport`), geocoding, caches and rate limits, Gemini model fallback and search-blocked fallback, citation insertion (UTF-8 byte offsets, Hindi text included), pledge de-duplication, every API route, validation, gzip, plan caching and security headers. GitHub Actions runs lint, format check and tests on every push.

## How SmogSafe meets the judging criteria

**Code quality**
- Small, single-purpose modules: `aqi_india` (CPCB maths), `impact` (exposure/CO₂), `air_quality`, `gemini`, `context` (what the model sees), `planner`, `community`, `geocode`
- Type hints and docstrings throughout; Pydantic schemas for every request and for Gemini's JSON output
- `ruff` lint + format enforced in CI; config in `pyproject.toml`

**Security**
- API keys stay on the server; the browser never sees them
- Pydantic validates every input; request bodies capped at 16 KB; per-client rate limits on all API routes, tighter on AI routes
- Strict Content-Security-Policy (`script-src 'self'`), HSTS behind HTTPS, `X-Frame-Options: DENY`, `nosniff`, COOP/CORP, a tight Permissions-Policy
- Server and AI text rendered with `textContent` (no `innerHTML`); Google Search suggestions shown in a sandboxed iframe with scripts disabled
- No accounts. Household and health notes stay in the browser; pledges store only a salted hash of a random device id
- Docker image runs as a non-root user; Dependabot keeps dependencies updated

**Efficiency**
- Air data cached per ~1 km cell for 15 min; geocoding for 24 h; advisories for 30 min; identical AI plans for 15 min (fewer Gemini calls, lower cost)
- Open-Meteo and Google Air Quality fetched in parallel; one shared async HTTP client
- Gzip on responses; static files cached; no frontend framework or build step (the whole UI is ~85 KB, about 24 KB gzipped)
- Gemini gets a compact context (the AQI summary and headline numbers, not raw data), which keeps prompts small

**Testing**
- 70 automated tests, ~96% coverage, every external service mocked, run in CI on every push

**Accessibility**
- Passes an automated axe-core scan (WCAG 2.1 A/AA) on every screen with no violations
- Semantic landmarks, skip link, keyboard tabs (arrow keys, Home/End), labelled inputs, live regions, a screen-reader table behind the chart, visible focus, `prefers-reduced-motion`, and colour is never the only signal
- Decorative emoji hidden from screen readers; AI answers tagged with the right `lang` (Hindi/Hinglish) so screen readers pronounce them correctly

**Problem statement alignment**
- See the mapping table at the top of this README

## Limitations

- Open-Meteo values come from a ~45 km model grid and can read lower than CPCB stations during severe episodes. The app labels them as estimates and links to the official CPCB dashboard. Adding a Google Air Quality key improves this.
- Impact numbers are rounded estimates meant for comparing choices, not medical or regulatory measurements.
- SmogSafe gives general guidance, not medical advice.

## Data sources

- CPCB National Air Quality Index (2014) breakpoints
- Berkeley Earth: Air pollution and cigarette equivalence
- TERI: Per-passenger emissions of transport modes in Delhi
- ITF/OECD: Life-cycle assessment of passenger transport in India
- Open-Meteo Air Quality API (Copernicus CAMS)

---

Built by **Lakshay** · [github.com/lakshay57112](https://github.com/lakshay57112)
