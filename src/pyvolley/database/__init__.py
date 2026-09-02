"""
Module Database - Persistance des données.

Contient :
- Modèles SQLAlchemy (ORM)
- Configuration de la connexion
- Migrations (Alembic)
- Repositories pour l'accès aux données
- Services d'import
"""

from .connection import (
    get_db, 
    init_db, 
    drop_db,
    reset_db,
    get_engine,
    DatabaseSession
)
from .models import (
    Base,
    ClubDB,
    ClubAliasDB,
    EquipeDB,
    JoueurDB,
    MatchDB,
    SetDB,
    FormationDB,
    ChangementDB,
    TimeoutDB,
    ArbitreDB,
    ArbitreMatchDB,
    SanctionDB,
    SaisonDB,
    CompetitionDB,
    PouleDB,
    EntiteFFVBDB,
    ParticipationMatchDB,
    OfficielMatchDB,
    JoueurMatchStatsDB,
    JoueurSaisonStatsDB,
    JoueurCarriereStatsDB,
    EquipeSaisonStatsDB,
)
from .repositories import (
    JoueurRepository,
    ClubRepository,
    EquipeRepository,
    MatchRepository,
    SaisonRepository,
    CompetitionRepository,
    PouleRepository,
    EntiteFFVBRepository,
    JoueurMatchStatsRepository,
    JoueurSaisonStatsRepository,
    JoueurCarriereStatsRepository,
    EquipeSaisonStatsRepository,
)
from .import_service import MatchImportService, BulkImportService
from .export_import_service import ExportImportService
from .player_stats_service import JoueurMatchStatsService
from .rollup_service import RollupStatsService
from .migrations import (
    create_migration,
    upgrade,
    downgrade,
    get_current_revision,
    get_database_status,
    ensure_database_ready,
)

__all__ = [
    # Connection
    "get_db",
    "init_db",
    "drop_db",
    "reset_db",
    "get_engine",
    "DatabaseSession",
    "Base",
    # Models
    "ClubDB",
    "ClubAliasDB",
    "EquipeDB",
    "JoueurDB",
    "MatchDB",
    "SetDB",
    "FormationDB",
    "ChangementDB",
    "TimeoutDB",
    "ArbitreDB",
    "ArbitreMatchDB",
    "SanctionDB",
    "SaisonDB",
    "CompetitionDB",
    "PouleDB",
    "EntiteFFVBDB",
    "ParticipationMatchDB",
    "OfficielMatchDB",
    "JoueurMatchStatsDB",
    "JoueurSaisonStatsDB",
    "JoueurCarriereStatsDB",
    "EquipeSaisonStatsDB",
    # Repositories
    "JoueurRepository",
    "ClubRepository",
    "EquipeRepository",
    "MatchRepository",
    "SaisonRepository",
    "CompetitionRepository",
    "PouleRepository",
    "EntiteFFVBRepository",
    "JoueurMatchStatsRepository",
    "JoueurSaisonStatsRepository",
    "JoueurCarriereStatsRepository",
    "EquipeSaisonStatsRepository",
    # Services
    "MatchImportService",
    "BulkImportService",
    "ExportImportService",
    "JoueurMatchStatsService",
    "RollupStatsService",
    # Migrations
    "create_migration",
    "upgrade",
    "downgrade",
    "get_current_revision",
    "get_database_status",
    "ensure_database_ready",
]

