"""Hand-curated big events that CTFtime doesn't list (conferences, national
competitions) so you hear about them months ahead.

Dates were checked against the organisers' own announcements in October 2026
(except where a note says otherwise).
Entries without dates are shown in the "Watchlist · dates TBA" section until
you (or a pull request) fill them in. Add your own in ~/.config/pwnwatch/config.toml.
"""

from __future__ import annotations

CURATED: list[dict] = [
    {
        "name": "Bucharest Cybersecurity Conference 2026",
        "start": "2026-10-20", "end": "2026-10-22",
        "kind": "conference", "mode": "onsite", "country": "RO",
        "location": "HALO Events Center, Bucharest",
        "url": "https://bcc.dnsc.ro",
        "note": "Organised by DNSC. bcc.dnsc.ro is the only official domain; lookalike sites exist.",
    },
    {
        "name": "DefCamp 2026 · D-CTF & Hacking Village",
        "start": "2026-11-19", "end": "2026-11-20",
        "kind": "conference", "mode": "onsite", "country": "RO",
        "location": "Palace of the Parliament, Bucharest",
        "url": "https://def.camp",
        "note": "Largest security conference in CEE. Technical workshops Nov 16–18; "
                "10+ competitions in the Hacking Village (hosted on CyberEDU).",
    },
    {
        "name": "DEF CON 35",
        "start": "2027-08-05", "end": "2027-08-08",
        "kind": "conference", "mode": "onsite", "country": "US",
        "location": "Las Vegas Convention Center, Las Vegas",
        "url": "https://defcon.org",
        "note": "Home of the DEF CON CTF finals. Pre-registration usually opens in spring.",
    },
    {
        "name": "Bitdefender Cybersecurity Grand Prix 2026 (CTF)",
        "start": "2026-11-12", "end": "2026-11-12",
        "kind": "ctf", "mode": "onsite", "country": "RO",
        "location": "Bitdefender offices, Bucharest",
        "url": "https://www.bitdefender.com/ctf",
        "note": "On-site CTF run by Bitdefender; the 2025 edition's prize was a trip to "
                "DEF CON in Las Vegas. Date from the community — confirm it and the "
                "registration deadline on Bitdefender's page.",
    },
    # ---- recurring, next dates not announced yet ----
    {
        "name": "Olimpiada de Securitate Cibernetică (OSC) 2027",
        "kind": "ctf", "mode": "hybrid", "country": "RO",
        "location": "County centres, national phase in Bucharest",
        "url": "https://dnsc.ro",
        "note": "Romania's cybersecurity olympiad for students (Ministry of Education + DNSC). "
                "In 2026: registration on CyberEDU until 10 April, county phase 24 April "
                "(6h, Jeopardy CTF), national phase 16–19 May in Bucharest with Attack-Defense. "
                "Top students go on to the national team (ECSC).",
    },
    {
        "name": "DEF CON CTF Qualifier 2027",
        "kind": "ctf", "mode": "online", "country": "US",
        "url": "https://defcon.org",
        "note": "Online qualifier for the DEF CON CTF finals; usually held in May.",
    },
    {
        "name": "UNbreakable Romania",
        "kind": "ctf", "mode": "online", "country": "RO",
        "url": "https://unbreakable.ro",
        "note": "National CTF for high-school and university students (CyberEDU).",
    },
    {
        "name": "Romanian Cyber Security Challenge (RoCSC)",
        "kind": "ctf", "mode": "hybrid", "country": "RO",
        "url": "https://www.rocsc.ro",
        "note": "National selection for Romania's team at the European Cybersecurity Challenge.",
    },
    {
        "name": "European Cybersecurity Challenge (ECSC) 2027",
        "kind": "ctf", "mode": "onsite", "country": "",
        "url": "https://ecsc.eu",
        "note": "ENISA's European championship for young talent; national teams only.",
    },
]
