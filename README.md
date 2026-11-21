# SmogSafe 🫁 — breathe easier in smog season

**SmogSafe** is a GenAI assistant that helps Indian families get through winter smog. It reads the live air for your city, plans your day around the cleanest hours, gives advice for each person at home, and shows the real impact of every choice, with the maths visible.

> Every winter, cities across North India cross "Very Poor" and "Severe" AQI. Most apps show a number. SmogSafe tells a family **what to do today**, **who needs extra care**, and **how much each choice actually helps**.

---

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
        ├─► gemini.py       (plan JSON · grounded chat · grounded advisories)
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
pytest -q
```
44 tests cover CPCB AQI breakpoints, impact maths, forecast windows, Google AQ parsing, citation insertion (UTF-8 byte offsets, Hindi text included), pledge de-duplication, every API route (with Gemini mocked), validation, rate limiting and security headers.

## Security, privacy & accessibility

- API keys stay on the server; the browser never sees them
- Pydantic validates every input; request bodies are capped at 16 KB; AI routes are rate-limited per client
- Strict Content-Security-Policy (`script-src 'self'`), `X-Frame-Options: DENY`, `nosniff`, a tight Permissions-Policy
- Server and AI text is rendered with `textContent` (no `innerHTML`). Google Search suggestions render inside a sandboxed iframe with scripts disabled
- No accounts. Household and health notes stay in the browser; pledges store only a salted hash of a random device id
- Semantic landmarks, skip link, keyboard-friendly tabs (arrow keys, Home/End), labelled inputs, live regions for updates, a screen-reader table behind the chart, visible focus, `prefers-reduced-motion` support, and colour is never the only signal

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
