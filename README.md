# Truck Route Weather

A React and Django app that compares three truck routes by the weather each one will meet, and recommends the safest.

You enter an origin, a destination, a departure time and the cargo weight. The app asks TomTom for three truck routes, works out when the truck reaches each checkpoint along each route, looks up the forecast for that place at that hour, and classifies the risk with the assessment's rules. The route with the least dangerous weather wins; travel time only decides between routes whose risk is the same.

- **Live app:** _add Vercel URL_
- **API:** _add Render URL_
- **Walkthrough:** _add Loom URL_

## Using it

1. Type a city or address in **From** and **To** and pick a suggestion, or choose them on the map (see below).
2. Set the departure time (your local time zone) and the cargo weight. The switch inside the weight field changes between pounds and kilograms and converts what you typed; the app remembers your choice.
3. Choose how often to check the weather: every 10, 25 or 50 miles. You can change this after the results load; nothing is fetched again.
4. Press **Find routes**.

There are three ways to choose places on the map:

- Press the target button inside **From** or **To**, then click (or tap) the map. After From is set the map moves on to To, so two clicks plan a whole trip. Esc or **Cancel** stops.
- While you are in an empty From or To field, even mid-typing, right-click the map to fill that field.
- Right-click anywhere else for a small menu: **Set as From** or **Set as To**.

From and To appear as pins (From hollow, To filled), which can be dragged to adjust them. A picked point is named by the nearest street or town; the pin stays exactly where it was dropped. The small help buttons next to **Cargo weight**, **Weather checkpoints every** and **Forecast** explain what each one does.

If you change the trip after the results load, the panel says so and the button becomes **Update routes**, so results for an old trip are never mistaken for the new one.

The panel shows the recommended route and why it was picked, then the three routes with travel time, distance, arrival time and a strip showing risk mile by mile. Selecting a route highlights it on the map. The checkpoint table lists mile, ETA, wind, rain, snow and risk for the selected route; clicking a row moves the map to that checkpoint.

On the map, routes are coloured by risk and checkpoint dots show the forecast on hover. The forecast bar at the bottom shows the weather across the whole trip corridor. Drag the slider (or press play) to move through the 48 hours after departure, and switch between overall risk, wind, rain and snow. A blue dot marks where the truck on the selected route would be at that hour.

The layers button under the zoom controls switches the base map between **Light**, **Streets** and **Dark**, all from OpenFreeMap. Routes, checkpoints and the forecast layer stay in place when the map changes.

There is a one-click example trip (Denver to Salt Lake City with 42,000 lb), which is a good test of the wind and load rules because I-80 across southern Wyoming is often closed to light, high-sided loads in strong wind.

## How it works

### Routes

TomTom's Routing API is called with `travelMode=truck` and the vehicle's gross weight, so the routes respect truck restrictions. Gross weight is the cargo plus 35,000 lb for an empty tractor and trailer (`TRUCK_TARE_LB`); the form says this under the weight field.

TomTom is asked for two alternatives. For short or constrained trips it often returns fewer than three, or alternatives that differ by a single exit. Any route that shares more than 90% of its length with another, in both directions, is treated as a duplicate. When fewer than three distinct routes remain, the backend asks for routes through waypoints placed to either side of the fastest route's midpoint, and keeps distinct ones that take no more than 60% longer than the fastest. If three still can't be found, the app shows what it has and says so.

Routes are labelled A, B and C from fastest to slowest.

### Checkpoints and ETAs

Checkpoints sit at mile 0, then every 10, 25 or 50 miles, plus the destination. The ETA at each one comes from TomTom's own timing: every guidance instruction carries the distance and the elapsed time at that point, which gives a distance-to-time profile that reflects speed changes, climbs and traffic along the route. ETAs between instructions are interpolated on that profile. Driving is continuous, with no rest breaks, as the assessment describes.

Each checkpoint represents the stretch of road closer to it than to its neighbours. That is how mileage is attributed to risk levels: with 25-mile spacing, each middle checkpoint accounts for 25 miles, and the first and last account for half of the gap next to them.

### Weather

Forecasts come from Open-Meteo's hourly API (no key needed), requested for up to 100 locations per call, in parallel. All three spacings are computed in one pass, so the 10/25/50 toggle is instant.

Open-Meteo's free tier counts every location as one call and allows 600 a minute. Three routes across the country at 10-mile spacing need roughly 900 lookups, so without a commercial key a plan that would need more than 450 (`WEATHER_LOOKUP_BUDGET`) computes 25 and 50-mile spacing only. The results say so and the 10 mi option is disabled for that trip. Trips up to about 1,200 miles keep all three spacings. Setting `OPEN_METEO_API_KEY` switches to Open-Meteo's commercial endpoint and removes the limit.

- **Wind** is the sustained 10 m speed, interpolated between the two hours around the ETA. Gusts appear in the checkpoint popup for information but don't change the risk level.
- **Rain** is `rain + showers`, converted from mm to inches. Open-Meteo reports precipitation as the total for the hour ending at each timestamp, so the hour that contains the ETA is used.
- **Snow** is `snowfall`, converted from cm to inches, handled the same way.

Values are rounded to the precision shown in the interface (wind to 0.1 mph, precipitation to 0.01 in/hr) before they are classified, so the number on screen always agrees with the level beside it.

### Risk rules

| Condition | Low | Moderate | High | Severe | No travel |
|---|---|---|---|---|---|
| Wind (mph) | < 25 | 25 to < 35 | 35 to < 45 | 45 to < 55 | ≥ 55 |
| Rain (in/hr) | < 0.10 | 0.10 to < 0.25 | 0.25 to < 0.50 | 0.50 to 1.00 | > 1.00 |
| Snow (in/hr) | < 0.5 | 0.5 to < 1.0 | 1.0 to < 2.0 | 2.0 to 3.0 | > 3.0 |

The assessment's table lists some edges twice (0.25 in/hr of rain appears under both Moderate and High). A shared edge belongs to the higher band, which is how the wind row is written. The top of Severe is inclusive for rain and snow because No travel is written as a strict "greater than".

Load rules raise the wind level before the overall level is taken:

- wind ≥ 55 mph is No travel for any load;
- wind 45 to < 55 mph with more than 30,000 lb is No travel;
- wind 35 to < 45 mph with more than 40,000 lb is Severe.

The checkpoint's level is the worst of wind, rain and snow. The popup says which condition set it and whether the load rule applied.

All of this lives in `backend/routing/domain/risk.py`, with every edge covered by tests.

### Recommendation

Routes are ranked by, in order:

1. fewest No travel miles
2. fewest Severe miles
3. fewest High miles
4. lowest average risk, weighted by miles (Low = 0, Moderate = 1, High = 2, Severe = 3, No travel = 4)
5. shortest travel time

Items 2 to 5 are the assessment's list. No travel is added in front because a No travel mile is worse than a Severe one, and without it a route through a closure could beat a route with a little Severe weather. Mileage is compared to 0.1 mi and average risk to two decimals, so rounding noise can't decide the result.

The reason shown is the first criterion on which the winner beats the runner-up, for example "No Severe miles. Route C has 100 mi in Severe conditions." Travel time is compared in whole minutes, so two routes a few seconds apart count as equal. If every route crosses No travel conditions, the best one is labelled "Least exposed" rather than "Recommended", and the panel suggests a later departure.

### Corridor forecast map

The backend builds a grid around all three routes, keeping only cells within a set distance of a route (25 to 90 miles depending on trip length) and capped at 200 cells. It fetches 49 hourly values (departure hour to +48 h) for each cell and returns wind, rain, snow and the computed risk level, using the trip's cargo weight.

Grid rows are spaced evenly in Web Mercator, so each cell lines up exactly with one pixel of an image. The browser paints each forecast hour into a tiny PNG once, and the map stretches it over the corridor with linear filtering. Moving the slider swaps one image; there are no network requests and no per-frame GeoJSON work, which keeps the slider smooth even on slow machines. Risk uses the same colours as the routes. Wind, rain and snow use single-hue scales with the risk thresholds marked on the legend, and dry or calm areas are left transparent.

## Project layout

```
backend/
  config/                 Django settings and URLs
  routing/
    domain/               Pure logic, no Django or HTTP
      risk.py             Thresholds and load rules
      checkpoints.py      Checkpoint placement, mileage attribution, summaries
      recommend.py        Ranking and the reason text
      corridor.py         Mercator-aligned corridor grid for the forecast map
      geo.py              Distances, interpolation, simplification, overlap
    services/
      tomtom.py           Place search, reverse geocoding and truck routing
      weather.py          Open-Meteo client and hourly series
      planner.py          The trip planning use case
      heatmap.py          The corridor forecast use case
    serializers.py        Request validation
    middleware.py         One log line per request, with a request id
    views.py              Endpoints and error mapping
    tests/                Unit and API tests
frontend/
  src/
    App.tsx               State and layout
    components/           Form, route cards, map, forecast bar, table
    lib/                  API client, formatting, units, map styles, risk colours, heatmap frames
.github/                  CI workflow and Dependabot
render.yaml               Render blueprint for the API
```

The domain layer has no knowledge of Django or of the APIs, which is why the risk and ranking rules can be tested directly.

## Running locally

You need Python 3.12, Node 20 or later, and a free TomTom API key from [developer.tomtom.com](https://developer.tomtom.com). The key needs the Search and Routing APIs, which are enabled by default.

Backend:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then put your TomTom key in .env
python manage.py runserver
```

Frontend, in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. In development Vite forwards `/api` to `localhost:8000`, so no frontend configuration is needed.

## Quality checks

Every push and pull request runs GitHub Actions (`.github/workflows/ci.yml`). The same commands work locally:

```bash
cd backend
pip install -r requirements-dev.txt
ruff check . && ruff format --check .
python manage.py check --deploy --fail-level ERROR
coverage run manage.py test && coverage report --fail-under=90

cd ../frontend
npm run lint && npm run format:check && npm run typecheck && npm run build
```

The backend has 90 tests at 93% line coverage. They cover every edge of the risk table and load rules, the ranking order, ETA interpolation, the corridor grid, reverse geocoding, and the failure paths: TomTom rejecting a key, an address too far from a truck road, no route, a past departure, Open-Meteo rate limits, missing forecast hours, duplicate or slow alternative routes, trips shorter than one checkpoint interval, and malformed requests. External APIs are mocked, so the suite runs offline in under a second.

ESLint runs with the React hooks rules, including the newer ones that flag refs written during render, and fails on any warning. Prettier and Ruff enforce formatting. Dependabot opens weekly update PRs for Python and npm packages and monthly ones for GitHub Actions. Runtime dependencies are pinned to exact versions; Django is on the 5.2 LTS line.

Before release the interface was also checked in a headless browser against six data sets (a normal trip, every route in No travel, a single route with very long names, a cross-country trip, gaps in the forecast, and a 6-mile trip) at eight widths from 320 to 1920 px. There is no horizontal scrolling, clipped text or overlapping overlays. axe-core reports no accessibility violations, and the whole trip can be planned with the keyboard alone.

## Deploying

### API on Render

1. Push the repository to GitHub and let the first CI run finish.
2. In Render, choose **New > Blueprint** and select the repository. `render.yaml` creates the web service from `backend/`.
3. Set `TOMTOM_API_KEY`, and set `CORS_ALLOWED_ORIGINS` to the Vercel URL (for example `https://truck-route-weather.vercel.app`). `DJANGO_SECRET_KEY` is generated, and the Render hostname is added to `ALLOWED_HOSTS` automatically.
4. Check `https://<service>.onrender.com/api/health` returns `{"status": "ok", "version": "<commit>"}`.

The blueprint deploys only after the CI checks on `main` pass (`autoDeployTrigger: checksPass`), and only when something under `backend/` changed. Render waits for `/api/health` before switching traffic, so a broken build never replaces a working one. Each request is logged as one line with method, path, status, duration and a request id, which is also returned in the `X-Request-ID` header.

On Render's free plan the service sleeps after 15 minutes without traffic, and the first request then takes up to about a minute. The frontend requests `/api/config` as soon as it loads, which wakes the service while the user fills in the form.

### Checking against the real APIs

The test suite mocks TomTom and Open-Meteo. To check the whole pipeline against the real services, run the smoke test. It plans Denver to Salt Lake City with 38,000 lb and checks route count and order, distances, that ETAs start at departure and increase, that every checkpoint got a forecast, the recommendations, and the 49-hour corridor forecast:

```bash
cd backend
python manage.py smoke_test                                   # in-process, with TOMTOM_API_KEY in .env
python manage.py smoke_test --url https://<service>.onrender.com   # against the deployed API
```

It prints one PASS or FAIL line per check, a summary of the recommended route, and exits non-zero on any failure.

### Frontend on Vercel

1. Import the repository in Vercel and set **Root Directory** to `frontend`. `vercel.json` sets the build, long-term caching for hashed assets, and security headers.
2. Add the environment variable `VITE_API_BASE_URL` with the Render URL, with no trailing slash.
3. Deploy, then make sure the resulting URL is in the API's `CORS_ALLOWED_ORIGINS`.

To allow Vercel preview deployments as well, set `CORS_ALLOWED_ORIGIN_REGEXES` on Render to something like `^https://truck-route-weather-.*\.vercel\.app$`.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `TOMTOM_API_KEY` | (required) | Place search and truck routing |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | Comma-separated frontend origins |
| `CORS_ALLOWED_ORIGIN_REGEXES` | (empty) | Optional origin patterns |
| `DJANGO_SECRET_KEY` | dev value | Set in production |
| `DJANGO_DEBUG` | `false` | |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Render's hostname is added automatically |
| `TRUCK_TARE_LB` | `35000` | Empty truck and trailer weight added to the cargo for routing |
| `MAX_LOAD_LB` | `80000` | Largest cargo weight accepted |
| `MAX_DEPARTURE_DAYS` | `7` | How far ahead a departure can be |
| `TOMTOM_COUNTRY_SET` | (empty) | Limit place search, for example `US,CA` |
| `OPEN_METEO_API_KEY` | (empty) | Optional commercial key; removes the free-tier lookup limit |
| `WEATHER_LOOKUP_BUDGET` | `450` without a key, unlimited with one | Above this many forecast lookups, 10-mile spacing is skipped |
| `LOG_LEVEL` | `INFO` | |

Frontend (set in Vercel):

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | URL of the API, no trailing slash |
| `VITE_MAP_STYLE_URL` | Optional MapLibre style for the Light map; defaults to OpenFreeMap Positron |

## API

All endpoints are under `/api`.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check |
| GET | `/config` | Tare weight and input limits used by the form |
| GET | `/places?q=` | Place suggestions |
| GET | `/reverse?lat=&lon=` | Name of the nearest street or town, for a point picked on the map; `null` in open country |
| POST | `/plan` | Routes, checkpoints for all three spacings, risk summaries and recommendations |
| POST | `/heatmap` | Corridor forecast grid for 0 to 48 hours after departure |

`POST /plan` takes:

```json
{
  "origin": { "lat": 39.7392, "lon": -104.9903 },
  "destination": { "lat": 40.7608, "lon": -111.891 },
  "departure": "2026-11-05T14:00:00Z",
  "load_lb": 42000
}
```

Invalid input returns 400 with field messages, which the form shows under the matching field. A trip with no truck route, or an address too far from a road a truck can use, returns 422. Failures at TomTom or Open-Meteo return 502 with a message the interface shows as is. Requests are rate limited per client (20 plans a minute) to protect the TomTom quota.

The interface handles the rest of the failure cases without leaving the user stuck: if the corridor forecast fails, the routes stay usable and the forecast bar offers a retry; if the base map can't load, the map falls back to a plain background and still draws routes and weather; and if a request takes more than a few seconds, a note explains that the server may be starting.

## Limitations

- Forecast resolution sets a floor on accuracy. Open-Meteo's models over the US run at roughly 3 to 13 km, so 10-mile spacing doesn't add much information over flat terrain, though it does help in mountains.
- On Open-Meteo's free tier, very long trips lose the 10-mile spacing option (see Weather above), and a burst of plans in one minute can hit the rate limit. The app reports this clearly; a commercial key removes it.
- Sustained wind is classified, not gusts, because that is what the assessment's thresholds describe. A stricter operator might classify gusts instead; it is a one-line change in `planner.py`.
- Hours-of-service rest breaks are not modelled. On trips longer than about 11 hours of driving, real arrival times at later checkpoints would be later than shown.
- TomTom's free tier allows 2,500 requests a day. A plan uses one request, or up to five when detour routes are needed.
