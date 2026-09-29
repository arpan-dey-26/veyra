"""Dashboard read models (Phase 3). Aggregates only; every figure is scoped.

- Facility dashboards cover the caller's facility only (requests it sent or received,
  donations it collected, bags it holds, events addressed to it).
- The admin dashboard is network-wide but carries counts, not records: no donor data,
  no audit IPs or metadata.
- The network graph shows a hospital its own requests and the blood banks it could
  request from; a blood bank sees the hospitals that requested from it. Admins see all.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from app.core.clock import Clock
from app.core.errors import PermissionDeniedError
from app.core.rbac import AuthContext, Permission, Role
from app.modules.bags.service import require_facility
from app.modules.dashboard.schemas import (
    ActivityItem,
    AdminDashboard,
    AuditItem,
    AuditSummary,
    DayCount,
    DonationSummary,
    ExpiryBucket,
    FacilityDashboard,
    FacilityTotals,
    MovementDay,
    NetworkEdge,
    NetworkGraph,
    NetworkNode,
    RequestSummary,
    RoleCount,
    StatusCount,
)
from app.modules.outbox.models import OutboxEvent
from app.modules.requests.models import BloodRequest
from app.persistence.repositories import UnitOfWork
from app.providers.bloodbank import MOCK_BANKS

WINDOW_DAYS = 14
GRAPH_WINDOW_DAYS = 30
ACTIVITY_LIMIT = 15
OPEN_STATUSES = frozenset({"pending", "acknowledged", "dispatched"})
REQUEST_STATUSES = ("pending", "acknowledged", "dispatched", "fulfilled", "rejected", "cancelled")
BAG_STATUSES = ("available", "in_transit", "received", "discarded")

_EXPIRY_BUCKETS: tuple[tuple[str, str, timedelta | None], ...] = (
    ("lt_1d", "< 24 h", timedelta(days=1)),
    ("d1_3", "1-3 days", timedelta(days=3)),
    ("d3_7", "3-7 days", timedelta(days=7)),
    ("d7_30", "7-30 days", timedelta(days=30)),
    ("gt_30d", "> 30 days", None),
)
_ACTIVITY_FIELDS = ("reference", "status", "blood_group", "component", "units", "urgency", "reason")


def status_counts(counts: dict[str, int], order: tuple[str, ...]) -> list[StatusCount]:
    """Fixed order, zeros included: charts and legends stay stable as data changes."""
    return [StatusCount(status=s, count=counts.get(s, 0)) for s in order]


def day_series(times: list[datetime], *, days: int, today: date, tz: timezone) -> list[DayCount]:
    counts = Counter(t.astimezone(tz).date() for t in times)
    start = today - timedelta(days=days - 1)
    return [
        DayCount(day=start + timedelta(days=i), count=counts.get(start + timedelta(days=i), 0))
        for i in range(days)
    ]


def expiry_buckets(expiries: list[datetime], now: datetime) -> list[ExpiryBucket]:
    out = [ExpiryBucket(bucket="expired", label="Expired", count=0)]
    out += [ExpiryBucket(bucket=key, label=label, count=0) for key, label, _ in _EXPIRY_BUCKETS]
    by_key: dict[str, ExpiryBucket] = {b.bucket: b for b in out}
    for exp in expiries:
        left = exp - now
        if left <= timedelta(0):
            by_key["expired"].count += 1
            continue
        for key, _, limit in _EXPIRY_BUCKETS:
            if limit is None or left < limit:
                by_key[key].count += 1
                break
    return out


def activity_item(event: OutboxEvent) -> ActivityItem:
    payload = event.payload or {}
    extra = {k: payload.get(k) for k in _ACTIVITY_FIELDS}
    return ActivityItem.model_validate(
        {
            "event_id": str(event.event_id),
            "topic": event.topic,
            "created_at": event.created_at,
            **{k: v for k, v in extra.items() if v is not None},
        }
    )


class DashboardService:
    def __init__(self, uow: UnitOfWork, clock: Clock, *, utc_offset_minutes: int) -> None:
        self._uow = uow
        self._clock = clock
        self._offset = utc_offset_minutes
        self._tz = timezone(timedelta(minutes=utc_offset_minutes))

    def _today(self, now: datetime) -> date:
        return now.astimezone(self._tz).date()

    def _window_start(self, now: datetime, days: int) -> datetime:
        start_day = self._today(now) - timedelta(days=days - 1)
        return datetime(start_day.year, start_day.month, start_day.day, tzinfo=self._tz)

    async def _movements(
        self, facility_id: UUID | None, now: datetime, today: date
    ) -> list[MovementDay]:
        events = await self._uow.stats.bag_events_since(
            facility_id=facility_id,
            since=self._window_start(now, WINDOW_DAYS),
            event_types=("DISPATCHED", "RECEIVED"),
        )
        tz = self._tz
        dispatched = Counter(
            e.occurred_at.astimezone(tz).date() for e in events if e.event_type == "DISPATCHED"
        )
        received = Counter(
            e.occurred_at.astimezone(tz).date() for e in events if e.event_type == "RECEIVED"
        )
        start = today - timedelta(days=WINDOW_DAYS - 1)
        days = [start + timedelta(days=i) for i in range(WINDOW_DAYS)]
        return [
            MovementDay(day=d, dispatched=dispatched.get(d, 0), received=received.get(d, 0))
            for d in days
        ]

    async def _activity(self, facility_id: UUID | None) -> list[ActivityItem]:
        recent = await self._uow.stats.recent_outbox(limit=200)
        key = str(facility_id) if facility_id else None
        items = [e for e in recent if key is None or key in (e.audience or [])]
        return [activity_item(e) for e in items[:ACTIVITY_LIMIT]]

    # ------------------------------------------------------------------ facility

    async def facility(self, ctx: AuthContext) -> FacilityDashboard:
        facility_id = require_facility(ctx)
        facility = await self._uow.facilities.get(facility_id)
        if ctx.role not in (Role.HOSPITAL, Role.BLOOD_BANK) or facility is None:
            raise PermissionDeniedError()
        hospital = ctx.role is Role.HOSPITAL
        now = self._clock.now()
        today = self._today(now)

        counts = await self._uow.stats.request_status_counts(
            hospital_id=facility_id if hospital else None,
            target_facility_id=None if hospital else facility_id,
        )
        open_ids = OPEN_STATUSES
        recent = await self._uow.stats.requests_since(
            facility_id=facility_id, since=now - timedelta(days=365)
        )
        mine = [
            r
            for r in recent
            if (r.hospital_id if hospital else r.target_facility_id) == facility_id
        ]
        requests = RequestSummary(
            direction="outgoing" if hospital else "incoming",
            total=sum(counts.values()),
            open=sum(n for s, n in counts.items() if s in open_ids),
            emergency_open=sum(
                1 for r in mine if r.status in open_ids and r.urgency == "emergency"
            ),
            by_status=status_counts(counts, REQUEST_STATUSES),
        )

        if hospital:
            donations = DonationSummary(applicable=False, today=0, window_total=0, by_day=[])
        else:
            times = await self._uow.stats.donation_times_since(
                facility_id=facility_id, since=self._window_start(now, WINDOW_DAYS)
            )
            series = day_series(times, days=WINDOW_DAYS, today=today, tz=self._tz)
            donations = DonationSummary(
                applicable=True,
                today=series[-1].count,
                window_total=sum(d.count for d in series),
                by_day=series,
            )

        expiries = await self._uow.stats.on_hand_expiries(facility_id)
        buckets = expiry_buckets(expiries, now)
        return FacilityDashboard(
            facility_id=facility_id,
            facility_name=facility.name,
            kind="HOSPITAL" if hospital else "BLOOD_BANK",
            generated_at=now,
            window_days=WINDOW_DAYS,
            utc_offset_minutes=self._offset,
            requests=requests,
            donations=donations,
            movements=await self._movements(facility_id, now, today),
            on_hand=sum(b.count for b in buckets if b.bucket != "expired"),
            expiry=buckets,
            activity=await self._activity(facility_id),
        )

    # ------------------------------------------------------------------ admin

    async def admin(self, ctx: AuthContext) -> AdminDashboard:
        if not (ctx.has(Permission.NETWORK_READ) and ctx.has(Permission.AUDIT_READ)):
            raise PermissionDeniedError()
        now = self._clock.now()
        today = self._today(now)
        per_role: dict[str, dict[str, int]] = {}
        for role, status, n in await self._uow.stats.user_counts():
            per_role.setdefault(role, {})[status] = n
        users = [
            RoleCount(
                role=r.value,
                active=per_role.get(r.value, {}).get("active", 0),
                pending_verification=per_role.get(r.value, {}).get("pending_verification", 0),
                disabled=per_role.get(r.value, {}).get("disabled", 0),
                total=sum(per_role.get(r.value, {}).values()),
            )
            for r in Role
        ]
        facilities = await self._uow.stats.active_facilities()
        times = await self._uow.stats.donation_times_since(
            facility_id=None, since=self._window_start(now, WINDOW_DAYS)
        )
        actions = await self._uow.stats.audit_action_counts_since(now - timedelta(hours=24))
        top = sorted(actions.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
        recent_audit = await self._uow.stats.recent_audit(limit=12)
        return AdminDashboard(
            generated_at=now,
            window_days=WINDOW_DAYS,
            utc_offset_minutes=self._offset,
            users=users,
            users_total=sum(u.total for u in users),
            facilities=FacilityTotals(
                blood_banks=sum(1 for f in facilities if f.type == "BLOOD_BANK"),
                hospitals=sum(1 for f in facilities if f.type == "HOSPITAL"),
                simulated=sum(1 for f in facilities if f.is_simulated),
            ),
            requests_by_status=status_counts(
                await self._uow.stats.request_status_counts(
                    hospital_id=None, target_facility_id=None
                ),
                REQUEST_STATUSES,
            ),
            bags_by_status=status_counts(await self._uow.stats.bag_status_counts(), BAG_STATUSES),
            donations_by_day=day_series(times, days=WINDOW_DAYS, today=today, tz=self._tz),
            movements=await self._movements(None, now, today),
            audit=AuditSummary(
                last_24h=sum(actions.values()),
                top_actions=[StatusCount(status=a, count=n) for a, n in top],
                recent=[
                    AuditItem(
                        action=a.action,
                        resource=a.resource,
                        actor_type=a.actor_type,
                        created_at=a.created_at,
                    )
                    for a in recent_audit
                ],
            ),
            activity=await self._activity(None),
        )

    # ------------------------------------------------------------------ network graph

    async def graph(self, ctx: AuthContext) -> NetworkGraph:
        now = self._clock.now()
        is_admin = ctx.role is Role.ADMIN and ctx.has(Permission.NETWORK_READ)
        self_id = None if is_admin else require_facility(ctx)
        facilities = {f.id: f for f in await self._uow.stats.active_facilities()}
        requests = await self._uow.stats.requests_since(
            facility_id=self_id, since=now - timedelta(days=GRAPH_WINDOW_DAYS)
        )
        if self_id is not None and ctx.role is Role.BLOOD_BANK:
            requests = [r for r in requests if r.target_facility_id == self_id]
        elif self_id is not None:
            requests = [r for r in requests if r.hospital_id == self_id]

        def target_node(r: BloodRequest) -> str:
            if r.target_facility_id:
                return str(r.target_facility_id)
            return f"mock:{r.target_external_ref}"

        edges: dict[tuple[str, str], list[BloodRequest]] = {}
        for r in requests:
            edges.setdefault((str(r.hospital_id), target_node(r)), []).append(r)

        visible: set[str] = {n for pair in edges for n in pair}
        if self_id is not None:
            visible.add(str(self_id))
        if is_admin:
            visible |= {str(f) for f in facilities}
        elif ctx.role is Role.HOSPITAL:
            # Hospitals may already discover every onboarded blood bank (availability search).
            visible |= {
                str(f.id)
                for f in facilities.values()
                if f.type == "BLOOD_BANK" and not f.is_simulated
            }

        mock_names = {f"mock:{b.ref}": b for b in MOCK_BANKS}
        nodes: list[NetworkNode] = []
        for node_id in sorted(visible):
            if node_id in mock_names:
                bank = mock_names[node_id]
                nodes.append(
                    NetworkNode(
                        id=node_id,
                        name=bank.name,
                        kind="BLOOD_BANK",
                        city=bank.city,
                        simulated=True,
                        is_self=False,
                    )
                )
                continue
            try:
                facility = facilities.get(UUID(node_id))
            except ValueError:
                facility = None
            if facility is None:
                continue
            nodes.append(
                NetworkNode(
                    id=node_id,
                    name=facility.name,
                    kind="HOSPITAL" if facility.type == "HOSPITAL" else "BLOOD_BANK",
                    city=facility.city,
                    simulated=facility.is_simulated,
                    is_self=facility.id == self_id,
                )
            )
        known = {n.id for n in nodes}
        out_edges = [
            NetworkEdge(
                source=src,
                target=dst,
                requests=len(rs),
                open=sum(1 for r in rs if r.status in OPEN_STATUSES),
                units=sum(r.units for r in rs),
                last_status=rs[-1].status,
                last_at=rs[-1].updated_at,
            )
            for (src, dst), rs in sorted(edges.items())
            if src in known and dst in known
        ]
        nodes.sort(key=lambda n: (n.kind, not n.is_self, n.name))
        return NetworkGraph(
            generated_at=now, window_days=GRAPH_WINDOW_DAYS, nodes=nodes, edges=out_edges
        )
