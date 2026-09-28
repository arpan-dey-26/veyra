# VEYRA — Demo & simulation disclosures

VEYRA is a prototype. This file is the canonical list of what is **not** real. The web page `/disclosures` mirrors it, so update both together.

| Component | Label | What is true |
|---|---|---|
| Hospitals & blood banks | Simulated | Mock providers with seeded data. **No integration** with any real hospital, blood bank or government system. |
| Demand forecasts | Synthetic data | Real model outputs, trained on a documented **synthetic** dataset. Never random numbers. |
| Temperature sensors | Simulated | Software simulator. **No physical IoT devices.** |
| Blockchain | Demo | Local development chain (Hardhat). **Not a production blockchain.** |
| Phone verification | Demo | "Demo verification only. The last 4 digits of your mobile number are used for prototype verification instead of a real OTP." **Refused at startup in production.** |
| ZK eligibility | Demo | Technical prototype. **Not a medical certification or clinical decision system.** |
| Staff invitations | Demo | No email is sent. The admin sees a one-time invitation link (shown once, labelled "Demo delivery") to share with the invitee. |
| Demo admin account | Demo | `admin@veyra.demo` is created by `app.scripts.seed_demo`, flagged `is_demo`, and refused in production. |
| Routing / ETAs | Simulated (until a real routing provider is configured) | Straight-line estimates, labelled "Estimated". |
| AI assistant | Demo (in mock mode) | With no LLM key it runs a deterministic offline mode, labelled as such. |

## Enforcement

- API: every provider-backed response carries `SourceMeta { provider, kind, simulated }` (`app/core/provenance.py`).
- Web: `SimulatedBadge` is rendered whenever `simulated === true`. `DemoRibbon` is shown in every non-production environment.
- Config: `VEYRA_ENV=production` refuses demo verification and placeholder secrets.
