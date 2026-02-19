"""
Constantes partagées pour le parser de feuilles de match FFVB.
"""

import re
from pyvolley.core.models import RoleArbitre


# ── Mois français ──
MOIS_MAP = {
    'janvier': 1, 'février': 2, 'mars': 3, 'avril': 4,
    'mai': 5, 'juin': 6, 'juillet': 7, 'août': 8,
    'septembre': 9, 'octobre': 10, 'novembre': 11, 'décembre': 12,
}

JOURS_SEMAINE = (
    'Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche',
)

# ── Arbitres ──
ROLE_ARBITRE_MAP: dict[str, RoleArbitre] = {
    '1er': RoleArbitre.PREMIER,
    '2ème': RoleArbitre.SECOND,
    '2éme': RoleArbitre.SECOND,
    'Marqueur': RoleArbitre.MARQUEUR,
    'MarqueurAZAR': RoleArbitre.MARQUEUR,  # pdfplumber merge artifact
    'Marq.Ass.': RoleArbitre.MARQUEUR_ASSISTANT,
    'R.Salle': RoleArbitre.RESPONSABLE_SALLE,
}

# ── Sets ──
ROWS_PER_SET = 10

# ── Formats de score ──
COMPETITION_FORMAT_21_KEYWORDS = frozenset({
    'BRASSAGE', 'BRASSAGES', 'COMPETFUN', 'COMPET FUN',
    'COMPETMOUV', 'COMPET MOUV', 'LOISIR', 'LOISIRS',
})

COMPETITION_FORMAT_15_KEYWORDS = frozenset({
    '4X4', '3X3', '2X2',
})

# ── Regex : joueurs ──
# Caractères autorisés dans les noms (accents, tirets, apostrophes, ?, etc.)
NAME_CHARS = r'A-Za-zÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆàâäéèêëïîôùûüçñœæ\.\-\',\( \)\?'

JOUEUR_PATTERN = re.compile(
    r'^(\d{1,2})\s+'
    rf'([{NAME_CHARS}]+?)\s+'
    r'(\d{1,8})$'
)
JOUEUR_GLUED_PATTERN = re.compile(
    r'^(\d{1,2})\s+'
    rf'([{NAME_CHARS}]+?)'
    r'(\d{4,8})$'
)
JOUEUR_NO_LICENCE_PATTERN = re.compile(
    r'^(\d{1,2})\s+'
    rf'([{NAME_CHARS}]{{3,}})$'
)
