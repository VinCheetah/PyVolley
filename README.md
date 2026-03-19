# 🏐 PyVolley - Statistiques Volleyball Français

Système complet de scraping, parsing et analyse des feuilles de match de volleyball français (FFVB).

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0+-red.svg)

## ✨ Fonctionnalités

- **🔍 Scraping** : Récupération automatique des feuilles de match depuis le site FFVB
- **📄 Parsing** : Extraction complète des données des PDFs (joueurs, scores, formations, timeouts, sanctions...)
- **💾 Base de données** : Stockage structuré multi-saisons avec SQLAlchemy
- **🔎 Recherche** : Interface web pour chercher joueurs, clubs, équipes, matchs
- **📊 Statistiques** : Visualisation des performances individuelles et collectives
- **🖥️ CLI** : Interface en ligne de commande complète
- **🌐 API REST** : Endpoints JSON pour intégration externe

## 📁 Structure du Projet

```text
PyVolley/
├── src/pyvolley/           # Code source principal
│   ├── core/               # Configuration, exceptions, modèles Pydantic
│   ├── scrapers/           # Scrapers pour récupérer les PDFs (FFVB)
│   ├── parsers/            # Parsers PDF avec benchmark (V2)
│   ├── database/           # Modèles ORM, repositories, services import
│   ├── api/                # API REST FastAPI
│   ├── web/                # Application web avec templates Jinja2
│   └── cli/                # Interface ligne de commande Typer
├── tests/                  # Tests unitaires et d'intégration
│   ├── conftest.py         # Fixtures pytest
│   ├── test_models.py      # Tests des modèles
│   ├── test_repositories.py # Tests des repositories
│   └── test_api.py         # Tests de l'API
├── feuilles_match/         # PDFs téléchargés
└── pyproject.toml          # Configuration du projet
```

## 🚀 Installation

```bash
# Cloner le projet
git clone <repo-url>
cd PyVolley

# Créer l'environnement virtuel
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# ou .venv\Scripts\activate  # Windows

# Installer les dépendances
pip install -e ".[dev]"

# Copier le fichier d'environnement
cp .env.example .env
```

## 💻 Utilisation

### CLI (Interface en ligne de commande)

```bash
# Initialiser la base de données
pyvolley init

# Pipeline principal FFVB (scrape → download → parse)
pyvolley import -e ABCCS -s 24/25

# Suivre l'état du pipeline
pyvolley status -s 24/25

# Relancer une étape ciblée
pyvolley import --only download -e ABCCS -s 24/25
pyvolley import --only parse --force -s 24/25

# Parser un PDF ou un dossier (hors base)
pyvolley parse data/pdfs/ --limit 10 --output matchs.json

# Nettoyer les PDFs
pyvolley cleanup pdfs --dry-run

# Explorer les données disponibles côté FFVB
pyvolley list entities
pyvolley list poules ABCCS --saison 24/25
pyvolley list matches ABCCS --saison 24/25 --limit 20

# Lancer le serveur web
pyvolley serve --host 0.0.0.0 --port 8000 --reload

# Aide complète
pyvolley --help
```

### Gestion de la base de données

```bash
# Afficher le statut de la base de données
pyvolley db status

# Créer une nouvelle migration (après modification des modèles)
pyvolley db migrate "Description des changements"

# Appliquer les migrations en attente
pyvolley db upgrade

# Revenir à la migration précédente
pyvolley db downgrade

# Afficher l'historique des migrations
pyvolley db history

# Réinitialiser la base de données (⚠️ ATTENTION: supprime les données!)
pyvolley db reset --force

# Explorer les tables
pyvolley db explore tables
pyvolley db explore matchs --saison 24/25 --limit 20

# Rapports détaillés
pyvolley report joueur "Dupont"
pyvolley report club "PARIS VOLLEY"
```

### Configuration PostgreSQL (Production)

Pour utiliser PostgreSQL au lieu de SQLite, créez un fichier `.env` :

```bash
cp .env.example .env
```

Puis configurez les variables PostgreSQL :

```env
PYVOLLEY_POSTGRES_HOST=localhost
PYVOLLEY_POSTGRES_PORT=5432
PYVOLLEY_POSTGRES_USER=pyvolley
PYVOLLEY_POSTGRES_PASSWORD=votre_mot_de_passe
PYVOLLEY_POSTGRES_DB=pyvolley
```

### Application Web

```bash
# Lancer l'application
pyvolley serve

# Ouvrir dans le navigateur
# http://127.0.0.1:8000
```

### API REST

```bash
# Lancer l'API
uvicorn pyvolley.api.app:app --reload

# Endpoints disponibles :
# GET  /api/health          - Santé de l'API
# GET  /api/search?q=       - Recherche globale
# GET  /api/joueurs         - Liste des joueurs
# GET  /api/joueurs/{id}    - Détail d'un joueur
# GET  /api/equipes         - Liste des équipes
# GET  /api/equipes/{id}    - Détail d'une équipe
# GET  /api/clubs           - Liste des clubs
# GET  /api/matchs          - Liste des matchs
# GET  /api/matchs/{id}     - Détail d'un match
# GET  /api/stats           - Statistiques globales

# Documentation Swagger
# http://127.0.0.1:8000/api/docs
```

### Utilisation en Python

```python
from pyvolley.parsers import ParserFactory
from pyvolley.database import get_db, init_db, JoueurRepository

# Parser un PDF
factory = ParserFactory()
parser = factory.get_parser("v2")
result = parser.parse("feuille_match.pdf")

if result.success:
    match = result.data
    print(f"Match: {match.equipe_a.nom} vs {match.equipe_b.nom}")
    print(f"Score: {match.score_final}")

# Rechercher dans la base de données
init_db()
with get_db() as session:
    repo = JoueurRepository(session)
    joueurs = repo.search_by_name("Dupont")
    for j in joueurs:
        print(f"{j.nom} {j.prenom} - {j.licence}")
```

## 🧪 Tests

```bash
# Lancer tous les tests
pytest

# Avec couverture
pytest --cov=pyvolley --cov-report=html

# Tests spécifiques
pytest tests/test_models.py -v
pytest tests/test_api.py -v
```

## 📊 Données extraites

Le parser V2 extrait les informations suivantes d'une feuille de match :

| Catégorie | Données |
| --------- | ------- |
| **Match** | Code, date, heure, lieu, salle, journée |
| **Compétition** | Ligue, catégorie, genre, nom |
| **Équipes** | Nom, club, joueurs (numéro, nom, prénom, licence) |
| **Résultat** | Vainqueur, score final, durée |
| **Sets** | Numéro, scores, heures début/fin, formations |
| **Événements** | Timeouts, sanctions, remarques |
| **Arbitres** | Nom, prénom, grade |

## 🛠️ Technologies

- **Python 3.11+** - Langage principal
- **FastAPI** - Framework API REST
- **SQLAlchemy 2.0** - ORM base de données
- **Pydantic v2** - Validation des données
- **PyMuPDF** - Parsing des PDFs
- **Jinja2** - Templates HTML
- **Typer** - Interface CLI
- **Rich** - Affichage console

## 📝 Licence

MIT License - Voir [LICENSE](LICENSE)
