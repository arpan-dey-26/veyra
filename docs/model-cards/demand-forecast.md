# Model card — `veyra-demand-gbm` v1.0.0

> **Synthetic ML forecast — prototype.** Trained and run on synthetic demand data. This is **not clinical guidance** and **not a certified medical prediction system**.

| | |
|---|---|
| Artifact | `apps/api/app/modules/forecast/demand_model_v1.json` |
| Fingerprint | `47213848aae9e96b` (SHA-256 of the serialised trees) |
| Data generator | `synthetic-demand-v1`, seed `2026` |
| Reproduce | `uv run python -m app.scripts.train_forecast --check` (also a bootstrap gate) |

## Purpose
This is prototype short-term (1–14 day) blood-demand forecasting, by blood group and component. It shows how a network could anticipate demand and compare it with the stock actually on hand.

## Intended use
- Engineering demonstration and UI prototyping inside VEYRA.
- Every figure is labelled "Synthetic ML forecast — prototype".

## Not intended for
- Clinical decisions, transfusion planning or patient care.
- Real ordering, staffing or procurement without validated real-world data.
- Predicting medical emergencies or crises. The demand signals (normal / elevated / high) are operational prototype indicators only.

## Training data (synthetic)
The data is generated from hand-chosen assumptions. No real patient, donor or hospital data is used.

- **Facility level:** red-cell units/day, drawn per facility key (hospitals 6–30, blood banks 18–60).
- **Blood-group share (approximate):** O+ 36%, B+ 32%, A+ 21%, AB+ 7%, O− 1.5%, B− 1.2%, A− 0.8%, AB− 0.5%.
- **Component share vs red cells:** platelets 0.45, FFP 0.35, whole blood 0.15, cryo 0.08.
- **Day of week:** Monday ×1.08 down to Sunday ×0.74 (elective activity).
- **Season:**
  - an annual ±10% cycle
  - a late-monsoon platelet bump peaking mid-September (+45%), a dengue-season-like pattern
- **Spikes:** 1.2% of days start a 1–3 day surge of ×1.6–2.4, shared by a facility's series.
- **Noise:** exact Poisson counts.
- **Determinism:**
  - Every (series, day) draws from its own SHA-256-seeded RNG, so values are stateless by date.
  - Transcendental results are rounded to 12 decimals, so Linux and Windows produce identical data and trees.

Reference training universe:
- profiles: synthetic-hospital-a, synthetic-hospital-b, synthetic-bank-a
- groups: O+, A+, AB+, O-
- components: PRBC, PLATELETS, FFP
- period: 548 days from 2024-06-01

## Features (explicit, `features.py`)
All features come from history strictly before the target day. Values are divided by the trailing 28-day level, so a single model serves small and large facilities.

- **Lags:** `lag1`, `lag7`, `lag14`
- **Recent pattern:** `roll7`, `roll7_sd`, `max28`
- **Scale:** `log_level`
- **Calendar:** `dow`, `weekend`, `doy_sin`, `doy_cos`
- **Component:** `component`

The target is `demand / level`.

## Models
- **Baseline (transparent):** the mean of the same weekday over the last 4 weeks (seasonal naive).
- **GBM:** gradient-boosted regression trees, squared error, in pure Python with no ML dependency.
  - Settings: 60 trees, depth 3, learning rate 0.12, min 40 samples/leaf, 16 quantile bins.
  - No row or feature sampling, so training is deterministic.
  - Multi-day forecasts are recursive: each predicted day feeds the next.

## Evaluation
The split is strictly chronological: train up to 2025-08-31 (15444 rows), validation from 2025-09-01 (91 days, 3276 rows). No future observation reaches training.

| Horizon | Model | MAE | RMSE | WAPE |
|---|---|---|---|---|
| Next day | Seasonal baseline | 1.1717 | 1.7823 | 53.0% |
| Next day | GBM | **1.0703** | **1.6083** | **48.4%** |
| 7-day recursive | Seasonal baseline | 1.1717 | 1.7823 | 53.0% |
| 7-day recursive | GBM | **1.0815** | **1.623** | **48.9%** |

- MAPE is not reported: zero-demand days make it undefined.
- For horizons up to 7 days the seasonal baseline only uses observed lags, so its 7-day and next-day scores are identical by construction.
- The GBM's gain is modest (about 9% lower MAE), as expected on noisy Poisson counts.

## Uncertainty
- Intervals come from empirical quantiles of the validation residuals relative to level: q10 = -1.0282, q90 = 1.2081.
- They are widened by √step and clipped at 0.
- Nominal coverage is about 80%. They are approximate, not a calibrated guarantee.

## Limitations, biases and assumptions
- Real demand has drivers the generator doesn't model (hospital mix, procedures, referral patterns, holidays, outbreaks).
- Each VEYRA facility's "history" is itself synthetic, seeded by the facility id, because the prototype has no real demand history.
- Group and component shares are rounded approximations applied uniformly to every facility.
- Spikes are random in the data, so no model can foresee them. The interval does not cover them.
- Components are limited to PRBC, platelets and FFP (what the model was trained on).
- The network forecast sums hospital forecasts, and sums intervals as well (conservative).

## Security and privacy
- Forecast payloads contain facility names and synthetic counts only.
- They never contain donor, patient or user identity.
- Access follows RBAC and facility scope (see the Phase 4 report).
