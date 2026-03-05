"""
Données géographiques pour le filtre de localisation.

Mapping ville → département pour les lieux de matchs connus,
permettant le filtrage géographique via la carte de France.
"""

from typing import List, Set

# ─── Mapping ville → code département ──────────────────────────────
# Ce mapping couvre les villes connues dans la base de données.
# Il peut être enrichi au fil du temps avec de nouvelles données.

CITY_TO_DEPT: dict[str, str] = {
    # Département 01 - Ain
    "BOURG EN BRESSE": "01",
    "AMBERIEU EN BUGEY": "01",
    "MEXIMIEUX": "01",
    "ST ETIENNE DU BOIS": "01",
    "VAL REVERMONT": "01",

    # Département 03 - Allier
    "MOULINS": "03",
    "VICHY": "03",
    "MONTLUCON": "03",

    # Département 07 - Ardèche
    "CHARNAS": "07",
    "AUBENAS": "07",
    "ST-MARCEL D'ARDECHE": "07",
    "GUILHERAND-GRANGES": "07",
    "PRIVAS": "07",
    "ANNONAY": "07",

    # Département 15 - Cantal
    "AURILLAC": "15",

    # Département 26 - Drôme
    "VALENCE": "26",
    "ROMANS SUR ISERE": "26",
    "MONTELIMAR": "26",
    "PEYRINS": "26",
    "MARGES": "26",
    "LA MOTTE DE GALAURE": "26",
    "CREST": "26",
    "DIE": "26",

    # Département 38 - Isère
    "GRENOBLE": "38",
    "VIF": "38",
    "ST-JEAN DE MOIRANS": "38",
    "SEYSSINS": "38",
    "SAINT-EGREVE": "38",
    "ECHIROLLES": "38",
    "FONTAINE": "38",
    "VIENNE": "38",
    "MEYLAN": "38",
    "PONT DE CHERUY": "38",
    "LA TOUR DU PIN": "38",
    "BOURGOIN JALLIEU": "38",
    "CLAIX": "38",
    "APPRIEU": "38",
    "SAINT MARTIN D'HERES": "38",
    "SAINT-MARTIN D'HERES": "38",
    "VOIRON": "38",
    "VILLEFONTAINE": "38",
    "SASSENAGE": "38",
    "SAINT-ISMIER": "38",

    # Département 42 - Loire
    "SAINT-ETIENNE": "42",
    "MONTBRISON": "42",
    "FIRMINY": "42",
    "VILLARS": "42",
    "SAINT-CHAMOND": "42",
    "LA FOUILLOUSE": "42",
    "POUILLY SOUS CHARLIEU": "42",
    "ROANNE": "42",
    "SAINT-GALMIER": "42",
    "SAINT NIZIER SOUS CHARLIEU": "42",
    "SAINT-CYPRIEN": "42",
    "ANDREZIEUX-BOUTHEON": "42",
    "RIVE DE GIER": "42",
    "SAINT-JUST-SAINT-RAMBERT": "42",

    # Département 43 - Haute-Loire
    "LE PUY EN VELAY": "43",
    "BRIOUDE": "43",
    "YSSINGEAUX": "43",

    # Département 63 - Puy-de-Dôme
    "CLERMONT FERRAND": "63",
    "CLERMONT-FERRAND": "63",
    "CHAMALIERES": "63",
    "CEBAZAT": "63",
    "ISSOIRE": "63",
    "THIERS": "63",
    "RIOM": "63",

    # Département 69 - Rhône
    "LYON": "69",
    "VILLEFRANCHE SUR SAONE": "69",
    "BRON": "69",
    "MEYZIEU": "69",
    "FRANCHEVILLE": "69",
    "CALUIRE": "69",
    "RILLIEUX LA PAPE": "69",
    "SAINTE FOY LES LYON": "69",
    "VILLEURBANNE": "69",
    "DARDILLY": "69",
    "DECINES": "69",
    "OULLINS": "69",
    "VAULX EN VELIN": "69",
    "VENISSIEUX": "69",
    "TARARE": "69",
    "GIVORS": "69",
    "SAINT-PRIEST": "69",

    # Département 73 - Savoie
    "CHAMBERY": "73",
    "DRUMETTAZ-CLARAFOND": "73",
    "AIX LES BAINS": "73",
    "ALBERTVILLE": "73",
    "SAINT-JEAN-DE-MAURIENNE": "73",

    # Département 74 - Haute-Savoie
    "ANNECY": "74",
    "ANNEMASSE": "74",
    "CRAN GEVRIER": "74",
    "THONON LES BAINS": "74",
    "CLUSES": "74",
    "SALLANCHES": "74",
    "RUMILLY": "74",

    # ── Autres régions (villes principales) ────────────────────
    # Île-de-France (75, 77, 78, 91, 92, 93, 94, 95)
    "PARIS": "75",
    "BOULOGNE BILLANCOURT": "92",
    "LEVALLOIS PERRET": "92",
    "NANTERRE": "92",
    "CRETEIL": "94",
    "CHARENTON LE PONT": "94",
    "MONTREUIL": "93",
    "SAINT DENIS": "93",
    "VERSAILLES": "78",

    # Hauts-de-France (02, 59, 60, 62, 80)
    "LILLE": "59",
    "TOURCOING": "59",
    "ROUBAIX": "59",
    "AMIENS": "80",
    "CALAIS": "62",
    "ARRAS": "62",
    "LAON": "02",
    "BEAUVAIS": "60",
    "COMPIEGNE": "60",

    # Grand Est (08, 10, 51, 52, 54, 55, 57, 67, 68, 88)
    "STRASBOURG": "67",
    "MULHOUSE": "68",
    "COLMAR": "68",
    "METZ": "57",
    "NANCY": "54",
    "REIMS": "51",
    "TROYES": "10",
    "EPINAL": "88",
    "CHARLEVILLE MEZIERES": "08",

    # Normandie (14, 27, 50, 61, 76)
    "ROUEN": "76",
    "LE HAVRE": "76",
    "CAEN": "14",
    "CHERBOURG": "50",
    "EVREUX": "27",
    "ALENCON": "61",

    # Bretagne (22, 29, 35, 56)
    "RENNES": "35",
    "BREST": "29",
    "QUIMPER": "29",
    "LORIENT": "56",
    "VANNES": "56",
    "SAINT BRIEUC": "22",

    # Pays de la Loire (44, 49, 53, 72, 85)
    "NANTES": "44",
    "ANGERS": "49",
    "LE MANS": "72",
    "LAVAL": "53",
    "LA ROCHE SUR YON": "85",
    "SAINT NAZAIRE": "44",

    # Centre-Val de Loire (18, 28, 36, 37, 41, 45)
    "ORLEANS": "45",
    "TOURS": "37",
    "BOURGES": "18",
    "CHARTRES": "28",
    "BLOIS": "41",
    "CHATEAUROUX": "36",

    # Bourgogne-Franche-Comté (21, 25, 39, 58, 70, 71, 89, 90)
    "DIJON": "21",
    "BESANCON": "25",
    "AUXERRE": "89",
    "NEVERS": "58",
    "CHALON SUR SAONE": "71",
    "MACON": "71",
    "BELFORT": "90",
    "LONS LE SAUNIER": "39",
    "VESOUL": "70",

    # Nouvelle-Aquitaine (16, 17, 19, 23, 24, 33, 40, 47, 64, 79, 86, 87)
    "BORDEAUX": "33",
    "LIMOGES": "87",
    "POITIERS": "86",
    "PAU": "64",
    "BAYONNE": "64",
    "BIARRITZ": "64",
    "LA ROCHELLE": "17",
    "ANGOULEME": "16",
    "AGEN": "47",
    "MONT DE MARSAN": "40",
    "PERIGUEUX": "24",
    "NIORT": "79",
    "BRIVE LA GAILLARDE": "19",
    "GUERET": "23",

    # Occitanie (09, 11, 12, 30, 31, 32, 34, 46, 48, 65, 66, 81, 82)
    "TOULOUSE": "31",
    "MONTPELLIER": "34",
    "NIMES": "30",
    "PERPIGNAN": "66",
    "BEZIERS": "34",
    "NARBONNE": "11",
    "CARCASSONNE": "11",
    "TARBES": "65",
    "ALBI": "81",
    "RODEZ": "12",
    "CAHORS": "46",
    "AUCH": "32",
    "MONTAUBAN": "82",
    "MENDE": "48",
    "FOIX": "09",

    # PACA (04, 05, 06, 13, 83, 84)
    "MARSEILLE": "13",
    "NICE": "06",
    "TOULON": "83",
    "AIX EN PROVENCE": "13",
    "AVIGNON": "84",
    "CANNES": "06",
    "ANTIBES": "06",
    "FREJUS": "83",
    "GAP": "05",
    "DIGNE LES BAINS": "04",

    # Corse (2A, 2B)
    "AJACCIO": "2A",
    "BASTIA": "2B",
}

# Index inversé : département → set de villes
_DEPT_TO_CITIES: dict[str, set[str]] = {}
for _city, _dept in CITY_TO_DEPT.items():
    _DEPT_TO_CITIES.setdefault(_dept, set()).add(_city)


# ─── Mapping code entité FFVB → départements ──────────────────────
# Les codes d'entité suivent le pattern :
#   - PT + abréviation région + numéro département  (comité départemental)
#   - LI + abréviation région                        (ligue régionale)
#   - A*                                              (nationale, pas de département spécifique)
#
# Mapping ligue → départements de la région correspondante

LIGUE_TO_DEPTS: dict[str, List[str]] = {
    # Auvergne-Rhône-Alpes
    "LIRA": ["01", "03", "07", "15", "26", "38", "42", "43", "63", "69", "73", "74"],
    # Bourgogne-Franche-Comté
    "LIBOUR": ["21", "25", "39", "58", "70", "71", "89", "90"],
    # Bretagne
    "LIBR": ["22", "29", "35", "56"],
    # Centre-Val de Loire
    "LICE": ["18", "28", "36", "37", "41", "45"],
    # Corse
    "LICO": ["2A", "2B"],
    # Grand Est (Alsace + Lorraine anciens)
    "LIAL": ["67", "68"],
    "LILO": ["54", "55", "57", "88"],
    "LIGE": ["08", "10", "51", "52", "54", "55", "57", "67", "68", "88"],
    # Hauts-de-France (Flandres + Picardie anciens)
    "LIFL": ["59", "62"],
    "LIPI": ["02", "60", "80"],
    "LIHDF": ["02", "59", "60", "62", "80"],
    # Île-de-France
    "LIIDF": ["75", "77", "78", "91", "92", "93", "94", "95"],
    # Normandie (Basse-Normandie + Haute-Normandie anciens)
    "LILBNV": ["14", "50", "61"],
    "LILH": ["27", "76"],
    "LINO": ["14", "27", "50", "61", "76"],
    # Nouvelle-Aquitaine (Aquitaine + Poitou-Charentes anciens)
    "LIAQ": ["24", "33", "40", "47", "64"],
    "LIPO": ["16", "17", "79", "86"],
    "LINA": ["16", "17", "19", "23", "24", "33", "40", "47", "64", "79", "86", "87"],
    # Occitanie (Languedoc-Roussillon + Midi-Pyrénées anciens)
    "LILR": ["11", "30", "34", "48", "66"],
    "LIMP": ["09", "12", "31", "32", "46", "65", "81", "82"],
    "LIOCC": ["09", "11", "12", "30", "31", "32", "34", "46", "48", "65", "66", "81", "82"],
    # Pays de la Loire
    "LIPL": ["44", "49", "53", "72", "85"],
    # PACA (Côte d'Azur + Provence anciens)
    "LICA": ["06", "83"],
    "LIPR": ["04", "05", "13", "84"],
    "LIPACA": ["04", "05", "06", "13", "83", "84"],
    # Guadeloupe, Guyane, Martinique, Mayotte, Réunion (overseas)
    "LIGU": [],
    "LIGY": [],
    "LIMART": [],
    "LIMY": [],
    "LIRE": [],
}

# Comité départemental : code entité → numéro de département
# Pattern: "PT" + abréviation région + numéro département
# On extrait automatiquement le numéro de département du code

import re as _re

def _extract_dept_from_entite_code(code: str) -> str | None:
    """Extrait le numéro de département d'un code entité comité (PT...).
    
    Les codes suivent le pattern PT + abrév région + numéro département :
      PTRA38  → 38  (Rhône-Alpes, Isère)
      PTIDF75 → 75  (Île-de-France, Paris)
      PTAQ33  → 33  (Aquitaine, Gironde)
      PTAL67  → 67  (Alsace, Bas-Rhin)
      PTLB14  → 14  (Basse-Normandie, Calvados)
    """
    if not code or not code.startswith("PT"):
        return None
    # Match trailing digits (1-3 digits) at end of code
    m = _re.search(r'(\d{1,3})$', code)
    if m:
        return m.group(1).zfill(2) if len(m.group(1)) < 2 else m.group(1)
    return None


def get_departments_for_entite(code: str) -> List[str]:
    """Retourne les départements associés à un code entité FFVB.
    
    - Pour un comité départemental (PT...) : retourne le département correspondant.
    - Pour une ligue régionale (LI...) : retourne tous les départements de la région.
    - Pour une entité nationale (A...) : retourne une liste vide.
    
    Args:
        code: Code entité FFVB (ex: "PTRA38", "LIRA", "ABCCS")
    
    Returns:
        Liste de codes département (ex: ["38"]) ou liste vide.
    """
    if not code:
        return []
    
    code = code.upper().strip()
    
    # Comité départemental
    if code.startswith("PT"):
        dept = _extract_dept_from_entite_code(code)
        if dept:
            return [dept]
        return []
    
    # Ligue régionale
    if code.startswith("LI"):
        return LIGUE_TO_DEPTS.get(code, [])
    
    # Nationale ou autre
    return []


def extract_entite_code_from_path(source_pdf: str) -> str | None:
    """Extrait le code entité FFVB depuis le chemin d'un fichier PDF.
    
    Le chemin suit la convention : .../saison/ENTITE_CODE/poule/fichier.pdf
    Exemples :
        "data/pdfs/2024-2025/PTRA38/1RMA/PTRA38_1RMA001.pdf" → "PTRA38"
        "data/pdfs/2025-2026/LIRA/EMA/LIRA_EMA001.pdf"       → "LIRA"
        "2024-2025/ABCCS/EMA/ABCCS_EMA001.pdf"                → "ABCCS"
    
    Peut aussi extraire depuis le nom de fichier (entite_code_matchcode.pdf).
    """
    if not source_pdf:
        return None
    
    # Normaliser les séparateurs
    path = source_pdf.replace("\\", "/")
    parts = path.split("/")
    
    # Chercher dans le chemin : après une saison (YYYY-YYYY), le dossier suivant est l'entité
    for i, part in enumerate(parts):
        if _re.match(r'^\d{4}-\d{4}$', part) and i + 1 < len(parts):
            candidate = parts[i + 1]
            if candidate and not candidate.endswith('.pdf'):
                return candidate
    
    # Fallback : extraire du nom de fichier (ENTITE_CODE_matchcode.pdf)
    filename = parts[-1] if parts else source_pdf
    if filename.endswith('.pdf'):
        filename = filename[:-4]
    m = _re.match(r'^([A-Z]+\d*)_', filename)
    if m:
        return m.group(1)
    
    return None


def get_cities_for_departments(dept_codes: List[str]) -> List[str]:
    """Retourne les noms de ville associés à une liste de codes département."""
    cities: Set[str] = set()
    for code in dept_codes:
        cities.update(_DEPT_TO_CITIES.get(code, set()))
    return list(cities)


def get_department_for_city(city: str) -> str | None:
    """Retourne le code département pour une ville, ou None."""
    return CITY_TO_DEPT.get(city.upper().strip())
