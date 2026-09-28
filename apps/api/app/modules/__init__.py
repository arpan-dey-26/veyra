"""Domain modules. Each module owns: router.py → service.py → repository.py
(+ models.py, schemas.py, policies.py). Modules talk to each other only through
services. See docs/adr/0002-modular-monolith-layering.md.

Phase 0 contains only the ``system`` module (health, readiness, product meta).
"""
