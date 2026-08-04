"""ISO country -> international dialling code, for the account-region field.

Haier's account API wants a bare dialling code (``66``, ``351``) as its ``zoneInfo``, and fails
the least helpful way possible: an account that exists but was registered under a different region
comes back as ``retCode 30032``, *"Account is not registered"*. There is no endpoint that
enumerates regions, so a curated list plus free text is the best that can be done — but a list turns
an unbounded guessing game into a pick, and the Home Assistant instance already knows its own
country.

The list is not exhaustive and does not need to be: the selector allows a custom value, so an
unlisted
code can still be typed. Codes are shared where reality shares them (``+1`` US/Canada, ``+7``
Russia/Kazakhstan) — that is correct, not a bug.
"""
from __future__ import annotations

# ISO 3166-1 alpha-2 -> (display name, international dialling code)
COUNTRY_DIAL_CODES: dict[str, tuple[str, str]] = {
    "AL": ("Albania", "355"),
    "DZ": ("Algeria", "213"),
    "AR": ("Argentina", "54"),
    "AM": ("Armenia", "374"),
    "AU": ("Australia", "61"),
    "AT": ("Austria", "43"),
    "AZ": ("Azerbaijan", "994"),
    "BH": ("Bahrain", "973"),
    "BD": ("Bangladesh", "880"),
    "BY": ("Belarus", "375"),
    "BE": ("Belgium", "32"),
    "BO": ("Bolivia", "591"),
    "BA": ("Bosnia and Herzegovina", "387"),
    "BR": ("Brazil", "55"),
    "BN": ("Brunei", "673"),
    "BG": ("Bulgaria", "359"),
    "KH": ("Cambodia", "855"),
    "CA": ("Canada", "1"),
    "CL": ("Chile", "56"),
    "CN": ("China", "86"),
    "CO": ("Colombia", "57"),
    "CR": ("Costa Rica", "506"),
    "HR": ("Croatia", "385"),
    "CY": ("Cyprus", "357"),
    "CZ": ("Czechia", "420"),
    "DK": ("Denmark", "45"),
    "EC": ("Ecuador", "593"),
    "EG": ("Egypt", "20"),
    "EE": ("Estonia", "372"),
    "FI": ("Finland", "358"),
    "FR": ("France", "33"),
    "GE": ("Georgia", "995"),
    "DE": ("Germany", "49"),
    "GR": ("Greece", "30"),
    "GT": ("Guatemala", "502"),
    "HK": ("Hong Kong", "852"),
    "HU": ("Hungary", "36"),
    "IS": ("Iceland", "354"),
    "IN": ("India", "91"),
    "ID": ("Indonesia", "62"),
    "IR": ("Iran", "98"),
    "IQ": ("Iraq", "964"),
    "IE": ("Ireland", "353"),
    "IL": ("Israel", "972"),
    "IT": ("Italy", "39"),
    "JP": ("Japan", "81"),
    "JO": ("Jordan", "962"),
    "KZ": ("Kazakhstan", "7"),
    "KE": ("Kenya", "254"),
    "KW": ("Kuwait", "965"),
    "LA": ("Laos", "856"),
    "LV": ("Latvia", "371"),
    "LB": ("Lebanon", "961"),
    "LT": ("Lithuania", "370"),
    "LU": ("Luxembourg", "352"),
    "MY": ("Malaysia", "60"),
    "MT": ("Malta", "356"),
    "MX": ("Mexico", "52"),
    "MD": ("Moldova", "373"),
    "MN": ("Mongolia", "976"),
    "MA": ("Morocco", "212"),
    "MM": ("Myanmar", "95"),
    "NP": ("Nepal", "977"),
    "NL": ("Netherlands", "31"),
    "NZ": ("New Zealand", "64"),
    "NG": ("Nigeria", "234"),
    "MK": ("North Macedonia", "389"),
    "NO": ("Norway", "47"),
    "OM": ("Oman", "968"),
    "PK": ("Pakistan", "92"),
    "PA": ("Panama", "507"),
    "PY": ("Paraguay", "595"),
    "PE": ("Peru", "51"),
    "PH": ("Philippines", "63"),
    "PL": ("Poland", "48"),
    "PT": ("Portugal", "351"),
    "QA": ("Qatar", "974"),
    "RO": ("Romania", "40"),
    "RU": ("Russia", "7"),
    "SA": ("Saudi Arabia", "966"),
    "RS": ("Serbia", "381"),
    "SG": ("Singapore", "65"),
    "SK": ("Slovakia", "421"),
    "SI": ("Slovenia", "386"),
    "ZA": ("South Africa", "27"),
    "KR": ("South Korea", "82"),
    "ES": ("Spain", "34"),
    "LK": ("Sri Lanka", "94"),
    "SE": ("Sweden", "46"),
    "CH": ("Switzerland", "41"),
    "TW": ("Taiwan", "886"),
    "TH": ("Thailand", "66"),
    "TN": ("Tunisia", "216"),
    "TR": ("Turkey", "90"),
    "UA": ("Ukraine", "380"),
    "AE": ("United Arab Emirates", "971"),
    "GB": ("United Kingdom", "44"),
    "US": ("United States", "1"),
    "UY": ("Uruguay", "598"),
    "UZ": ("Uzbekistan", "998"),
    "VE": ("Venezuela", "58"),
    "VN": ("Vietnam", "84"),
}


def country_options() -> list[dict[str, str]]:
    """Selector options: ``{"value": "66", "label": "Thailand (+66)"}``, sorted by country name.

    Several countries legitimately share a code, so the value is not unique across options — that is
    fine for a selector, and picking either "Russia (+7)" or "Kazakhstan (+7)" sends the same thing.
    """
    return [
        {"value": code, "label": f"{name} (+{code})"}
        for name, code in sorted(COUNTRY_DIAL_CODES.values())
    ]


def default_dial_code(country: str | None) -> str | None:
    """The dialling code for an ISO country, for pre-selecting from ``hass.config.country``.

    Returns ``None`` rather than a guess when the country is unknown or unset: an empty field the
    user must fill in deliberately beats a plausible-looking wrong default, which is what the
    previous hardcoded ``66`` was for everyone outside Thailand.
    """
    if not country:
        return None
    entry = COUNTRY_DIAL_CODES.get(country.upper())
    return entry[1] if entry else None
