"""
Team tag lookup — converts full VCT team names to short display tags.
CUSTOM_TAGS loaded from config.json["team_tags"] at call time; overrides TEAM_TAGS.
"""

import state

TEAM_TAGS: dict[str, str] = {
    "Paper Rex": "PRX",
    "Sentinels": "SEN",
    "DRX": "DRX",
    "T1": "T1",
    "Gen.G": "GEN",
    "Global Esports": "GE",
    "Talon Esports": "TLN",
    "Team Secret": "TS",
    "Rex Regum Qeon": "RRQ",
    "Nongshim RedForce": "NS",
    "DetonatioN FocusMe": "DFM",
    "ZETA DIVISION": "ZETA",
    "BBL Esports": "BBL",
    "Karmine Corp": "KC",
    "Team Vitality": "VIT",
    "Fnatic": "FNC",
    "Team Heretics": "TH",
    "Giants Gaming": "GIA",
    "FUT Esports": "FUT",
    "KOI": "KOI",
    "Natus Vincere": "NAVI",
    "Gentle Mates": "M8",
    "Team Liquid": "TL",
    "Apeks": "APK",
    "LOUD": "LOUD",
    "FURIA": "FUR",
    "Leviatán": "LEV",
    "KRÜ Esports": "KRU",
    "MIBR": "MIBR",
    "NRG": "NRG",
    "100 Thieves": "100T",
    "Cloud9": "C9",
    "Evil Geniuses": "EG",
    "G2 Esports": "G2",
    "Trace Esports": "TE",
    "EDward Gaming": "EDG",
    "FunPlus Phoenix": "FPX",
    "Bilibili Gaming": "BLG",
    "All Gamers": "AG",
    "JD Gaming": "JDG",
    "Wolves Esports": "WOL",
    "Nova Esports": "NOVA",
    "TyLoo": "TYL",
    "Dragon Ranger Gaming": "DRG",
    "Full Sense": "FS",
    # Academy / affiliate teams — distinct tags so they don't match main roster favourites
    "T1 Academy": "T1A",
    "Gen.G Global Academy": "GNA",
    "Gen.G Academy": "GNA",
    "DRX Academy": "DRA",
    "Team Liquid Academy": "TLA",
    "Sentinels Academy": "SNA",
    "Cubert Academy": "CUA",
    "MIBR Academy": "MIA",
    "Leviatán Academy": "LEA",
    "LEVIATÁN Academy": "LEA",
    "FURIA Academy": "FUA",
    "ZETA DIVISION Academy": "ZDA",
    "Team Secret Academy": "TSA",
    "Talon Academy": "TLNA",
    "TALON Academy": "TLNA",
    "RRQ Academy": "RRQA",
    "Global Esports Academy": "GEA",
    "DetonatioN FocusMe Academy": "DFMA",
    "DFM Academy": "DFMA",
    "KOI Fénix": "KOIF",
    "KOI Fénix Academy": "KOIF",
    "KCORP Blue Stars": "KCBS",
    "Karmine Corp Academy": "KCA",
    "2Game Academy": "2GA",
    "OXEN": "OXEN",
    "UCAM Esports Club": "UCAM",
    "CGN Esports": "CGN",
    "Fenerbahçe Esports": "FEN",
    "BBL PCIFIC": "BBLP",
    "EDward Gaming Young": "EDGY",
    "All Gamers Young": "AGY",
}


def get_tag(name: str) -> str:
    """Return the display tag for a team name.

    Lookup order: custom tags (from config) → hardcoded TEAM_TAGS → fallback (first
    word, uppercased, max 4 chars).
    """
    if not name:
        return "???"
    custom = state.cfg.get("team_tags", {})
    if name in custom:
        return custom[name]
    if name in TEAM_TAGS:
        return TEAM_TAGS[name]
    return name.split()[0].upper()[:4]
