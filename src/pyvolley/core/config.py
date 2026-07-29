"""
Configuration de l'application PyVolley.

Utilise pydantic-settings pour charger la configuration depuis :
1. Variables d'environnement
2. Fichier .env
3. Valeurs par défaut
"""

from pathlib import Path
from typing import Literal, Optional
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    """Configuration principale de PyVolley."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="PYVOLLEY_",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Environnement
    env: Literal["development", "production", "test"] = "development"
    debug: bool = False
    
    # Chemins - Calculés dynamiquement dans __init__ pour garantir le bon chemin
    base_dir: Path = Path(__file__).parent.parent.parent.parent
    data_dir: Path = Path("")
    pdfs_dir: Path = Path("")
    logs_dir: Path = Path("")
    
    # Base de données - Sera mise à jour dans __init__
    # PostgreSQL: postgresql://user:password@localhost:5432/pyvolley
    # SQLite: sqlite:///absolute/path/to/data/pyvolley.db
    database_url: str = ""
    
    # PostgreSQL spécifique (optionnel, pour construction dynamique de l'URL)
    postgres_host: Optional[str] = None
    postgres_port: int = 5432
    postgres_user: Optional[str] = None
    postgres_password: Optional[str] = None
    postgres_db: str = "pyvolley"
    
    # FFVB Scraping
    ffvb_base_url: str = "https://www.ffvbbeach.org/ffvbapp/resu/"
    ffvb_request_delay: float = 0.1  # Délai entre requêtes (secondes)
    ffvb_timeout: int = 30

    # Gestion des PDFs
    keep_pdfs: bool = True  # Conserver les PDFs après parsing (défaut: oui)
    
    # Serveur Web
    web_host: str = "127.0.0.1"
    web_port: int = 8000
    secret_key: str = "dev-secret-key-change-in-production"
    
    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/pyvolley.log"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Calculer les chemins absolus
        self.base_dir = Path(__file__).parent.parent.parent.parent.resolve()
        self.data_dir = self.base_dir / "data"
        self.pdfs_dir = self.data_dir / "pdfs"
        self.logs_dir = self.base_dir / "logs"
        
        # Créer les dossiers nécessaires
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.pdfs_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Construire l'URL de base de données (si non fournie explicitement)
        if not self.database_url:
            if self.postgres_host and self.postgres_user:
                # PostgreSQL
                self.database_url = self._build_postgres_url()
            else:
                # SQLite avec chemin absolu
                db_path = self.data_dir / "pyvolley.db"
                self.database_url = f"sqlite:///{db_path}"
    
    def _build_postgres_url(self) -> str:
        """Construit l'URL PostgreSQL depuis les variables individuelles."""
        password_part = f":{self.postgres_password}" if self.postgres_password else ""
        return f"postgresql://{self.postgres_user}{password_part}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
    
    @property
    def is_development(self) -> bool:
        return self.env == "development"
    
    @property
    def is_production(self) -> bool:
        return self.env == "production"
    
    @property
    def is_test(self) -> bool:
        return self.env == "test"
    
    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")
    
    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


@lru_cache
def get_settings() -> Settings:
    """Retourne l'instance singleton des settings."""
    return Settings()


# Instance globale
settings = get_settings()
