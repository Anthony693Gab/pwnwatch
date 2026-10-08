"""Minimal country lookup: ISO-3166 alpha-2 <-> English name, plus location parsing."""

from __future__ import annotations

import re

NAMES: dict[str, str] = {
    "AE": "United Arab Emirates", "AM": "Armenia", "AR": "Argentina", "AT": "Austria",
    "AU": "Australia", "AZ": "Azerbaijan", "BA": "Bosnia and Herzegovina", "BD": "Bangladesh",
    "BE": "Belgium", "BG": "Bulgaria", "BH": "Bahrain", "BR": "Brazil", "BY": "Belarus",
    "CA": "Canada", "CH": "Switzerland", "CL": "Chile", "CN": "China", "CO": "Colombia",
    "CY": "Cyprus", "CZ": "Czechia", "DE": "Germany", "DK": "Denmark", "DZ": "Algeria",
    "EE": "Estonia", "EG": "Egypt", "ES": "Spain", "FI": "Finland", "FR": "France",
    "GB": "United Kingdom", "GE": "Georgia", "GR": "Greece", "HK": "Hong Kong", "HR": "Croatia",
    "HU": "Hungary", "ID": "Indonesia", "IE": "Ireland", "IL": "Israel", "IN": "India",
    "IR": "Iran", "IS": "Iceland", "IT": "Italy", "JO": "Jordan", "JP": "Japan", "KE": "Kenya",
    "KR": "South Korea", "KZ": "Kazakhstan", "LB": "Lebanon", "LK": "Sri Lanka", "LT": "Lithuania",
    "LU": "Luxembourg", "LV": "Latvia", "MA": "Morocco", "MD": "Moldova", "ME": "Montenegro",
    "MK": "North Macedonia", "MT": "Malta", "MX": "Mexico", "MY": "Malaysia", "NG": "Nigeria",
    "NL": "Netherlands", "NO": "Norway", "NP": "Nepal", "NZ": "New Zealand", "OM": "Oman",
    "PE": "Peru", "PH": "Philippines", "PK": "Pakistan", "PL": "Poland", "PT": "Portugal",
    "QA": "Qatar", "RO": "Romania", "RS": "Serbia", "RU": "Russia", "SA": "Saudi Arabia",
    "SE": "Sweden", "SG": "Singapore", "SI": "Slovenia", "SK": "Slovakia", "TH": "Thailand",
    "TN": "Tunisia", "TR": "Turkey", "TW": "Taiwan", "UA": "Ukraine", "US": "United States",
    "UZ": "Uzbekistan", "VN": "Vietnam", "ZA": "South Africa",
}

ALIASES: dict[str, str] = {
    "usa": "US", "u.s.": "US", "u.s.a.": "US", "united states of america": "US", "america": "US",
    "uk": "GB", "england": "GB", "scotland": "GB", "wales": "GB", "great britain": "GB",
    "korea": "KR", "republic of korea": "KR", "czech republic": "CZ", "uae": "AE",
    "türkiye": "TR", "turkiye": "TR", "russian federation": "RU", "the netherlands": "NL",
    "holland": "NL", "viet nam": "VN", "macedonia": "MK",
    # Cities that often appear alone in CTFtime locations
    "bucharest": "RO", "bucuresti": "RO", "cluj-napoca": "RO", "cluj": "RO", "iasi": "RO",
    "timisoara": "RO", "las vegas": "US", "new york": "US", "san francisco": "US",
    "tokyo": "JP", "seoul": "KR", "taipei": "TW", "beijing": "CN", "shanghai": "CN",
    "paris": "FR", "berlin": "DE", "munich": "DE", "hamburg": "DE", "leipzig": "DE",
    "london": "GB", "amsterdam": "NL", "madrid": "ES", "rome": "IT", "warsaw": "PL",
    "prague": "CZ", "vienna": "AT", "budapest": "HU", "sofia": "BG", "chisinau": "MD",
    "kyiv": "UA", "riyadh": "SA", "dubai": "AE", "abu dhabi": "AE", "doha": "QA",
    "singapore": "SG", "sydney": "AU", "melbourne": "AU", "toronto": "CA", "montreal": "CA",
}

_BY_NAME = {v.lower(): k for k, v in NAMES.items()}


def name_of(code: str) -> str:
    return NAMES.get(code.upper(), code.upper()) if code else ""


def code_from_location(location: str | None) -> str:
    """Best-effort ISO code from strings like 'Bucharest, Romania' or 'Las Vegas, NV, USA'."""
    if not location:
        return ""
    loc = location.strip().lower()
    if loc in ("", "online", "virtual", "remote"):
        return ""
    parts = [p.strip(" .") for p in re.split(r"[,/|()\-–]", loc) if p.strip(" .")]
    for p in reversed(parts):
        if p in _BY_NAME:
            return _BY_NAME[p]
        if p in ALIASES:
            return ALIASES[p]
    for name, code in list(_BY_NAME.items()) + list(ALIASES.items()):
        if re.search(rf"\b{re.escape(name)}\b", loc):
            return code
    return ""
