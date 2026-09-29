# PHASE STATUS — Phase 4: ML Predictive Demand & Crisis Forecasting

> **Synthetic ML forecast — prototype.** Trained and run on synthetic demand data. This is not clinical guidance and not a certified medical prediction system. The full model card is [`docs/model-cards/demand-forecast.md`](../model-cards/demand-forecast.md).

## Phase 3 final gate
Real Windows bootstrap, 2026-09-29: **`OVERALL: PASS (34/34 steps passed)`**. The run is saved as `docs/phase-reports/phase-3-verification.log`.

The last failure was `niceMax(0)` returning 5 instead of 4. The function clamped the value up to the floor and then rounded the floor itself onto the 1/2/2.5/5 ladder. Now, empty or tiny data uses the floor directly, and only larger values are rounded. The test is unchanged.

## Architecture

```
app/modules/forecast/
  synthetic.py   deterministic synthetic demand generator (stateless by date, seeded)
  features.py    explicit, scale-free features + seasonal baseline
  gbm.py         pure-Python gradient-boosted regression trees (deterministic, JSON-serialisable)
  training.py    reference dataset → chronological split → baseline vs GBM metrics → artifact
  model.py       artifact loader (cached per process) + recursive multi-day forecaster
  demand_model_v1.json   committed, versioned model artifact (fingerprint 47213848aae9e96b)
  schemas.py / service.py / router.py   scoped read-only API
app/scripts/train_forecast.py   retrain (or --check reproducibility)
```

Design choices:
- **No new dependencies.** numpy and scikit-learn are not in the stack, and scikit-learn would add scipy to the image. A ~150-line GBM is enough here and fully testable.
- **No Redis, worker or database schema.**
  - Synthetic history is generated on demand, deterministically per facility and date: about 1 ms per series.
  - The model is an immutable versioned artifact, loaded once per process.
  - **No migration.** `alembic check` stays clean.
- **Training is offline and reproducible.**
  - `train_forecast --check` retrains (about 5 s) and must reproduce the committed fingerprint and metrics exactly. This is a unit test and a bootstrap step, so it runs on Windows' own math library.
  - Transcendental values are rounded to 12 decimals. Poisson draws use exact additivity instead of `gauss()`, so Linux and Windows produce identical data and trees.

## Synthetic data design
The generator combines:
- a per-facility level
- an approximate ABO/Rh mix
- component shares
- a day-of-week factor
- an annual cycle plus a late-monsoon platelet bump
- rare 1–3 day surges shared across a facility
- exact Poisson noise

It is stateless by date: each (series, day) has its own SHA-256-seeded RNG, so moving the window never changes a day's value. No real patient, donor or hospital data is used. Every assumption is listed in the model card.

## Models, features and metrics
- **Features** (12, all from history strictly before the target day, scaled by the trailing 28-day level):
  - lags 1/7/14
  - 7-day mean and standard deviation, 28-day max
  - log level
  - day of week and weekend flag
  - annual sin/cos
  - component
- **Baseline:** the same weekday's mean over the last 4 weeks.
- **GBM:** 60 trees, depth 3, learning rate 0.12, 40 samples per leaf minimum, 16 quantile bins. Multi-day forecasts are recursive.
- **Split:** chronological. Train through 2025-08-31 (15,444 rows); validate from 2025-09-01 for 91 days (3,276 rows).

| Horizon | Baseline MAE / RMSE / WAPE | GBM MAE / RMSE / WAPE |
|---|---|---|
| Next day | 1.1717 / 1.7823 / 53.0% | **1.0703 / 1.6083 / 48.4%** |
| 7-day recursive | 1.1717 / 1.7823 / 53.0% | **1.0815 / 1.6230 / 48.9%** |

- MAPE is omitted because zero-demand days make it undefined.
- The gain is modest and reported as such.

**Uncertainty:** an approximately 80% band from the validation residual quantiles (q10/q90 relative to level), widened by √step.

## API (read-only, GET only)

| Endpoint | Returns |
|---|---|
| `GET /forecast/demand?blood_group&component&horizon&facility_id` | 28 days of synthetic history, a 1–14 day forecast with lower/upper/baseline, a demand signal, model info, `source.kind = synthetic` and the disclaimer |
| `GET /forecast/summary?horizon&facility_id` | 8 groups × PRBC/platelets/FFP. For your own facility it adds real usable stock, coverage in days and a pressure band (pressure < 3 d, watch < 7 d). Also signal counts. |
| `GET /forecast/model` | The model card, including metrics, split, features, limitations and disclaimer |

Validation:
- `horizon` must be 1–14.
- `component` must be one of PRBC, platelets or FFP, the components the model was trained on.
- Any invalid value returns 422.

## RBAC and scope

| Role | Access |
|---|---|
| Hospital, blood bank | Own facility only (`forecast:read:own_facility`). Another facility's id returns **404**, so existence is never confirmed. |
| Admin | Network aggregate (the sum of active hospitals) or any single facility (`network:read`) |
| Donor | **403** on every forecast endpoint |
| Anonymous | 401 |

- The new endpoints are in the RBAC matrix (3 rows × 5 roles).
- A new `require_any(...)` dependency permits either permission; the service then applies scope.
- Existing permissions are unchanged.

## Crisis / anomaly signal (prototype)
- **high:** forecast daily mean ≥ 1.5 × the trailing 28-day mean.
- **elevated:** ≥ 1.2 ×.
- **normal:** everything else.
- Minimum volumes apply, so tiny series never trigger a signal on noise alone.
- Labelled everywhere as "Prototype indicator, not a medical alert". The signal never claims to predict clinical crises.

## Dashboards
**Hospital and blood bank: new Forecast tab**
- Prototype banner.
- Group, component and horizon (7/14 days) selectors.
- Tiles: forecast total, per-day vs history, signal, scope.
- History → forecast line chart with an interval band, crosshair tooltip, Table view and empty state.
- Model label (name, version, "trained on synthetic data", validation MAE vs baseline).
- Upcoming demand by blood group.
- Hospitals: a demand-signal list.
- Blood banks: **supply vs forecast**, i.e. real stock against the synthetic forecast, with coverage days and pressure bands.

**Overview (both roles)**
- A 7-day demand outlook card (signal and pressure counts) that links to the Forecast tab.

**Admin**
- Network demand forecast by blood group per component.
- Model evaluation table (baseline vs GBM, next day and 7-day).
- Fingerprint and seed, plus the disclaimer.

**Every view**
- Loading skeleton, error with **Try again**, empty states.
- Labelled selects, and a chart `aria-label` describing history and horizon.
- Responsive tile grid and scrollable tables.
- Light and dark mode via tokens.

## Security and privacy
- Forecast payloads carry facility names and synthetic counts only. There is no donor, patient or user identity (tested for all endpoints).
- Real inventory appears only in the caller's own facility summary.
- The endpoints are read-only (POST returns 405), so CSRF and session protections are unchanged.
- No audit entries: forecasts are reads, as with the dashboards.

## Tests
- **API** `test_phase4_forecast.py`: 21 tests.
  - generator: determinism, statelessness by date, documented assumptions (weekday effect, platelet season, rare bounded spikes, Poisson mean)
  - features: exact values, scale-free
  - no leakage + chronological split
  - metric maths
  - GBM: fit, determinism, JSON round-trip
  - **committed artifact beats the baseline and reproduces exactly on retrain**
  - interval bounds and horizon validation
  - signal and pressure thresholds
  - facility scope and determinism
  - input validation (5 cases), cross-facility 404
  - bank real stock vs forecast
  - admin network = sum of hospitals
  - donor 403, model card
  - no personal data, read-only
- **API** `test_integration_phase4.py` (PostgreSQL): real stock in the bank summary, hospital scope and 404, admin network view, donor 403.
- **RBAC matrix**: +3 rows.
- **Web** `forecast.test.tsx`: 14 tests.
  - mapping: timeline, by-group bars, attention order
  - chart: series and legend, accessible label, table view, empty state
  - panel: disclaimer, model label, horizon refetch, bank supply table, error and retry
  - outlook card
  - admin: evaluation table, empty network, error
- **Bootstrap**, 2 new steps:
  - `ml: forecast model reproducible (retrain == committed artifact)`
  - `e2e: phase 4 synthetic ML forecast (scoped, disclaimer, RBAC, via web proxy)`: hospital and bank dashboard pages → forecast → chart/table data → disclaimer → scope 404 → horizon 422 → bank stock → admin network + model card → donor 403

## Known limitations
- Every facility's history is synthetic (seeded by facility id); VEYRA has no real demand history yet.
- Intervals are approximate and don't cover random surges.
- The model covers three components.
- The E2E step verifies the dashboard pages load and the forecast payloads behind the chart and table. Rendering itself is covered by Vitest; there's no headless browser in the bootstrap.
- Network forecasts are recomputed per request (about 24 series × N hospitals). That's fine for a prototype; a cache is the next step at scale.

## Future production work
- Train on real, consented, de-identified demand history, with data governance.
- Add holiday and outbreak covariates, per-facility calibration, and a probabilistic model (e.g. quantile GBM).
- Run a backtesting service, drift monitoring and a scheduled retraining job (a worker, when real data exists).
- Add clinical and operational review before any decision use.
