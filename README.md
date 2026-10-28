# 🛡️ Kaniyan.AI — Environmental Risk Monitoring and Guidance

A Streamlit dashboard that shows weather, a 24-hour hourly forecast, rainfall, wind and air quality for a
chosen city, applies **transparent, rule-based alerts**, summarises them as an overall *Low / Moderate / High /
Very High* indicator, and gives practical precautions that can be tailored to an activity.

> **Honest status (v2):** 217 automated tests pass (`python -m pytest -q`, 40 s), and the app was started with
> Streamlit and exercised end-to-end in Demo mode and with *mocked* weather/air-quality services (live, one provider
> down, both down, stale cache, invalid thresholds, chat). The sandbox where v2 was built had **no access to
> open-meteo.com**, so **live API calls were not executed**. Parameters and fields were kept identical to v1 except one
> addition (hourly `apparent_temperature`). **Run the app once with internet access and confirm that live data loads
> before a demo** — see "Remaining verification" below.

## What it is (and is not)
- ✅ Weather + air-quality display, interactive charts, configurable threshold alerts, a 24-hour risk timeline,
  activity-specific precautions, grounded AI explanations (optional).
- ✅ Works with **no API key**. AI is optional; a Python rule-based fallback always works.
- ❌ **Not an official warning system.** The Low/Moderate/High/Very High indicator is an *application-generated*
  classification from simple threshold rules, not a government risk index and not a validated composite score.
- ❌ It does **not** predict street-level flooding or street-level pollution.
- ❌ AQI is the **US AQI scale computed by a CAMS model** via Open-Meteo — not CPCB's NAQI and not a ground-station reading.
- ❌ No notifications (push, browser, email, SMS) and no background/scheduled alerting.

## How it works
| Piece | Behaviour |
|---|---|
| **Overall risk** | The highest single alert level decides the category: none/Information → Low, Caution → Moderate, High concern → High. *Very High* = High concern in **two different hazard groups** (heat, rain, wind, air quality) at **overlapping times**. Levels are never added up. Reasons, contributing factors and data caveats are shown. |
| **Current vs forecast** | "Current" values are model estimates for the present hour (tagged *Current conditions*). Forecast items are tagged *forecast*. Alerts carry a `basis` of `current` or `forecast`. |
| **24-hour timeline** | Hourly values for the next 24 h at the location's local time. Heat, feels-like, wind gust and US AQI are compared hour by hour with the configured cut-offs; rain compares the *running total* with the 24-hour rainfall rule. Shows when a threshold is first crossed and how long it persists. Missing hours stay as gaps. If hourly air quality is unavailable, it says so — nothing is estimated. |
| **Activity advice** | Optional selector (general, travelling, outdoor work, walking/exercising, school). Rules map each triggered condition to a tip and show *because* (trigger) and *when*. No personal data. "Lower-risk hours" are offered only for activity modes and only when the hourly forecast has complete data for them. |
| **AI explanations** | The AI gets only verified Python results (alerts, overall risk, 24 h events, comparisons, data gaps, data status) and is told it may explain but never change them. Questions ≤ 600 chars, answers ≤ 2,500 chars, keys redacted, safe fallbacks. |
| **Data status** | Each provider is labelled **Live** (retrieved ≤ 10 min ago), **Cached (stale)** (refresh failed; older copy shown), **Unavailable**, or **Demonstration data**, with retrieval time, period, source and limitations. Stale data is never labelled live. |
| **Failures** | Weather and air quality are fetched independently; one failing never hides the other. Timeouts/5xx are retried twice with back-off; rate limits are not retried. Manual refresh is limited to once per 60 s. |

## Project structure
```
Kaniyan.AI/
├── app.py               Streamlit UI flow (display only)
├── ui_components.py     CSS, metric cards, risk banner, status chips
├── assessment.py        Runs all logic and returns one Assessment object
├── config.py            Thresholds (+ validation, limits, docs), URLs, cache/retry settings, activities
├── data_service.py      API calls, validation, retries, DataCache, live/cached/unavailable status
├── alert_engine.py      Threshold rules: current + daily alerts, de-duplication
├── timeline.py          24-hour window, events, summaries, today-vs-tomorrow
├── risk.py              Overall Low/Moderate/High/Very High classification
├── recommendations.py   Generic precautions per hazard/level (unchanged text)
├── activity_advice.py   Activity-specific recommendations with traceability
├── llm_service.py       Optional Groq AI + rule-based answers
├── charts.py            Plotly charts (7-day and 24-hour)
├── sample_data.py       INVENTED offline demo/test data (always labelled SAMPLE)
├── requirements.txt  .env.example  .gitignore  pytest.ini  CHANGELOG.md
├── .streamlit/secrets.toml.example
├── tests/               217 pytest tests
└── docs/                REPORT.md, PRESENTATION.md  (written for v1; not updated)
```

## Configurable thresholds
Edit in the sidebar (or `config.DEFAULT_THRESHOLDS`). Each rule has *Information < Caution < High* cut-offs, validated
against documented ranges (`config.THRESHOLD_LIMITS`); invalid input is reported, never silently replaced. Units and
meaning: `config.THRESHOLD_DOCS` (also shown in *Sources & notes*). Rain and US AQI defaults match published category
lower bounds (IMD 24-h rainfall classes; US EPA AQI bands) **as recalled by the authors — not re-verified online**;
temperature, feels-like and wind defaults are **illustrative and unvalidated**. The "high chance of rain" level (60 %) used
in recommendations is likewise configurable and unvalidated (`config.RAIN_PROB_NOTABLE_PERCENT`).

## Install & run

### Windows (PowerShell or Command Prompt) — run inside the `Kaniyan.AI` folder
```
py -3 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```
If PowerShell blocks activation: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then retry.

### Ubuntu / Linux — run inside the `Kaniyan.AI` folder
```
sudo apt update && sudo apt install -y python3 python3-venv python3-pip
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```
Streamlit prints a **Local URL** (normally `http://localhost:8501`). Open it in your browser.

### Opening in an IDE
- **VS Code:** *File → Open Folder → Kaniyan.AI*. Press `Ctrl+Shift+P` → *Python: Select Interpreter* →
  choose `.venv`. Use the built-in terminal (`Ctrl+``) for the commands above.
- **PyCharm:** *Open* the folder → *Settings → Project → Python Interpreter → Add Interpreter →
  Existing* → choose `.venv/bin/python` (Windows: `.venv\Scripts\python.exe`).

## Optional Groq AI setup (explanations + chat)
1. Create a free GroqCloud account and an API key at https://console.groq.com/keys.
2. In the `Kaniyan.AI` project folder, create `.streamlit` if it does not exist.
3. Inside `.streamlit`, create a file named `secrets.toml` with this line:
   `GROQ_API_KEY = "paste_your_real_key_here"`
4. The `.gitignore` excludes `.streamlit/secrets.toml`. Never commit or share the real key.
5. Install updated packages and run:
   `python -m pip install -r requirements.txt`
   `python -m streamlit run app.py`
   (Alternative for local use: copy `.env.example` to `.env` and put the key there.)
6. Tick **Use Groq AI explanation** in the sidebar and press **Generate AI explanation**. Open the **Kaniyan.AI Chat** tab to ask questions.

Default model: `openai/gpt-oss-120b` (Groq retired `llama-3.3-70b-versatile` on 16 Aug 2026). To use another model, set `KANIYAN_LLM_MODEL` in `.env` or `secrets.toml`.

If no key is configured or Groq is temporarily unavailable, the app continues with a rule-based Python fallback. The alert engine, not the LLM, decides which alerts are triggered. The chat is for general information, not official emergency guidance.

## Run the tests
```
pytest -q
```
Tests use **sample/mocked data** to verify logic. They are *not* validation against real observations.

## Reliable demonstrations
Switch on **Demo mode** in the sidebar. A red banner *“SAMPLE DATA – invented numbers”* is shown on
every run, and alert sources are tagged `[SAMPLE DATA]`. Say clearly to the audience that Demo mode
is offline sample data; show live mode first, and use Demo mode only if the network fails.

## Troubleshooting
| Problem | Fix |
|---|---|
| `streamlit: command not found` | Activate the virtual environment, then `pip install -r requirements.txt`. |
| `ModuleNotFoundError: No module named 'x'` | Same as above; check the interpreter selected in your IDE. |
| “Could not connect…” | Check internet/proxy/firewall. Use Demo mode meanwhile. |
| “Too many requests…” (HTTP 429) | Open-Meteo free limits: 600/min, 5,000/hour, 10,000/day, 300,000/month. Wait and retry; results are cached for 10 minutes. |
| “No place found for …” | Check spelling, try a larger nearby city, or add the state/country (e.g. `Kumbakonam`). |
| Some values show `n/a` or blank | The API returned null for that variable; the app skips it safely. |
| Air-quality section unavailable | Air-quality service failed; weather still works. Retry later. |
| Port 8501 busy | `streamlit run app.py --server.port 8502` |

## Data sources, licences, attribution
- Weather: Open-Meteo.com — data licensed CC BY 4.0; free API is for **non-commercial** use.
- Air quality: Open-Meteo Air Quality API, based on CAMS (Copernicus Atmosphere Monitoring Service) data.
  Open-Meteo requires attribution to the CAMS data provider and Open-Meteo (shown in the app footer tab).
- Geocoding: Open-Meteo Geocoding API, based on GeoNames.
- For real decisions use **IMD** (mausam.imd.gov.in), **CPCB** (cpcb.nic.in) and your state disaster
  management authority.

## Remaining verification (needs internet — not possible in the build sandbox)
1. `streamlit run app.py` → pick Chennai → confirm both status chips say **Live** and the *Next 24 hours* tab shows data.
2. Confirm `Air quality` hourly values appear (otherwise the app says unavailable, by design).
3. Pull the network cable / use airplane mode, press **Refresh** → status should become **Cached (stale)** with its age.
4. Optional: add a Groq key and confirm the AI answer is labelled *AI-generated explanation*.
5. Open the app on a phone-sized window and check the cards and charts wrap sensibly (layout was designed responsively
   with CSS grid, but not tested on real devices).

## Known limitations
- Open-Meteo's free API is non-commercial; "current" values are model analysis, not station observations.
- The 24-hour rain rule uses a running total of model precipitation; it says nothing about local drainage or flooding.
- No official warning feed (IMD/CPCB) is integrated; the app tells users to check them.
- Alerts have no memory between refreshes, so "resolved" alerts are not tracked.
- English only. No saved locations, history or downloadable daily report (possible future work).
