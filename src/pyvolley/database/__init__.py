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
    EquipeDB,
    JoueurDB,
    MatchDB,
    SetDB,
    ArbitreDB,
    ArbitreMatchDB,
    SanctionDB,
    SaisonDB,
    CompetitionDB,
    ParticipationMatchDB,
)
from .repositories import (
    JoueurRepository,
    ClubRepository,
    EquipeRepository,
    MatchRepository,
)
from .import_service import MatchImportService, BulkImportService
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
    "EquipeDB",
    "JoueurDB",
    "MatchDB",
    "SetDB",
    "ArbitreDB",
    "ArbitreMatchDB",
    "SanctionDB",
    "SaisonDB",
    "CompetitionDB",
    "ParticipationMatchDB",
    # Repositories
    "JoueurRepository",
    "ClubRepository",
    "EquipeRepository",
    "MatchRepository",
    # Services
    "MatchImportService",
    "BulkImportService",
    # Migrations
    "create_migration",
    "upgrade",
    "downgrade",
    "get_current_revision",
    "get_database_status",
    "ensure_database_ready",
]
