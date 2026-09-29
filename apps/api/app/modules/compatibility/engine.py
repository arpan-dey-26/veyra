"""Phase 8: ABO/Rh compatibility reference (pure, deterministic, informational only).

This is the ONE place VEYRA encodes compatibility rules; the web app renders what the API
returns and never re-implements them. The rules are a simplified, conservative textbook
reference for a student prototype. They are NOT clinical decision support: they do not
consider antibodies, crossmatch results, patient history, institutional policy or urgency,
and they never approve, allocate or dispatch blood. Human confirmation stays mandatory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.modules.bags.domain import Component

COMPATIBILITY_DISCLAIMER: Final = (
    "Informational prototype reference only; final transfusion decisions require authorized "
    "clinical confirmation."
)
COMPATIBILITY_LABEL: Final = "Prototype ABO/Rh compatibility reference (simplified, not clinical)"

BLOOD_GROUPS: Final[tuple[str, ...]] = ("O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+")
COMPONENTS: Final[tuple[Component, ...]] = (
    Component.WHOLE_BLOOD,
    Component.PRBC,
    Component.PLATELETS,
    Component.FFP,
    Component.CRYO,
)


@dataclass(frozen=True)
class Rule:
    code: str  # "red_cell" | "whole_blood" | "plasma" | "platelet"
    summary: str
    rh_matters: bool


RULES: Final[dict[Component, Rule]] = {
    Component.WHOLE_BLOOD: Rule(
        "whole_blood",
        "Whole blood contains red cells and plasma: ABO-identical only; an Rh-negative unit "
        "may go to an Rh-positive recipient, not the reverse.",
        rh_matters=True,
    ),
    Component.PRBC: Rule(
        "red_cell",
        "Red cells: the donor's A/B antigens must also be present in the recipient "
        "(O is the universal red-cell donor, AB+ the universal recipient); Rh-negative "
        "recipients receive Rh-negative units.",
        rh_matters=True,
    ),
    Component.PLATELETS: Rule(
        "platelet",
        "Platelets (conservative reference): plasma-compatible ABO (the recipient's A/B "
        "antigens present in the donor) and Rh-negative recipients receive Rh-negative units. "
        "Institutions often relax this; follow local policy.",
        rh_matters=True,
    ),
    Component.FFP: Rule(
        "plasma",
        "Plasma: the recipient's A/B antigens must also be present in the donor (AB is the "
        "universal plasma donor, O the universal plasma recipient); Rh is not considered.",
        rh_matters=False,
    ),
    Component.CRYO: Rule(
        "plasma",
        "Cryoprecipitate (conservative reference): plasma-compatible ABO as for plasma; Rh "
        "is not considered. Many institutions accept any ABO group; follow local policy.",
        rh_matters=False,
    ),
}


def _split(group: str) -> tuple[frozenset[str], bool]:
    """'AB-' → ({'A', 'B'}, False). Raises ValueError for anything outside the 8 groups."""
    if group not in BLOOD_GROUPS:
        raise ValueError(f"unsupported blood group {group!r}")
    abo, rh = group[:-1], group[-1] == "+"
    return frozenset() if abo == "O" else frozenset(abo), rh


@dataclass(frozen=True)
class Verdict:
    compatible: bool
    reason: str


def check(donor: str, recipient: str, component: Component) -> Verdict:
    d_abo, d_rh = _split(donor)
    r_abo, r_rh = _split(recipient)
    rule = RULES[component]
    if rule.code == "whole_blood":
        abo_ok = d_abo == r_abo
        abo_text = "ABO groups are identical" if abo_ok else "whole blood needs identical ABO"
    elif rule.code == "red_cell":
        abo_ok = d_abo <= r_abo
        abo_text = (
            "the recipient carries every donor A/B antigen"
            if abo_ok
            else "the donor red cells carry an A/B antigen the recipient lacks"
        )
    else:  # plasma / platelet: plasma compatibility
        abo_ok = r_abo <= d_abo
        abo_text = (
            "the donor plasma has no antibody against the recipient's A/B antigens"
            if abo_ok
            else "the donor plasma carries antibodies against the recipient's A/B antigens"
        )
    rh_ok = (not rule.rh_matters) or r_rh or not d_rh
    if not abo_ok:
        return Verdict(False, f"Not compatible: {abo_text}.")
    if not rh_ok:
        return Verdict(False, "Not compatible: an Rh-positive unit for an Rh-negative recipient.")
    rh_text = "" if not rule.rh_matters else " and the Rh rule is met"
    return Verdict(True, f"Compatible: {abo_text}{rh_text}.")


def compatible_donors(recipient: str, component: Component) -> list[str]:
    return [d for d in BLOOD_GROUPS if check(d, recipient, component).compatible]


def compatible_recipients(donor: str, component: Component) -> list[str]:
    return [r for r in BLOOD_GROUPS if check(donor, r, component).compatible]


LABELS: Final[dict[Component, str]] = {
    Component.WHOLE_BLOOD: "Whole Blood",
    Component.PRBC: "Packed Red Blood Cells (PRBC)",
    Component.PLATELETS: "Platelets",
    Component.FFP: "Fresh Frozen Plasma (FFP)",
    Component.CRYO: "Cryoprecipitate",
}


def component_label(component: Component) -> str:
    return LABELS[component]
