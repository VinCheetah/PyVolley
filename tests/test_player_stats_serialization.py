"""
Tests de non-régression pour la sérialisation des statistiques joueurs et l'absence de noms 'null'.
"""

from pyvolley.database.models import JoueurDB, JoueurMatchStatsDB, MatchDB
from pyvolley.database.player_stats_service import JoueurMatchStatsService


def test_joueur_match_stats_as_dict_includes_name():
    """Vérifie que JoueurMatchStatsDB.as_dict() inclut nom, prenom et licence."""
    joueur = JoueurDB(id=42, nom="DUPONT", prenom="Jean", licence="1234567")
    stat = JoueurMatchStatsDB(
        joueur_id=42,
        match_id=1,
        equipe_id=10,
        numero="10",
        side="A",
        points_joues=50,
        points_gagnes=20,
    )
    stat.joueur = joueur

    data = stat.as_dict()
    assert data["nom"] == "DUPONT"
    assert data["prenom"] == "Jean"
    assert data["licence"] == "1234567"
    assert data["numero"] == "10"
    assert data["points_joues"] == 50
