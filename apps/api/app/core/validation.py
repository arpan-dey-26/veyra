"""Input normalisation + validation shared by all modules.

Error messages never echo the submitted value (they may contain personal data).
"""

from __future__ import annotations

import re
import unicodedata

BLOOD_GROUPS: tuple[str, ...] = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")

INDIAN_STATES_AND_UTS: tuple[str, ...] = (
    "Andaman and Nicobar Islands",
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chandigarh",
    "Chhattisgarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jammu and Kashmir",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Ladakh",
    "Lakshadweep",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Puducherry",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
)

_EMAIL = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
_PIN = re.compile(r"^[1-9][0-9]{5}$")
_NAME = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ .'\-])*$")
_CITY = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ .'\-()])*$")
_MOBILE_SEPARATORS = re.compile(r"[\s\-()]")
_WS = re.compile(r"\s+")

PASSWORD_MIN = 10
PASSWORD_MAX = 128

# Tiny blocklist of the most common passwords that satisfy the length rule.
_COMMON_PASSWORDS = frozenset(
    {
        "1234567890",
        "0123456789",
        "12345678910",
        "qwertyuiop",
        "password123",
        "password1234",
        "passwordpassword",
        "iloveyou123",
        "abcdefghij",
        "abcd123456",
        "1q2w3e4r5t",
        "qwerty12345",
        "welcome123",
        "admin12345",
        "letmein1234",
        "veyra12345",
        "bloodbank123",
    }
)


def clean_text(value: str) -> str:
    """NFC-normalise, collapse whitespace, strip, drop control characters."""
    value = unicodedata.normalize("NFC", value)
    value = "".join(
        " " if ch.isspace() else ch
        for ch in value
        if ch.isspace() or unicodedata.category(ch)[0] != "C"
    )
    return _WS.sub(" ", value).strip()


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        raise ValueError("Enter a valid email address")
    return email


def normalize_indian_mobile(value: str) -> str:
    """Accept common Indian formats and return E.164 (+91XXXXXXXXXX)."""
    digits = _MOBILE_SEPARATORS.sub("", value.strip())
    if digits.startswith("+91"):
        digits = digits[3:]
    elif len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not (len(digits) == 10 and digits.isdigit() and digits[0] in "6789"):
        raise ValueError("Enter a valid 10-digit Indian mobile number")
    return f"+91{digits}"


def validate_person_name(value: str) -> str:
    name = clean_text(value)
    letters = sum(ch.isalpha() for ch in name)
    if not (2 <= len(name) <= 120) or letters < 2 or not _NAME.match(name):
        raise ValueError("Enter your full name using letters, spaces, . ' or -")
    return name


def validate_city(value: str) -> str:
    city = clean_text(value)
    if not (2 <= len(city) <= 80) or not _CITY.match(city):
        raise ValueError("Enter a valid city name")
    return city


def validate_address(value: str) -> str:
    address = clean_text(value)
    if not (5 <= len(address) <= 255):
        raise ValueError("Address must be between 5 and 255 characters")
    return address


def validate_state(value: str) -> str:
    state = clean_text(value)
    for known in INDIAN_STATES_AND_UTS:
        if known.lower() == state.lower():
            return known
    raise ValueError("Select a valid Indian state or union territory")


def validate_pin_code(value: str) -> str:
    pin = value.strip().replace(" ", "")
    if not _PIN.match(pin):
        raise ValueError("Enter a valid 6-digit PIN code")
    return pin


def validate_blood_group(value: str) -> str:
    group = value.strip().upper().replace(" ", "").replace("\u2212", "-")  # unicode minus
    if group not in BLOOD_GROUPS:
        raise ValueError("Select a valid blood group")
    return group


def validate_new_password(password: str, *, email: str | None = None) -> str:
    if not (PASSWORD_MIN <= len(password) <= PASSWORD_MAX):
        raise ValueError(f"Password must be {PASSWORD_MIN}-{PASSWORD_MAX} characters")
    lowered = password.lower()
    if lowered in _COMMON_PASSWORDS or len(set(password)) < 4:
        raise ValueError("This password is too common or too simple")
    if email:
        local = email.split("@", 1)[0].lower()
        if len(local) >= 4 and local in lowered:
            raise ValueError("Password must not contain your email name")
    return password
