"""Train the synthetic demand-forecast model and write the versioned artifact.

Usage:  python -m app.scripts.train_forecast [--check]

``--check`` retrains and fails if the result differs from the committed artifact
(reproducibility gate: same seed + same code ⇒ identical trees and metrics).
"""

from __future__ import annotations

import argparse
import json
import sys

from app.modules.forecast.model import ARTIFACT_PATH
from app.modules.forecast.training import train_and_evaluate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    artifact = train_and_evaluate()
    text = json.dumps(artifact, indent=1, sort_keys=True) + "\n"
    if args.check:
        committed = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        if committed.get("fingerprint") != artifact["fingerprint"] or (
            committed.get("metrics") != artifact["metrics"]
        ):
            print("Model artifact is NOT reproducible from the current code/seed.", file=sys.stderr)
            raise SystemExit(1)
        print(f"Model artifact reproducible (fingerprint {artifact['fingerprint']}).")
        return
    ARTIFACT_PATH.write_text(text, encoding="utf-8")
    m = artifact["metrics"]
    print(f"wrote {ARTIFACT_PATH.name} fingerprint={artifact['fingerprint']}")
    print(f"one-step  baseline {m['baseline']}  gbm {m['gbm']}")
    print(f"horizon-7 baseline {m['horizon_7']['baseline']}  gbm {m['horizon_7']['gbm']}")


if __name__ == "__main__":
    main()
