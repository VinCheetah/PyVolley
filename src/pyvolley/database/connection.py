"""
Configuration de la connexion à la base de données.

Supporte PostgreSQL (production) et SQLite (développement).
Utilise SQLAlchemy 2.0 avec le style moderne.
"""

import logging
import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import create_engine, event, text, inspect as sa_inspect
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from pyvolley.core.config import settings


logger = logging.getLogger(__name__)

# Variable globale pour l'engine (initialisée à la demande)
_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def get_engine() -> Engine:
    """
    Récupère ou crée l'engine SQLAlchemy.
    
    Supporte:
    - PostgreSQL: postgresql://user:pass@host:port/db
    - SQLite: sqlite:///path/to/db.sqlite ou sqlite:///:memory:
    """
    global _engine
    
    if _engine is not None:
        return _engine
    
    database_url = settings.database_url
    
    # Configuration selon le type de base de données
    if database_url.startswith("sqlite"):
        # SQLite - mode développement
        connect_args = {"check_same_thread": False}
        
        # Pour les tests en mémoire
        if ":memory:" in database_url:
            _engine = create_engine(
                database_url,
                echo=settings.debug,
                connect_args=connect_args,
                poolclass=StaticPool,  # Nécessaire pour SQLite in-memory
            )
        else:
            _engine = create_engine(
                database_url,
                echo=settings.debug,
                connect_args=connect_args,
            )
        
        # Activer les foreign keys, le mode WAL et optimiser SQLite
        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.execute("PRAGMA cache_size=-64000")  # 64MB memory cache
            cursor.close()

    
    elif database_url.startswith("postgresql"):
        # PostgreSQL - mode production
        _engine = create_engine(
            database_url,
            echo=settings.debug,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,  # Vérifie les connexions avant utilisation
        )
    
    else:
        # Fallback générique
        _engine = create_engine(
            database_url,
            echo=settings.debug,
        )
    
    logger.info(f"Database engine created: {database_url.split('@')[-1] if '@' in database_url else database_url}")
    return _engine


def get_session_factory() -> sessionmaker:
    """Récupère ou crée la factory de sessions."""
    global _SessionLocal
    
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    
    return _SessionLocal


class DatabaseSession:
    """Gestionnaire de session de base de données."""
    
    def __init__(self):
        SessionFactory = get_session_factory()
        self.session: Session = SessionFactory()
    
    def __enter__(self) -> Session:
        return self.session
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.session.rollback()
        self.session.close()


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """
    Contexte pour obtenir une session de base de données.
    
    Usage:
        with get_db() as db:
            db.query(...)
    """
    SessionFactory = get_session_factory()
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """
    Initialise la base de données en créant toutes les tables.

    À appeler au démarrage de l'application.
    Pour les changements de schéma en production, utiliser Alembic.

    Après un ``create_all`` initial (base vide), la révision Alembic est
    automatiquement stampée à ``head`` pour éviter que ``db upgrade`` tente de
    recréer des tables déjà existantes.
    """
    from pyvolley.database.models import Base

    engine = get_engine()

    current_rev = None
    table_names: set[str] = set()
    try:
        from alembic.runtime.migration import MigrationContext

        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            current_rev = ctx.get_current_revision()
            table_names = set(sa_inspect(conn).get_table_names())
    except Exception as e:
        logger.warning("Could not inspect Alembic/database state: %s", e)

    if current_rev:
        try:
            from pyvolley.database.migrations import upgrade

            upgrade("head")
            logger.info("Database migrations checked/applied to head")
        except Exception as e:
            logger.warning("Could not apply pending migrations: %s", e)
        return

    if not table_names:
        try:
            from pyvolley.database.migrations import upgrade

            upgrade("head")
            logger.info("Database initialized from Alembic migrations")
            return
        except Exception as e:
            logger.warning("Migration-based initialization failed, fallback create_all: %s", e)
            Base.metadata.create_all(bind=engine)
            logger.info("Database tables created successfully (bootstrap fallback)")

    else:
        logger.info("Existing non-versioned schema detected; create_all skipped")

    try:
        from pyvolley.database.migrations import stamp

        stamp("head")
        logger.info("Alembic stamped at head")
    except Exception as e:
        logger.warning("Could not stamp Alembic revision after init_db: %s", e)


def drop_db() -> None:
    """
    Supprime toutes les tables de la base de données.
    
    ⚠️ Attention: Cette opération est destructive !
    Utilisez uniquement en développement.
    """
    from pyvolley.database.models import Base
    
    engine = get_engine()
    Base.metadata.drop_all(bind=engine)
    logger.warning("All database tables dropped")


def reset_db() -> None:
    """
    Réinitialise complètement la base de données.
    
    ⚠️ Supprime toutes les données et invalide les caches de parsing !
    """
    drop_db()
    init_db()
    _clear_parse_caches()
    logger.info("Database reset completed (parse caches cleared)")


def reset_db_with_migrations() -> None:
    """
    Réinitialise complètement la base de données y compris l'historique des migrations.
    
    ⚠️ Attention: Cette opération est destructive!
    - Supprime le fichier de base de données SQLite
    - Réinitialise l'historique des migrations Alembic
    - Crée une nouvelle base de données
    - Invalide les caches de parsing
    
    Utilisez uniquement en développement après des changements de schéma majeurs.
    """
    database_url = settings.database_url
    
    # 1. Supprimer la base de données SQLite si elle existe
    if database_url.startswith("sqlite"):
        # Extraire le chemin du fichier
        db_path = database_url.replace("sqlite:///", "")
        if db_path and db_path != ":memory:":
            try:
                if os.path.exists(db_path):
                    os.remove(db_path)
                    logger.warning(f"Deleted database file: {db_path}")
            except Exception as e:
                logger.error(f"Failed to delete database file: {e}")
    
    # 2. Réinitialiser l'engine et la SessionFactory
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None
    logger.info("Database engine and session factory reset")
    
    # 3. Réinitialiser l'historique des migrations Alembic
    try:
        alembic_dir = Path(__file__).parent.parent.parent.parent / "alembic"
        versions_dir = alembic_dir / "versions"
        
        if versions_dir.exists():
            # Supprimer les fichiers __pycache__
            pycache_dir = versions_dir / "__pycache__"
            if pycache_dir.exists():
                shutil.rmtree(pycache_dir)
                logger.info("Cleared alembic versions __pycache__")
        
        logger.info("Alembic migrations directory preserved for manual cleanup if needed")
    except Exception as e:
        logger.error(f"Error handling alembic directory: {e}")
    
    # 4. Initialiser la nouvelle base de données
    init_db()
    _clear_parse_caches()
    logger.warning("Database fully reset - new empty database created (parse caches cleared)")


def _clear_parse_caches() -> None:
    """
    Supprime tous les fichiers de cache de parsing (.pyvolley_parse_cache.json)
    trouvés dans le dossier data/.

    Appelé automatiquement lors d'un reset de la base de données pour qu'un
    ``parse --save-db`` subséquent re-parse et ré-importe tout.
    """
    data_dir = settings.data_dir
    if not data_dir.exists():
        return
    count = 0
    for cache_file in data_dir.rglob(".pyvolley_parse_cache.json"):
        try:
            cache_file.unlink()
            count += 1
        except Exception as e:
            logger.warning(f"Impossible de supprimer le cache {cache_file}: {e}")
    if count:
        logger.info(f"Supprimé {count} fichier(s) de cache de parsing")


def check_connection() -> bool:
    """
    Vérifie que la connexion à la base de données fonctionne.
    
    Returns:
        True si la connexion est OK, False sinon
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False


def vacuum_db() -> dict:
    """
    Exécute un VACUUM et optimise les pages de la base de données SQLite.
    
    Returns:
        Dictionnaire avec les tailles avant/après et l'espace récupéré.
    """
    database_url = settings.database_url
    if not database_url.startswith("sqlite"):
        return {"status": "skipped", "reason": "Not a SQLite database"}

    db_path = database_url.replace("sqlite:///", "")
    if not db_path or db_path == ":memory:" or not os.path.exists(db_path):
        return {"status": "skipped", "reason": "Database file not found"}


    size_before = os.path.getsize(db_path)
    logger.info(f"Starting VACUUM on {db_path} (Current size: {size_before / (1024*1024):.2f} MB)...")

    engine = get_engine()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("VACUUM"))
        conn.execute(text("ANALYZE"))

    size_after = os.path.getsize(db_path)
    freed_mb = (size_before - size_after) / (1024 * 1024)
    logger.info(
        f"VACUUM completed! New size: {size_after / (1024*1024):.2f} MB "
        f"(Freed: {freed_mb:.2f} MB)"
    )

    return {
        "status": "success",
        "size_before_mb": round(size_before / (1024 * 1024), 2),
        "size_after_mb": round(size_after / (1024 * 1024), 2),
        "freed_mb": round(freed_mb, 2),
    }

