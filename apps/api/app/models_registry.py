"""The ORM model registry: importing this module registers EVERY table on ``Base.metadata``.

Alembic (``migrations/env.py``) imports it so autogenerate / ``alembic check`` compare the
database against the complete model set. ``tests/test_models_registry.py`` fails if a new
``app/modules/*/models.py`` is not listed here.
"""

from __future__ import annotations

import app.modules.audit.models
import app.modules.bags.models
import app.modules.donations.models
import app.modules.donors.models
import app.modules.facilities.models
import app.modules.identity.models
import app.modules.logistics.models
import app.modules.outbox.models
import app.modules.requests.models
import app.modules.telemetry.models  # noqa: F401
from app.core.db import Base

MODEL_MODULES: tuple[str, ...] = (
    "app.modules.audit.models",
    "app.modules.bags.models",
    "app.modules.donations.models",
    "app.modules.donors.models",
    "app.modules.facilities.models",
    "app.modules.identity.models",
    "app.modules.logistics.models",
    "app.modules.outbox.models",
    "app.modules.requests.models",
    "app.modules.telemetry.models",
)

metadata = Base.metadata
