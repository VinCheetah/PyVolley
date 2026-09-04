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
        "data/pdfs/2024-2025/PTRA38/1RMA/1RMA001.pdf" → "PTRA38"
        "data/pdfs/2025-2026/LIRA/EMA/EMA001.pdf"     → "LIRA"
        "2024-2025/ABCCS/EMA/EFA001.pdf"              → "ABCCS"
    
    Peut aussi extraire depuis le nom de fichier (anciens formats legacy).
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
    
    # Fallback : extraire du nom de fichier (format legacy ENTITE_CODE_matchcode.pdf)
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
    if not city:
        return None
    cleaned = city.upper().strip()
    # Direct match
    if cleaned in CITY_TO_DEPT:
        return CITY_TO_DEPT[cleaned]
    # Check if postal code is embedded in city string (e.g. "38600 FONTAINE")
    m = _re.search(r'\b(\d{5})\b', cleaned)
    if m:
        code = m.group(1)
        dept = extract_dept_from_postal_code(code)
        if dept:
            return dept
    # Try stripping postal code if present
    no_digits = _re.sub(r'^\d{5}\s*', '', cleaned).strip()
    if no_digits in CITY_TO_DEPT:
        return CITY_TO_DEPT[no_digits]
    return None


def extract_dept_from_postal_code(postal_code: str) -> str | None:
    """Extrait le code de département depuis un code postal français à 5 chiffres."""
    if not postal_code:
        return None
    code = postal_code.strip()
    if len(code) < 2:
        return None
    # DOM-TOM (97X)
    if code.startswith("97"):
        return code[:3] if len(code) >= 3 else None
    # Corse (20)
    if code.startswith("20"):
        try:
            num = int(code[:5])
            return "2A" if num < 20200 else "2B"
        except (ValueError, TypeError):
            return "2A"
    return code[:2]


def extract_dept_from_address_or_city(ville: str | None = None, adresse: str | None = None) -> str | None:
    """Extrait intelligemment le code département d'une ville ou adresse.
    
    Exemples:
        ville="38600 FONTAINE" -> "38"
        adresse="23 RUE DES ALPES, 69400 VILLEFRANCHE" -> "69"
        ville="GRENOBLE" -> "38"
    """
    for text in (ville, adresse):
        if not text:
            continue
        # Search for 5-digit postal code
        m = _re.search(r'\b(\d{5})\b', text)
        if m:
            dept = extract_dept_from_postal_code(m.group(1))
            if dept and (dept in DEPARTMENT_CENTROIDS or dept in _DEPT_TO_CITIES):
                return dept
    
    # Try city dictionary lookup
    if ville:
        dept = get_department_for_city(ville)
        if dept:
            return dept
    return None


# ─── Centroïdes des 101 départements français ──────────────────────
# Couverture complète de la France métropolitaine, de la Corse et des DROM.
DEPARTMENT_CENTROIDS: dict[str, tuple[float, float]] = {
    "01": (46.20, 5.23),   # Ain
    "02": (49.56, 3.62),   # Aisne
    "03": (46.35, 3.36),   # Allier
    "04": (44.09, 6.24),   # Alpes-de-Haute-Provence
    "05": (44.66, 6.33),   # Hautes-Alpes
    "06": (43.94, 7.18),   # Alpes-Maritimes
    "07": (44.75, 4.60),   # Ardèche
    "08": (49.61, 4.68),   # Ardennes
    "09": (42.94, 1.50),   # Ariège
    "10": (48.33, 4.17),   # Aube
    "11": (43.15, 2.40),   # Aude
    "12": (44.28, 2.68),   # Aveyron
    "13": (43.53, 5.08),   # Bouches-du-Rhône
    "14": (49.10, -0.36),  # Calvados
    "15": (45.05, 2.67),   # Cantal
    "16": (45.71, 0.16),   # Charente
    "17": (45.75, -0.63),  # Charente-Maritime
    "18": (47.08, 2.40),   # Cher
    "19": (45.35, 1.87),   # Corrèze
    "2A": (41.85, 8.95),   # Corse-du-Sud
    "2B": (42.45, 9.25),   # Haute-Corse
    "21": (47.42, 4.78),   # Côte-d'Or
    "22": (48.45, -2.85),  # Côtes-d'Armor
    "23": (46.03, 1.95),   # Creuse
    "24": (45.15, 0.72),   # Dordogne
    "25": (47.17, 6.35),   # Doubs
    "26": (44.70, 5.17),   # Drôme
    "27": (49.12, 1.15),   # Eure
    "28": (48.37, 1.40),   # Eure-et-Loir
    "29": (48.23, -4.10),  # Finistère
    "30": (44.02, 4.22),   # Gard
    "31": (43.40, 1.30),   # Haute-Garonne
    "32": (43.65, 0.58),   # Gers
    "33": (44.84, -0.58),  # Gironde
    "34": (43.61, 3.48),   # Hérault
    "35": (48.17, -1.67),  # Ille-et-Vilaine
    "36": (46.78, 1.60),   # Indre
    "37": (47.25, 0.70),   # Indre-et-Loire
    "38": (45.22, 5.55),   # Isère
    "39": (46.75, 5.70),   # Jura
    "40": (43.90, -0.80),  # Landes
    "41": (47.65, 1.33),   # Loir-et-Cher
    "42": (45.72, 4.17),   # Loire
    "43": (45.12, 3.88),   # Haute-Loire
    "44": (47.35, -1.68),  # Loire-Atlantique
    "45": (47.92, 2.18),   # Loiret
    "46": (44.62, 1.60),   # Lot
    "47": (44.37, 0.45),   # Lot-et-Garonne
    "48": (44.52, 3.50),   # Lozère
    "49": (47.45, -0.55),  # Maine-et-Loire
    "50": (49.10, -1.33),  # Manche
    "51": (49.00, 4.25),   # Marne
    "52": (48.12, 5.22),   # Haute-Marne
    "53": (48.18, -0.62),  # Mayenne
    "54": (48.70, 6.18),   # Meurthe-et-Moselle
    "55": (49.00, 5.38),   # Meuse
    "56": (47.88, -2.83),  # Morbihan
    "57": (49.05, 6.63),   # Moselle
    "58": (47.12, 3.50),   # Nièvre
    "59": (50.50, 3.20),   # Nord
    "60": (49.42, 2.42),   # Oise
    "61": (48.60, 0.15),   # Orne
    "62": (50.52, 2.37),   # Pas-de-Calais
    "63": (45.77, 3.08),   # Puy-de-Dôme
    "64": (43.32, -0.75),  # Pyrénées-Atlantiques
    "65": (43.05, 0.15),   # Hautes-Pyrénées
    "66": (42.60, 2.60),   # Pyrénées-Orientales
    "67": (48.68, 7.62),   # Bas-Rhin
    "68": (47.88, 7.30),   # Haut-Rhin
    "69": (45.76, 4.75),   # Rhône
    "70": (47.63, 6.08),   # Haute-Saône
    "71": (46.65, 4.60),   # Saône-et-Loire
    "72": (48.00, 0.20),   # Sarthe
    "73": (45.50, 6.50),   # Savoie
    "74": (46.00, 6.40),   # Haute-Savoie
    "75": (48.8566, 2.3522),# Paris
    "76": (49.65, 1.05),   # Seine-Maritime
    "77": (48.60, 2.90),   # Seine-et-Marne
    "78": (48.80, 1.90),   # Yvelines
    "79": (46.53, -0.33),  # Deux-Sèvres
    "80": (49.92, 2.30),   # Somme
    "81": (43.78, 2.22),   # Tarn
    "82": (44.08, 1.25),   # Tarn-et-Garonne
    "83": (43.43, 6.25),   # Var
    "84": (44.00, 5.08),   # Vaucluse
    "85": (46.67, -1.42),  # Vendée
    "86": (46.60, 0.45),   # Vienne
    "87": (45.85, 1.25),   # Haute-Vienne
    "88": (48.20, 6.35),   # Vosges
    "89": (47.85, 3.55),   # Yonne
    "90": (47.63, 6.95),   # Territoire de Belfort
    "91": (48.53, 2.25),   # Essonne
    "92": (48.83, 2.23),   # Hauts-de-Seine
    "93": (48.91, 2.45),   # Seine-Saint-Denis
    "94": (48.78, 2.47),   # Val-de-Marne
    "95": (49.07, 2.12),   # Val-d'Oise
    "971": (16.25, -61.55),# Guadeloupe
    "972": (14.65, -61.02),# Martinique
    "973": (3.93, -53.12), # Guyane
    "974": (-21.11, 55.53),# La Réunion
    "976": (-12.83, 45.16),# Mayotte
}

# ─── Coordonnées précises des communes de volley récurrentes ────────
CITY_COORDINATES: dict[str, tuple[float, float]] = {
    # Isère (38)
    "GRENOBLE": (45.1885, 5.7245),
    "FONTAINE": (45.1932, 5.6853),
    "ECHIROLLES": (45.1436, 5.7175),
    "SEYSSINS": (45.1585, 5.6800),
    "SAINT-EGREVE": (45.2319, 5.6833),
    "BOURGOIN JALLIEU": (45.5861, 5.2758),
    "VOIRON": (45.3644, 5.5906),
    "MEYLAN": (45.2094, 5.7806),
    "SAINT MARTIN D'HERES": (45.1681, 5.7681),
    "SAINT-MARTIN D'HERES": (45.1681, 5.7681),
    "VIF": (45.0558, 5.6706),
    "CLAIX": (45.1172, 5.6750),
    "SASSENAGE": (45.2078, 5.6631),
    "VIENNE": (45.5253, 4.8778),
    "VILLEFONTAINE": (45.6144, 5.1486),
    "SAINT-ISMIER": (45.2486, 5.8272),
    "LA TOUR DU PIN": (45.5658, 5.4464),
    "PONT DE CHERUY": (45.7503, 5.1747),
    "VARCES-ALLIERES-ET-RISSET": (45.0867, 5.6811),
    "ST-JEAN DE MOIRANS": (45.3406, 5.5806),

    # Rhône & Lyon métropole (69)
    "LYON": (45.7640, 4.8357),
    "VILLEURBANNE": (45.7667, 4.8800),
    "BRON": (45.7333, 4.9167),
    "CALUIRE": (45.7958, 4.8436),
    "CALUIRE ET CUIRE": (45.7958, 4.8436),
    "RILLIEUX LA PAPE": (45.8167, 4.9000),
    "RILLIEUX-LA-PAPE": (45.8167, 4.9000),
    "SAINTE FOY LES LYON": (45.7333, 4.8000),
    "VILLEFRANCHE SUR SAONE": (45.9897, 4.7197),
    "GLEIZE": (45.9928, 4.6989),
    "MONTANAY": (45.8817, 4.8622),
    "ARNAS": (46.0253, 4.7083),
    "MEYZIEU": (45.7667, 4.9833),
    "FRANCHEVILLE": (45.7333, 4.7667),
    "DARDILLY": (45.8083, 4.7500),
    "DECINES": (45.7667, 4.9500),
    "DECINES-CHARPIEU": (45.7667, 4.9500),
    "OULLINS": (45.7167, 4.8000),
    "VAULX EN VELIN": (45.7833, 4.9167),
    "VENISSIEUX": (45.7000, 4.8833),
    "SAINT-PRIEST": (45.6961, 4.9450),
    "GIVORS": (45.5833, 4.7667),
    "TARARE": (45.8964, 4.4336),

    # Ain (01)
    "BOURG EN BRESSE": (46.2056, 5.2289),
    "AMBERIEU EN BUGEY": (45.9583, 5.3583),
    "MEXIMIEUX": (45.9056, 5.1958),
    "VILLIEU LOYES MOLLON": (45.9222, 5.2222),

    # Drôme / Ardèche (26, 07)
    "VALENCE": (44.9333, 4.8917),
    "ROMANS SUR ISERE": (45.0458, 5.0519),
    "ROMANS SUR ISÈRE": (45.0458, 5.0519),
    "MONTELIMAR": (44.5583, 4.7508),
    "PEYRINS": (45.0917, 5.0500),
    "AUBENAS": (44.6206, 4.3900),
    "PRIVAS": (44.7353, 4.5986),
    "ANNONAY": (45.2406, 4.6706),
    "SAINT JUST D'ARDECHE": (44.3050, 4.6108),

    # Loire (42)
    "SAINT-ETIENNE": (45.4397, 4.3872),
    "SAINT-CHAMOND": (45.4744, 4.5136),
    "ROANNE": (46.0367, 4.0742),
    "MONTBRISON": (45.6083, 4.0650),
    "FIRMINY": (45.3883, 4.2867),

    # Savoie / Haute-Savoie (73, 74)
    "CHAMBERY": (45.5667, 5.9167),
    "AIX LES BAINS": (45.6886, 5.9153),
    "ALBERTVILLE": (45.6756, 6.3925),
    "ANNECY": (45.8992, 6.1294),
    "ANNEMASSE": (46.1958, 6.2364),
    "THONON LES BAINS": (46.3706, 6.4789),

    # Auvergne (63, 03, 15, 43)
    "CLERMONT-FERRAND": (45.7772, 3.0870),
    "CLERMONT FERRAND": (45.7772, 3.0870),
    "CHAMALIERES": (45.7758, 3.0672),
    "ISSOIRE": (45.5439, 3.2492),
    "VICHY": (46.1278, 3.4267),
    "MOULINS": (46.5658, 3.3333),
    "LE PUY EN VELAY": (45.0428, 3.8847),
    "AURILLAC": (44.9261, 2.4453),

    # Grandes villes nationales de volley
    "PARIS": (48.8566, 2.3522),
    "MARSEILLE": (43.2965, 5.3698),
    "TOULOUSE": (43.6047, 1.4442),
    "NICE": (43.7102, 7.2620),
    "NANTES": (47.2184, -1.5536),
    "MONTPELLIER": (43.6108, 3.8767),
    "STRASBOURG": (48.5734, 7.7521),
    "BORDEAUX": (44.8378, -0.5792),
    "LILLE": (50.6292, 3.0573),
    "RENNES": (48.1173, -1.6778),
    "REIMS": (49.2583, 4.0317),
    "TOULON": (43.1242, 5.9280),
    "DIJON": (47.3220, 5.0415),
    "ANGERS": (47.4784, -0.5632),
    "NIMES": (43.8367, 4.3601),
    "TOURS": (47.3941, 0.6848),
    "CANNES": (43.5528, 7.0174),
    "SETE": (43.4078, 3.6939),
    "NARBONNE": (43.1836, 3.0042),
    "CHAUMONT": (48.1128, 5.1389),
    "CAMBRAI": (50.1764, 3.2342),
    "TOURCOING": (50.7239, 3.1611),
    "LE PLESSIS-ROBINSON": (48.7817, 2.2619),
    "POITIERS": (46.5802, 0.3404),
    "SAINT-NAZAIRE": (47.2736, -2.2139),
    "AJACCIO": (41.9267, 8.7369),
}


def resolve_entity_coordinates(
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    ville: str | None = None,
    adresse: str | None = None,
    departement: str | None = None,
    entity_id: int = 1,
) -> tuple[float, float] | None:
    """Résout les coordonnées géographiques les plus précises possibles pour une entité.
    
    Ordre de priorité :
    1. Coordonnées exactes déjà enregistrées (latitude/longitude != None)
    2. Coordonnées de commune répertoriée (CITY_COORDINATES)
    3. Centroïde du département résolu (par departement, code postal ou ville) avec
       dispersion subtile déterministe pour éviter la superposition exacte.
    """
    # 1. Exact coordinates
    if latitude is not None and longitude is not None:
        try:
            lat_f, lng_f = float(latitude), float(longitude)
            if -90 <= lat_f <= 90 and -180 <= lng_f <= 180 and (lat_f != 0.0 or lng_f != 0.0):
                return lat_f, lng_f
        except (ValueError, TypeError):
            pass

    # 2. Known city exact coordinates
    for cand_city in (ville,):
        if not cand_city:
            continue
        cleaned = cand_city.upper().strip()
        if cleaned in CITY_COORDINATES:
            coords = CITY_COORDINATES[cleaned]
            # Add micro-offset per entity_id (max 200m)
            from math import sin, cos, radians
            angle = radians((entity_id * 47) % 360)
            radius = ((entity_id % 5) - 2) * 0.0008
            return coords[0] + sin(angle) * radius, coords[1] + cos(angle) * radius
        # Check without postal code
        no_digits = _re.sub(r'^\d{5}\s*', '', cleaned).strip()
        if no_digits in CITY_COORDINATES:
            coords = CITY_COORDINATES[no_digits]
            from math import sin, cos, radians
            angle = radians((entity_id * 47) % 360)
            radius = ((entity_id % 5) - 2) * 0.0008
            return coords[0] + sin(angle) * radius, coords[1] + cos(angle) * radius

    # 3. Department centroid
    dept = departement.strip().upper() if departement else None
    if not dept:
        dept = extract_dept_from_address_or_city(ville, adresse)
    if dept and len(dept) == 1 and dept.isdigit():
        dept = dept.zfill(2)

    if dept and dept in DEPARTMENT_CENTROIDS:
        centroid = DEPARTMENT_CENTROIDS[dept]
        from math import sin, cos, radians
        angle = radians((entity_id * 37) % 360)
        # 800m - 1.5km spread around centroid
        radius = 0.004 + ((entity_id % 7) * 0.002)
        return centroid[0] + sin(angle) * radius, centroid[1] + cos(angle) * radius

    return None
