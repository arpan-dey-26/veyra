"""Phase 4: synthetic demand generator, features, GBM, evaluation, and the scoped forecast API."""

from __future__ import annotations

import json
from datetime import date, timedelta
from statistics import fmean

import pytest

from app.modules.forecast.features import FEATURES, WINDOW, feature_row, seasonal_baseline
from app.modules.forecast.gbm import GBMParams, GradientBoostedTrees
from app.modules.forecast.model import ARTIFACT_PATH, load_artifact, recursive_forecast
from app.modules.forecast.service import demand_signal, pressure_band
from app.modules.forecast.synthetic import (
    GROUP_SHARE,
    SeriesKey,
    daily_demand,
    expected_demand,
    facility_level,
    generate,
    spike_factor,
)
from app.modules.forecast.training import (
    DATA_START,
    build_rows,
    chronological_split,
    metrics,
    series_keys,
    train_and_evaluate,
)
from tests import test_phase2_network as phase2
from tests.conftest import csrf
from tests.test_phase2_network import API, Net, donate, lookup

net = phase2.net  # reuse the Phase 2 network fixture (name "net")

KEY = SeriesKey("synthetic-test-facility", "HOSPITAL", "O+", "PRBC")


# ---------------------------------------------------------------- synthetic generator


def test_generator_is_deterministic_and_stateless_by_date() -> None:
    a = generate(KEY, date(2025, 1, 1), 60)
    assert a == generate(KEY, date(2025, 1, 1), 60)
    assert generate(KEY, date(2025, 1, 11), 20) == a[10:30]  # moving the window changes nothing
    assert generate(KEY, date(2025, 1, 1), 60, seed=7) != a
    other = SeriesKey("synthetic-other", "HOSPITAL", "O+", "PRBC")
    assert generate(other, date(2025, 1, 1), 60) != a
    assert all(isinstance(v, int) and v >= 0 for v in a)


def test_generator_follows_its_documented_assumptions() -> None:
    lvl = facility_level(KEY.facility_key, "HOSPITAL")
    assert 6.0 <= lvl <= 30.0
    assert 18.0 <= facility_level("synthetic-bank", "BLOOD_BANK") <= 60.0
    assert abs(sum(GROUP_SHARE.values()) - 1.0) < 1e-9
    days = [date(2025, 1, 1) + timedelta(days=i) for i in range(730)]
    # Weekdays demand more than Sundays (elective activity), on expectation.
    monday = [expected_demand("k", 10, "O+", "PRBC", d, 2026) for d in days if d.weekday() == 0]
    sunday = [expected_demand("k", 10, "O+", "PRBC", d, 2026) for d in days if d.weekday() == 6]
    assert fmean(monday) > fmean(sunday)
    # Platelet demand peaks in the late-monsoon season (September) vs March.
    sep = expected_demand("k", 10, "O+", "PLATELETS", date(2025, 9, 15), 2026)
    mar = expected_demand("k", 10, "O+", "PLATELETS", date(2025, 3, 15), 2026)
    assert sep > 1.3 * mar
    # Spikes are rare, multi-day and bounded.
    factors = [spike_factor("k", d) for d in days]
    spiky = [f for f in factors if f > 1.0]
    assert 0 < len(spiky) < 0.08 * len(days)
    assert all(1.6 <= f <= 2.4 for f in spiky)
    # Counts track the expected rate over a long window (Poisson noise averages out).
    series = [daily_demand(KEY, d) for d in days]
    lam = [expected_demand(KEY.facility_key, lvl, "O+", "PRBC", d, 2026) for d in days]
    assert abs(fmean(series) - fmean(lam)) < 0.05 * fmean(lam)


# ---------------------------------------------------------------- features & baseline


def test_features_are_explicit_and_scale_free() -> None:
    history = [float(v) for v in range(1, 29)]  # 1..28, level = 14.5
    row = feature_row(history, date(2026, 9, 28), "PLATELETS")  # a Monday
    values = dict(zip(FEATURES, row, strict=True))
    assert values["lag1"] == pytest.approx(28 / 14.5)
    assert values["lag7"] == pytest.approx(22 / 14.5)
    assert values["lag14"] == pytest.approx(15 / 14.5)
    assert values["roll7"] == pytest.approx(25 / 14.5)
    assert values["max28"] == pytest.approx(28 / 14.5)
    assert (values["dow"], values["weekend"], values["component"]) == (0.0, 0.0, 1.0)
    doubled = feature_row([2 * v for v in history], date(2026, 9, 28), "PLATELETS")
    assert doubled[:6] == pytest.approx(row[:6])  # ratios don't depend on facility size
    assert seasonal_baseline(history) == pytest.approx(fmean([22, 15, 8, 1]))
    with pytest.raises(ValueError):
        feature_row(history[:-1], date(2026, 9, 28), "PRBC")


def test_reductions_are_exact_across_python_versions() -> None:
    """Built-in sum() of floats changed in Python 3.12; training must not depend on it."""
    from app.modules.forecast.features import fmean as exact_mean
    from app.modules.forecast.features import pstdev as exact_pstdev

    assert exact_mean([0.1] * 10) == 0.1  # plain sum()/n gives 0.0999… on Python 3.11
    assert exact_pstdev([0.1] * 10) == 0.0
    assert exact_pstdev([1.0, 3.0]) == 1.0
    gbm_source = (ARTIFACT_PATH.parent / "gbm.py").read_text(encoding="utf-8")
    assert " sum(" not in gbm_source.replace("math.fsum(", "")


def test_rows_only_use_the_past_and_the_split_is_chronological() -> None:
    key = series_keys()[0]
    rows = build_rows(key, 2026)
    values = [float(v) for v in generate(key, DATA_START, len(rows) + WINDOW)]
    for t in (WINDOW, WINDOW + 100, WINDOW + len(rows) - 1):
        row = rows[t - WINDOW]
        assert row.features == feature_row(values[:t], row.day, key.component)
        assert row.y == values[t]
    split = chronological_split(rows)
    assert max(r.day for r in split.train) < split.cutoff <= min(r.day for r in split.validation)
    assert len(split.validation) == 91


def test_metrics_are_computed_correctly() -> None:
    assert metrics([1, 2, 3], [1, 2, 3]) == {"mae": 0.0, "rmse": 0.0, "wape": 0.0}
    m = metrics([2, 0, 4], [1, 1, 1])
    assert m["mae"] == pytest.approx(5 / 3, abs=1e-4)
    assert m["rmse"] == pytest.approx((11 / 3) ** 0.5, abs=1e-4)
    assert m["wape"] == pytest.approx(5 / 6, abs=1e-4)


# ---------------------------------------------------------------- GBM


def test_gbm_learns_a_step_function_deterministically() -> None:
    X = [[i / 100, (i * 7) % 3] for i in range(200)]
    y = [3.0 if x[0] > 0.5 else 1.0 for x in X]
    params = GBMParams(n_estimators=30, learning_rate=0.3, max_depth=2, min_samples_leaf=5)
    a, b = GradientBoostedTrees(params=params), GradientBoostedTrees(params=params)
    a.fit(X, y, ("x", "noise"))
    b.fit(X, y, ("x", "noise"))
    assert a.to_dict() == b.to_dict()
    assert a.predict_one([0.9, 0]) == pytest.approx(3.0, abs=0.05)
    assert a.predict_one([0.1, 0]) == pytest.approx(1.0, abs=0.05)
    restored = GradientBoostedTrees.from_dict(json.loads(json.dumps(a.to_dict())))
    assert restored.predict(X[:20]) == a.predict(X[:20])
    with pytest.raises(ValueError):
        a.fit([], [], ())


def test_committed_artifact_beats_the_baseline_and_is_reproducible() -> None:
    card = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    m = card["metrics"]
    assert card["training_data"]["kind"] == "synthetic"
    assert card["split"]["method"] == "chronological"
    for horizon in (m, m["horizon_7"]):
        assert horizon["gbm"]["mae"] < horizon["baseline"]["mae"]
        assert horizon["gbm"]["rmse"] < horizon["baseline"]["rmse"]
    # Same code + same seed ⇒ identical trees and metrics (also run by the bootstrap).
    retrained = train_and_evaluate()
    assert retrained["fingerprint"] == card["fingerprint"]
    assert retrained["metrics"] == m


def test_recursive_forecast_bounds_and_intervals() -> None:
    model = load_artifact()
    history = [float(v) for v in generate(KEY, date(2026, 8, 1), WINDOW)]
    start = date(2026, 8, 29)
    points = recursive_forecast(model.gbm, history, start, "PRBC", 14, model.q10, model.q90)
    assert len(points) == 14 and points[0].day == date(2026, 8, 29)
    for p in points:
        assert 0 <= p.lower <= p.predicted <= p.upper
    width = [p.upper - p.lower for p in points]
    assert width[-1] > width[0]  # uncertainty grows with the horizon
    for bad in (0, 15):
        with pytest.raises(ValueError):
            recursive_forecast(model.gbm, history, date(2026, 8, 29), "PRBC", bad)


def test_signal_and_pressure_bands_are_conservative() -> None:
    assert demand_signal(10, 16).status == "high"
    assert demand_signal(10, 12.5).status == "elevated"
    assert demand_signal(10, 11).status == "normal"
    assert demand_signal(0.1, 0.4).status == "normal"  # tiny series never trigger on noise
    assert pressure_band(2, 1.0) == (2.0, "pressure")
    assert pressure_band(5, 1.0) == (5.0, "watch")
    assert pressure_band(30, 1.0) == (30.0, "ok")
    assert pressure_band(0, 0.0) == (None, "ok")


# ---------------------------------------------------------------- API


async def test_hospital_forecast_is_facility_scoped_synthetic_and_deterministic(net: Net) -> None:
    url = f"{API}/forecast/demand"
    q = {"blood_group": "O+", "component": "PRBC", "horizon": 7}
    r = await net.hospital.get(url, params=q)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope"] == "facility" and body["facility_id"] == net.hospital_id
    assert len(body["history"]) == 28 and len(body["forecast"]) == 7
    assert body["source"]["kind"] == "synthetic" and body["source"]["simulated"] is True
    assert "not clinical guidance" in body["disclaimer"]
    assert body["model"]["fingerprint"] == load_artifact().fingerprint
    assert body["model"]["trained_on"] == "synthetic"
    assert body["forecast"][0]["day"] == "2026-09-28"  # today in the network's offset
    assert body["history"][-1]["day"] == "2026-09-27"
    assert body["signal"]["status"] in {"normal", "elevated", "high"}
    again = await net.hospital.get(url, params=q)
    assert again.json()["forecast"] == body["forecast"]
    other = await net.hospital2.get(url, params=q)
    assert other.json()["forecast"] != body["forecast"]  # each facility has its own profile


@pytest.mark.parametrize(
    "params",
    [
        {"blood_group": "O+", "horizon": 0},
        {"blood_group": "O+", "horizon": 15},
        {"blood_group": "O+", "component": "WHOLE_BLOOD"},
        {"blood_group": "O"},
        {},
    ],
)
async def test_forecast_input_validation(net: Net, params: dict[str, object]) -> None:
    r = await net.hospital.get(f"{API}/forecast/demand", params=params)
    assert r.status_code == 422


async def test_facilities_cannot_read_other_facilities(net: Net) -> None:
    q = {"blood_group": "O+", "facility_id": net.bank_id}
    assert (await net.hospital.get(f"{API}/forecast/demand", params=q)).status_code == 404
    q_sum = {"facility_id": net.hospital_id}
    assert (await net.bank.get(f"{API}/forecast/summary", params=q_sum)).status_code == 404
    own = {"blood_group": "O+", "facility_id": net.hospital_id}
    assert (await net.hospital.get(f"{API}/forecast/demand", params=own)).status_code == 200


async def test_bank_summary_compares_real_stock_with_the_forecast(net: Net) -> None:
    donor_id = (await lookup(net.bank))["donor_id"]
    await donate(net.bank, donor_id, components=["PRBC", "PLATELETS"])  # 1 x O+ PRBC, 1 x PLT
    s = (await net.bank.get(f"{API}/forecast/summary", params={"horizon": 7})).json()
    assert s["scope"] == "facility" and s["facility_id"] == net.bank_id
    assert len(s["rows"]) == 24  # 8 groups x PRBC/PLATELETS/FFP
    row = next(r for r in s["rows"] if (r["blood_group"], r["component"]) == ("O+", "PRBC"))
    assert row["stock_available"] == 1
    assert row["pressure"] in {"ok", "watch", "pressure"}
    assert row["coverage_days"] == pytest.approx(1 / row["forecast_daily_mean"], abs=0.06)
    assert sum(s["signal_counts"].values()) == 24
    other = (await net.bank2.get(f"{API}/forecast/summary")).json()
    assert all(r["stock_available"] == 0 for r in other["rows"])


async def test_admin_sees_the_network_or_any_facility(net: Net) -> None:
    n = (await net.admin.get(f"{API}/forecast/demand", params={"blood_group": "O+"})).json()
    assert n["scope"] == "network" and n["facility_id"] is None
    assert n["facilities_included"] == 2  # the two hospitals
    h = (await net.hospital.get(f"{API}/forecast/demand", params={"blood_group": "O+"})).json()
    h2 = (await net.hospital2.get(f"{API}/forecast/demand", params={"blood_group": "O+"})).json()
    pairs = zip(h["forecast"], h2["forecast"], strict=True)
    total = [a["predicted"] + b["predicted"] for a, b in pairs]
    assert [p["predicted"] for p in n["forecast"]] == pytest.approx(total, abs=0.02)
    one = await net.admin.get(f"{API}/forecast/summary", params={"facility_id": net.bank_id})
    assert one.status_code == 200 and one.json()["scope"] == "facility"
    s = (await net.admin.get(f"{API}/forecast/summary")).json()
    assert s["scope"] == "network" and all(r["stock_available"] is None for r in s["rows"])


async def test_forecast_rbac_and_model_card(net: Net) -> None:
    for path in ("/forecast/demand?blood_group=O%2B", "/forecast/summary", "/forecast/model"):
        assert (await net.donor.get(API + path)).status_code == 403
    card = (await net.hospital.get(f"{API}/forecast/model")).json()
    assert card["fingerprint"] == load_artifact().fingerprint
    assert any("Clinical" in x for x in card["not_intended_for"])
    assert card["one_step"]["gbm"]["mae"] < card["one_step"]["baseline"]["mae"]
    assert "not a certified medical prediction system" in card["disclaimer"]


async def test_forecast_payloads_carry_no_personal_data(net: Net) -> None:
    donor_id = (await lookup(net.bank))["donor_id"]
    await donate(net.bank, donor_id, components=["PRBC"])
    for client, path in (
        (net.hospital, "/forecast/demand?blood_group=O%2B"),
        (net.bank, "/forecast/summary"),
        (net.admin, "/forecast/summary"),
        (net.admin, "/forecast/model"),
    ):
        text = (await client.get(API + path)).text
        for secret in ("Arpan", "Rina", "9876543210", "arpan@example.in", "donor", "patient_"):
            assert secret not in text, (path, secret)


async def test_forecast_is_read_only(net: Net) -> None:
    r = await net.hospital.post(f"{API}/forecast/summary", headers=csrf(net.hospital))
    assert r.status_code == 405
