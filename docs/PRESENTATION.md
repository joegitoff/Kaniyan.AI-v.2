# Kaniyan.AI — Presentation, Demo, Viva and Schedule

## 1. Why this is more than "displaying weather"
A weather app answers *"what are the numbers?"* Kaniyan.AI answers *"do any of these numbers cross a
defined level of concern, why, when, and what could I do?"* It (a) merges weather and air quality,
(b) applies explicit, editable rules, (c) shows the rule, value, time, source and level for every alert,
(d) suggests precautions, and (e) states its limits honestly (not official, no flood prediction).

## 2. Five-to-seven-minute script (≈ 750 words, speak slowly)
**[0:00 Slide 1 – Title]** "Good morning. We are presenting Kaniyan.AI, a location-based environmental alert dashboard built in Python."
**[0:30 Slide 2 – Problem]** "People see raw numbers – 72 millimetres of rain, AQI 135 – but not what they mean or what to do. Data sit in different apps."
**[1:15 Slide 3 – Objectives]** "We built a dashboard that fetches weather and air quality for any city, applies transparent rules, explains each alert and suggests precautions."
**[2:00 Slide 4 – Architecture]** "The user picks a city. data_service geocodes it and calls three Open-Meteo APIs. Pandas cleans the JSON. alert_engine applies threshold rules. recommendations adds precautions. Streamlit and Plotly display everything."
**[3:00 Slide 5 – Alert logic]** "Every alert is a simple comparison: value ≥ threshold. We use three levels – Information, Caution, High concern. Thresholds are illustrative and editable. These are not official warnings, and rainfall alerts never claim flooding."
**[3:45 Slide 6 – Air quality honesty]** "We show US AQI as calculated by the CAMS model through Open-Meteo. It is not the Indian CPCB index. We never mix AQI scales."
**[4:15 Slide 7 – Optional LLM]** "An LLM can rephrase alerts in plain language, but Python makes all decisions. If the key is missing, the API fails, or the answer contains numbers not in our data, we use a Python fallback."
**[5:00 Slide 8 – Live demo]** (see sequence below)
**[6:15 Slide 9 – Testing & limits]** "39 automated tests cover thresholds, parsing, network failure, null data and LLM failure. Tests use sample data, so they verify logic, not forecast accuracy."
**[6:45 Slide 10 – Conclusion]** "Kaniyan.AI turns data into explainable, location-specific guidance and shows responsible handling of uncertainty. Thank you."

## 3. Slide-by-slide PowerPoint outline
1. **Title:** Kaniyan.AI; team; guide; date.
2. **Problem & motivation:** raw numbers vs decisions; Tamil Nadu monsoon/heat/air examples.
3. **Objectives:** 5 bullets.
4. **Architecture diagram** (Mermaid from report → export as image).
5. **Data sources:** Open-Meteo weather, air quality (CAMS), geocoding (GeoNames); limits and attribution.
6. **Alert engine:** rule table (variable, levels), example alert card screenshot.
7. **Safety & honesty:** not official; no flood prediction; AQI scale note; sample-data labelling.
8. **Optional LLM:** flow diagram with fallback.
9. **Live demo / screenshots.**
10. **Testing:** test table summary (39 tests, categories).
11. **Limitations & future work.**
12. **Conclusion & Q&A.**

## 4. Live demonstration sequence (≈ 90 seconds)
1. Open the app (already running). Pick **Chennai** → show Overview metrics and timestamp.
2. **Forecast tab:** point at rainfall bar vs dashed caution line.
3. **Air quality tab:** read the “Which index is this?” note aloud.
4. **Alerts tab:** expand one alert; show value, rule, time, level, explanation, precautions, source, “Official warning: No”.
5. Change a threshold in the sidebar (e.g. rain caution to 20 mm) → alerts update (shows rules are configurable).
6. Type an invalid city (`Zzzzqq`) → show clean error message.
7. **Resilience:** switch on **Demo mode** → point at the red SAMPLE DATA banner: "If Wi-Fi fails we can still show the interface – but this is invented data, clearly labelled."
8. (Optional) Generate LLM explanation; show the “Explanation source” label.
*Rehearse once on the venue network. If live data fail, say so openly and switch to Demo mode.*

## 5. Five realistic scenarios
1. **Monsoon day, Chennai:** forecast 118 mm/day → HIGH rain alert; advice: avoid unnecessary travel, follow IMD/municipal updates; app states it cannot predict which streets flood.
2. **Summer afternoon, Thanjavur/Madurai:** max 40 °C, feels-like 43 °C → CAUTION heat; advice: avoid 11 am–4 pm exertion, hydrate.
3. **Winter morning, Delhi:** modelled US AQI peak 180 → HIGH air quality; advice: limit outdoor exertion, sensitive groups indoors, N95 mask outdoors.
4. **Windy coastal day:** gusts 66 km/h → CAUTION wind; secure loose objects, be careful on two-wheelers.
5. **Calm day:** nothing triggered → green "no rule triggered" message and a reminder to re-check forecasts.
*(Scenarios 1–4 use the sample-data patterns; real values will differ — do not present them as actual observations.)*

## 6. Viva questions and answers
**Python & structure**
1. *Why split into modules?* Separation of concerns: data, rules, advice, UI, LLM. Easier to test, read and change.
2. *What is a dataclass and where used?* A class that mainly stores data with auto-generated `__init__`. Used for `Location`, `WeatherData`, `AirQualityData`, `Alert`.
3. *What does `IntEnum` give you in `Level`?* Named constants that compare as integers, so `HIGH > CAUTION` and sorting work.
4. *Explain type hints.* Annotations like `-> list[Alert]` document expected types; they are not enforced at runtime but help readers/IDEs.
5. *Difference between list and dictionary?* List: ordered by position. Dict: key→value lookup; we use dicts for JSON and thresholds.

**APIs & JSON**
6. *What is an API?* A defined way for programs to request data; ours is HTTP returning JSON.
7. *What is JSON and how do you parse it?* Text format of nested objects/lists; `response.json()` converts it to Python dict/list.
8. *Why geocoding first?* The weather API needs latitude/longitude, not names.
9. *What if the API gives 429?* Too many requests; we raise `RateLimitError`, show a message, and cache results 10 minutes to reduce calls.
10. *Which APIs and are they free?* Open-Meteo weather, air quality, geocoding; free for non-commercial use with limits (e.g. 10,000 calls/day) and attribution.

**Exception handling**
11. *Which errors do you handle?* Timeout, connection failure, HTTP errors, invalid JSON, unknown city, missing fields, LLM failures.
12. *Why custom exceptions?* They give meaningful categories; the UI catches one base class `DataServiceError`.
13. *`try/except/else/finally` — what do you use?* `try/except` mostly; `raise ... from exc` preserves the original cause.

**Pandas & visualisation**
14. *Why DataFrames?* Column-wise operations, grouping and filtering; e.g. daily peak AQI via `groupby`.
15. *How do you treat missing values?* `pd.to_numeric(errors="coerce")` converts bad/None to NaN; `is_missing()` stops comparisons.
16. *Why Plotly?* Interactive zoom/hover and easy threshold lines (`add_hline`).
17. *What does Streamlit do?* Turns a Python script into a web app; reruns the script on interaction; `st.cache_data` avoids repeated API calls.

**Rule-based alerts**
18. *Why rules, not machine learning?* Transparent, explainable, no training data needed, suitable for safety information; ML would need validated local data.
19. *Where do thresholds come from?* They are illustrative, loosely inspired by public categories, editable, and **not official**; real decisions need IMD/CPCB.
20. *Can the app predict floods?* No. Rainfall amount is not flood proof; floods depend on drainage, terrain and local conditions. We say so in every rain alert.
21. *Which AQI do you use and why?* US AQI from the CAMS model via Open-Meteo (global coverage). It is not CPCB NAQI; we never mix with European AQI.
22. *How do you avoid false precision?* Show model source, timestamps, “estimate” wording, daily peaks only, and limitations.

**LLM**
23. *Role of the LLM?* Only to rewrite results in plain language. Python decides alerts and calculates values.
24. *How do you stop the LLM inventing facts?* Strict system prompt, payload contains only real data, post-check rejects numbers not in payload, fallback on any doubt.
25. *Where is the API key stored?* In `.env` / environment variable, excluded via `.gitignore`; never in code.
26. *What if the LLM is down?* `explain()` never raises; returns the Python fallback and tells the user why.

**Testing**
27. *What is mocking?* Replacing `requests.get` with a fake so tests run offline and deterministically (`monkeypatch`).
28. *Do your tests prove the forecasts are accurate?* No — they prove our code behaves correctly with given inputs. Accuracy would need comparison with observations.
29. *How do you demo if the API fails?* Demo mode with labelled invented data; we tell the audience it is not live.

## 7. Five-hour implementation checklist
*Realistic note:* five hours is enough for the **smallest credible version** (steps 1–4) plus basic tests. Charts polish, LLM and documentation are tight; the complete code is provided, so most time goes into running, understanding, customising and documenting it.

| Time | Milestone | Done when |
|---|---|---|
| 0:00–0:30 | **Setup:** venv, install, create files, run `pytest` and `streamlit run app.py` in Demo mode | Dashboard opens with SAMPLE banner |
| 0:30–1:15 | **Minimum viable app (essential):** read `config.py`, `data_service.py`; run live mode for Chennai | Live current weather + forecast table appear |
| 1:15–2:00 | **Live API integration (essential):** test several cities, invalid names, offline mode (turn Wi-Fi off) | Errors are friendly; air quality loads |
| 2:00–2:45 | **Visualisations (essential):** study `charts.py`; adjust titles/colours | 4 charts render |
| 2:45–3:30 | **Rule-based alerts (essential):** understand `alert_engine.py`; tweak thresholds; read all alert cards | Alerts with explanations appear for sample and live |
| 3:30–4:00 | **Testing (essential):** `pytest -q`; add 2 tests of your own; screenshots | All tests pass |
| 4:00–4:30 | **Optional LLM:** set `.env`, try button; confirm fallback by removing key | Source label changes LLM ↔ fallback |
| 4:30–5:00 | **Documentation & rehearsal:** fill team details in `REPORT.md`, add screenshots, rehearse script | 7-minute run-through done |

**Essential:** geocoding, weather, air quality, rule alerts, charts, error handling, README.
**Optional:** LLM, CSV download, threshold editor, Demo mode (but strongly recommended for demos).
