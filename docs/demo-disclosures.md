# VEYRA — Demo & simulation disclosures

VEYRA is a prototype. This file is the canonical list of what is **not** real. The web page `/disclosures` mirrors it, so update both together.

| Component | Label | What is true |
|---|---|---|
| Partner blood banks (`provider = mock`) | Simulated | `MockBloodBankProvider`: three fictional banks with deterministic, generated availability. Requests to them are auto-acknowledged and **nothing is dispatched**. **No integration** with any real hospital, blood bank or government system. Refused in production (`VEYRA_ENABLE_MOCK_BLOOD_BANKS`). |
| Demo facilities | Demo | "VEYRA Central Blood Bank (Demo)" and "VEYRA City Hospital (Demo)" are seeded by `app.scripts.seed_demo` with staff logins `bank@veyra.demo` / `hospital@veyra.demo`. They run the real VEYRA workflows on demo data. |
| Bag trace chain | Tamper-evident (database) | Each bag's events are append-only (DB trigger) and SHA-256 hash-chained inside PostgreSQL. **Not anchored on any blockchain yet** (Phase 8). |
| Component shelf lives | Prototype defaults | Whole blood 35 d, PRBC 42 d, FFP/cryo 365 d, platelets 5 d, 90-day donation interval. Verify against current national guidelines before real use. |
| Demand forecasts | Synthetic data | Real model outputs, trained on a documented **synthetic** dataset. Never random numbers. |
| Temperature sensors | Simulated | Software simulator: simulated device ids, RFID tags, battery and readings, with prototype thresholds. **No physical IoT devices.** This is simulated IoT telemetry for a student engineering prototype and is not a certified medical monitoring system. |
| Blockchain | Demo | Local development chain (Hardhat). **Not a production blockchain.** |
| Phone verification | Demo | "Demo verification only. The last 4 digits of your mobile number are used for prototype verification instead of a real OTP." **Refused at startup in production.** |
| ZK eligibility | Demo | Technical prototype. **Not a medical certification or clinical decision system.** |
| Staff invitations | Demo | No email is sent. The admin sees a one-time invitation link (shown once, labelled "Demo delivery") to share with the invitee. |
| Demo accounts | Demo | `admin@veyra.demo`, `bank@veyra.demo`, `hospital@veyra.demo` (password `veyra-demo-console-2026`) are created by `app.scripts.seed_demo`, flagged `is_demo`; the script refuses to run in production. |
| Routing / ETAs | Simulated | Deterministic schematic estimates (distance band by city/state, simulated speed and route status), labelled "Simulated routing — prototype". **No GPS, maps or traffic data.** |
| Logistics / shipments | Simulated | Fictional couriers, schematic checkpoints (no coordinates) and deterministic ETAs, labelled "Simulated logistics — prototype". This is a simulated logistics prototype. Routes, courier status and ETAs are not real-world navigation or delivery guarantees. Receipt is always confirmed by a person. |
| Operational recommendations | Prototype | Explainable, rule-based priority, pressure and bag-ranking with structured reasons. This is an operational engineering prototype. Recommendations are not clinical decisions or medical advice. Nothing is dispatched without a person confirming it. |
| AI assistant | Demo (in mock mode) | With no LLM key it runs a deterministic offline mode, labelled as such. |

## Enforcement

- API: every provider-backed response carries `SourceMeta { provider, kind, simulated }` (`app/core/provenance.py`).
- Web: `SimulatedBadge` is rendered whenever `simulated === true`. `DemoRibbon` is shown in every non-production environment.
- Config: `VEYRA_ENV=production` refuses demo verification and placeholder secrets.
