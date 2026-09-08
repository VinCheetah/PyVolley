"""
Module CLI — Interface en ligne de commande pour PyVolley.

Structure et commandes principales :
- Pipeline : import, status, parse, cleanup, serve, simulate
- Consultation : list (entities, poules, matches)
- Base de données : db (status, migrate, upgrade, downgrade, history, vacuum, explore)
- Statistiques : compute (all, rollups, players, palmares), stats
- Audits : roles (diffuse, inspect, audit, evaluate-match), audit (plausibility)
- Rapports : report (joueur, club, equipe, match, arbitre, competition, saison)
- Outils dev : dev (compare, profile-parser, layout-editor)
"""

from pyvolley.cli.main import app, main

__all__ = ["app", "main"]
