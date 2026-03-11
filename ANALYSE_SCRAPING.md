# Analyse critique du système de scraping PyVolley

> Document généré suite à une exploration complète du code source, un crawling
> exhaustif du site FFVB (ffvbbeach.org), et des tests de couverture en direct.

---

## Table des matières

1. [Vue d'ensemble de l'architecture actuelle](#1-vue-densemble-de-larchitecture-actuelle)
2. [Analyse critique par composant](#2-analyse-critique-par-composant)
3. [Tests de couverture — résultats quantifiés](#3-tests-de-couverture--résultats-quantifiés)
4. [Sources de données FFVB découvertes](#4-sources-de-données-ffvb-découvertes)
5. [Problèmes critiques identifiés](#5-problèmes-critiques-identifiés)
6. [Architecture cible : approche en deux phases](#6-architecture-cible--approche-en-deux-phases)
7. [Plan d'action détaillé](#7-plan-daction-détaillé)
8. [Modifications de schéma proposées](#8-modifications-de-schéma-proposées)
9. [Estimations et priorités](#9-estimations-et-priorités)

---

## 1. Vue d'ensemble de l'architecture actuelle

### Pipeline actuel

```
planning_volley.php ──→ Entités (ligues/comités)
       │
       ▼
  Poule discovery ──→ Poules (4 stratégies)
       │
       ▼
  Calendar pages ──→ MatchInfo (code + PDF URL uniquement)
       │
       ▼
  PDF download ──→ feuille de match locale
       │
       ▼
  PDF parser ──→ Match Pydantic model (complet)
       │
       ▼
  Import service ──→ Base de données (SQLAlchemy)
       │
       ▼
  Score completion ──→ Complète les scores manquants depuis les calendriers
```

### Modules

| Module | Fichier | Rôle |
|--------|---------|------|
| `FFVBScraper` | `scrapers/ffvb/scraper.py` | Orchestrateur principal |
| `entities` | `scrapers/ffvb/entities.py` | Découverte des entités depuis `planning_volley.php` |
| `poules` | `scrapers/ffvb/poules.py` | Découverte des poules (4 stratégies) |
| `matches` | `scrapers/ffvb/matches.py` | Découverte des matchs depuis les calendriers |
| `download` | `scrapers/ffvb/download.py` | Téléchargement des PDFs avec fallback LNV |
| `patterns` | `scrapers/ffvb/patterns.py` | ~109 patterns de poules hardcodés |
| `utils` | `scrapers/ffvb/utils.py` | Construction d'URLs, détection genre/catégorie |
| `jeunes` | `scrapers/ffvb/jeunes.py` | Scraping Coupe de France Jeunes (ACJEUNES) |
| `score_scraper` | `scrapers/score_scraper.py` | Parsing séquentiel des cellules du calendrier HTML |
| `ScoreCompletionService` | `database/score_completion.py` | Synchronisation scores DB ↔ calendrier en ligne |
| `MatchImportService` | `database/import_service.py` | Import des données parsées en DB |
| `MatchSheetParser` | `parsers/parser.py` | Parsing PDF des feuilles de match |

---

## 2. Analyse critique par composant

### 2.1 `MatchInfo` (base.py) — **CRITIQUE : modèle appauvri**

```python
@dataclass
class MatchInfo:
    code: str               # Code du match (ex: PMAA001)
    competition_code: str   # Code de la compétition (ex: PMA)
    ligue_code: str         # Code de la ligue (ex: LIIDF)
    saison: str             # Saison (ex: 2024-2025)
    journee: Optional[str] = None
    pdf_url: Optional[str] = None
```

**Problème** : Ce dataclass ne contient que 6 champs. Il ne porte **aucune
information** sur les équipes, les scores, le lieu, les arbitres, les numéros
de club, la date ou l'heure. Toute la richesse des données disponibles en ligne
est perdue à cette étape.

**Conséquence** : L'identification des clubs et équipes repose **entièrement**
sur le parsing PDF, avec une correspondance approximative par nom via
l'algorithme de Levenshtein dans `MatchImportService`. Pas de code FFVB de
club, pas de numéro d'engagement.

### 2.2 Découverte des poules (poules.py) — **4 stratégies fragiles**

Les 4 stratégies actuelles :

1. **Home page** (`vbspo.php`) : Parse les options `<select>` de la page
   d'accueil FFVB. Dépend de la structure HTML.
2. **ffvb.org** : Construit une URL vers `ffvb.org/compet/` et parse les
   liens. Fragile (le site ffvb.org peut changer de structure).
3. **Calendar probe** : Teste des URLs candidates et vérifie si elles
   retournent un calendrier valide. Lent et indirect.
4. **Hardcoded patterns** (`patterns.py`) : 109 combinaisons prédéfinies pour
   ABCCS, ACJEUNES, AALNV. **Très fragile** — ces codes changent chaque saison.

**Test en direct** : Pour l'entité ABCCS, le scraper retourne 109 poules
(dont **68 marquées "EXTRA"**, i.e. depuis les patterns hardcodés). L'export
CSV officiel en liste seulement **41**. Résultat : 6 poules réelles manquent
(LBM, MSL, SPS, TSA, TSB, TST) et 68 faux positifs sont testés inutilement.

### 2.3 Découverte des matchs (matches.py) — **Parsing partiel**

Le module parse les pages de calendrier HTML (`vbspo_calendrier.php`) pour
extraire les matchs. Il gère 3 cas :

- **Formulaires FFVB** (`ffvolley_fdme.php`) : Extrait le code match et l'URL
  du PDF depuis les `<form>` cachés.
- **Liens externes** (`lnv.fr`) : Détecte les liens vers le site de la LNV.
- **Poule enumerate** : Tente de deviner les codes de match par énumération
  séquentielle quand le calendrier est protégé par un WAF.

**Problème** : Le parsing ne récupère que le `code_match` et le `pdf_url`.
Les noms d'équipes, scores, dates et heures visibles dans le même tableau
HTML sont **complètement ignorés**.

### 2.4 Score Scraper (score_scraper.py) — **Parsing indépendant, non-intégré**

Ce module (`FFVBScoreScraper`) parse les mêmes pages de calendrier que
`matches.py`, mais lui extrait les scores, noms d'équipes, dates, arbitres.
Cependant :

- Il est utilisé **après** l'import initial (par `ScoreCompletionService`),
  ce qui crée une duplication d'effort : deux requêtes HTTP à la même page.
- Il ne partage pas de code avec `matches.py` — les deux modules parsent le
  même HTML de manière indépendante.
- Il ne récupère **pas** les numéros de club FFVB, le lieu, la salle, les
  juges de ligne, ni les marqueurs.

### 2.5 Score Completion Service — **Bon concept, exécution limitée**

Le `ScoreCompletionService` est bien conçu architecturalement :
- Il complète les matchs existants et crée les matchs absents.
- Il gère les cas de forfait, les matchs exemptés, les arbitres.
- Il a un mode dry-run et un callback de progression.

Mais il souffre de la pauvreté de `OnlineMatchScore` : pas de numéro de club,
pas de lieu, pas de salle. L'identification des équipes se fait par nom exact
(`func.upper(EquipeDB.nom) == nom_upper`), ce qui échoue dès qu'un nom a une
variante.

### 2.6 Import Service (import_service.py) — **Matching approximatif**

L'identification des clubs s'appuie sur :
1. Correspondance exacte par nom normalisé
2. Recherche dans les alias (`ClubAliasDB`)
3. Matching flou par distance de Levenshtein

**Problèmes** :
- Pas de matching par code FFVB de club, alors que `ClubDB.code_ffvb` existe
  en base et que l'export CSV fournit ce code.
- Le matching par nom est sensible aux variations : « GRENOBLE UV VB » vs
  « GRENOBLE UCG VUC » vs « GRENOBLE VUC ».
- Les alias sont créés manuellement, pas alimentés automatiquement.

### 2.7 Patterns hardcodés (patterns.py) — **À supprimer**

Le fichier `patterns.py` contient ~109 combinaisons type/code pour 3 entités
(ABCCS, ACJEUNES, AALNV). Ces codes changent à chaque saison et ne sont pas
maintenus dynamiquement.

**Test en direct** : 68 des 109 patterns ne correspondent à aucune poule
existante pour la saison 2025-2026. Ce fichier génère du bruit et devrait
être remplacé par une découverte dynamique via l'export CSV.

---

## 3. Tests de couverture — résultats quantifiés

### 3.1 Couverture des matchs (entité ABCCS, poule EMA)

| Source | Matchs trouvés |
|--------|---------------|
| Scraper (`matches.py`) | 125 |
| Export CSV (`vbspo_calendrier_export.php`) | 182 |
| **Écart** | **57 matchs manquants (31%)** |

Codes manquants : EMA007, EMA127 à EMA135+ — probablement des matchs
reportés, des phases finales, ou des journées ajoutées en cours de saison.

### 3.2 Couverture des poules (entité ABCCS)

| Source | Poules |
|--------|--------|
| Scraper (4 stratégies) | 109 (dont 68 faux positifs) |
| Export CSV | 41 poules réelles |
| **Poules réelles manquantes** | **6** (LBM, MSL, SPS, TSA, TSB, TST) |
| **Faux positifs (patterns.py)** | **68** |

### 3.3 Richesse des données

| Donnée | Scraper actuel | Export CSV | Score scraper |
|--------|---------------|------------|---------------|
| Code match | ✅ | ✅ | ✅ |
| URL PDF | ✅ | ❌ | ❌ |
| Nom équipe A | ❌ | ✅ | ✅ |
| Nom équipe B | ❌ | ✅ | ✅ |
| N° club FFVB A | ❌ | ✅ | ❌ |
| N° club FFVB B | ❌ | ✅ | ❌ |
| Score sets | ❌ | ✅ | ✅ |
| Scores détaillés | ❌ | ✅ | ✅ |
| Total points | ❌ | ✅ | ✅ |
| Date | ❌ | ✅ | ✅ |
| Heure | ❌ | ✅ | ✅ |
| Salle | ❌ | ✅ | ❌ |
| Journée | ❌ | ✅ | ✅ |
| Arbitre 1 (licence + nom + ligue + CD) | ❌ | ✅ | ✅ (nom seul) |
| Arbitre 2 | ❌ | ✅ | ✅ (nom seul) |
| Juges de ligne | ❌ | ✅ | ❌ |
| Marqueur | ❌ | ✅ | ❌ |
| Vainqueur | ❌ | ✅ | ✅ |
| Forfait | ❌ | ✅ | ✅ |

**L'export CSV fournit 40 colonnes de données structurées** avec une seule
requête HTTP, sans parsing HTML fragile.

---

## 4. Sources de données FFVB découvertes

Le crawling du site `ffvbbeach.org/ffvbapp/resu/` a révélé les endpoints suivants :

### 4.1 Sources principales (haute valeur)

#### `vbspo_calendrier_export.php` — ⭐ SOURCE CLÉ

```
GET /ffvbapp/resu/vbspo_calendrier_export.php
    ?saison=2025/2026
    &codent=ABCCS
    [&poule=EMA]           ← optionnel, sans = toutes les poules de l'entité
    &calend=COMPLET
```

**Retourne** : Fichier CSV/Excel avec toutes les colonnes suivantes (40+) :
- `Entité`, `Journée`, `Code match`
- `Date`, `Heure`
- `N° club A`, `Équipe A`, `N° club B`, `Équipe B`
- `Set 1` à `Set 5` (scores détaillés), `Total`
- `Salle`
- `Arb1 licence`, `Arb1 nom`, `Arb1 ligue`, `Arb1 CD`
- `Arb2 licence`, `Arb2 nom`, `Arb2 ligue`, `Arb2 CD`
- `JL1`, `JL2`, `JL3`, `JL4`, `Marqueur`
- `Vainqueur`, `Forfait`

**Avantages** :
- **Données complètes** incluant les n° de club FFVB → identification fiable
- **Une seule requête** pour toute une entité (pas besoin d'itérer poule par poule)
- **Format structuré** (CSV) → pas de parsing HTML fragile
- **Découverte automatique des poules** via la colonne `Code match`
- **Pas d'authentification** requise

#### `planning_club_class.php` — Classement et clubs

```
GET /ffvbapp/resu/planning_club_class.php
    ?codent=ABCCS
    &saison=2025/2026
    &cnclub=0590005       ← numéro de club FFVB (7 chiffres)
```

**Retourne** : Page HTML avec le classement de toutes les équipes du club,
leur division, leurs résultats. Excellent pour :
- Identifier proprement les clubs avec leur code FFVB
- Récupérer le classement d'une équipe
- Croiser les données avec l'export CSV

#### `vbspo_calendrier_export_club.php` — Export par club

```
GET /ffvbapp/resu/vbspo_calendrier_export_club.php
    ?saison=2025/2026
    &codent=ABCCS
    &cnclub=0590005
```

Même format CSV que l'export global, mais filtré pour un seul club.

### 4.2 Sources secondaires (existantes, partiellement exploitées)

| Endpoint | Usage actuel | Données disponibles |
|----------|-------------|-------------------|
| `planning_volley.php` | ✅ Découverte des entités | Liste des entités dans le `<select>` |
| `vbspo.php` | ✅ Découverte des poules (stratégie 1) | Page d'accueil avec liens vers les poules |
| `vbspo_calendrier.php` | ✅ Découverte des matchs | Calendrier HTML avec formulaires PDF |
| `fiche_match_ffvb.php` | ❌ Non utilisé | Détails d'un match (nécessite POST) |

### 4.3 Sources non exploitées (à explorer)

| Endpoint | Accès | Contenu potentiel |
|----------|-------|-------------------|
| `planning_club.php` | GET (cnclub=) | Calendrier du club |
| `adressier.php` | GET (codent=, typ_edition=E) | Annuaire des équipes (format Excel) |
| `engag_division.php` | GET (dans `/ffvbapp/adressier/`) | Engagements par division |
| `vbspo_histo.php` | GET | Historique des saisons |

### 4.4 Coupe de France Jeunes (`ACJEUNES`) — Compétitions jeunes

> Ajouté suite à l'exploration du frameset jeunes du site FFVB.

#### Structure hiérarchique

```
ACJEUNES (entité cachée, non listée dans planning_volley.php)
└── Catégorie d'âge (M21, M18, M18-Challenge, M15, M13, M11)
    └── Division (code 3 lettres : JMX/JFX, CMX/CFX, RMX/RFX, MMX/MFX, BMX/BFX, PMA/PFA)
        └── Tour (01 à 07)
            └── Poules (multiples par tour, code 3 lettres : CYQ, CYR, BFA…)
                └── Matchs (code = poule + 3 chiffres : CYQ001)
```

#### Codes division

| Catégorie | Description            | Masculin | Féminin |
|-----------|------------------------|----------|---------|
| M21       | Juniors                | JMX      | JFX     |
| M18       | Cadets                 | CMX      | CFX     |
| M18-CHAL  | Cadets Challenge       | RMX      | RFX     |
| M15       | Minimes                | MMX      | MFX     |
| M13       | Benjamins              | BMX      | BFX     |
| M11       | Poussins (finales)     | PMA      | PFA     |

#### Sources de données spécifiques

| Source | URL | Usage |
|--------|-----|-------|
| Navigation | `jeunes/{saison}/pbscript.htm` | Découverte des divisions/tours (page frameset) |
| Calendrier | `vbspo_calendrier.php?...&division=CMX&tour=01` | Classements + résultats HTML par tour |
| Export CSV | `vbspo_calendrier_export.php?...&division=CMX` | Données structurées par division |
| Finales M11 | `ffvb_jeunes_finales.php?poule=PMA` | Page spéciale pour les poussins |

#### Comparaison des sources

L'export CSV et les pages calendrier HTML contiennent les **mêmes données de matchs**.
La source CSV est plus riche (40 colonnes : codes club, arbitres, juges, marqueurs),
mais le HTML inclut les **classements/poules** absents du CSV.

⚠️ **L'export global pour l'entité ACJEUNES est extrêmement lent** (>2 min, timeouts fréquents).
Il faut impérativement filtrer par division via le paramètre `division=`.

#### Implémentation : module `jeunes.py`

Le module `pyvolley.scrapers.ffvb.jeunes` implémente un scraper dédié :

1. **Découverte** : `scrape_youth_nav()` parse `pbscript.htm` pour construire
   un `YouthCupIndex` (divisions, tours, URLs)
2. **Export par division** : `fetch_youth_export()` télécharge le CSV d'une
   division spécifique (contourne le timeout)
3. **Classements** : `scrape_youth_tour()` parse le HTML d'un tour pour
   extraire les poules, équipes et matchs
4. **Routage automatique** : `FFVBScraper.scrape_entity("ACJEUNES")` redirige
   automatiquement vers le scraping par division

---

## 5. Problèmes critiques identifiés

### P1. Perte de données à l'étape de scraping (sévérité : CRITIQUE)

`MatchInfo` ne porte que code + pdf_url. Toutes les métadonnées riches
(équipes, scores, date, lieu, arbitres, clubs) disponibles dans le calendrier
HTML ou l'export CSV sont **jetées**.

**Impact** : L'identification des clubs et équipes repose uniquement sur le
parsing PDF (fragile, lent, et indisponible pour les matchs sans feuille).

### P2. Absence d'identification fiable des clubs (sévérité : CRITIQUE)

Le champ `ClubDB.code_ffvb` existe en base mais n'est **jamais alimenté** par
le scraper. L'export CSV fournit ce code pour chaque match, mais il n'est pas
utilisé. Le matching par nom (Levenshtein) est :
- Approximatif (risque de faux positifs/négatifs)
- Non-déterministe (dépend du seuil de similarité)
- Impossible à auditer

### P3. Poules hardcodées et obsolètes (sévérité : ÉLEVÉE)

68 des 109 patterns hardcodés dans `patterns.py` ne correspondent à rien pour
la saison courante. Cela provoque des requêtes HTTP inutiles et peut masquer
les poules réellement manquantes.

### P4. Duplication du parsing calendrier (sévérité : MOYENNE)

`matches.py` et `score_scraper.py` parsent le même HTML de manière
indépendante. Le premier extrait les codes/URLs, le second extrait les
scores/métadonnées. Cela double les requêtes HTTP et le code de maintenance.

### P5. Pipeline linéaire sans enrichissement progressif (sévérité : ÉLEVÉE)

Le pipeline actuel est séquentiel :
```
Scrape → Download PDF → Parse PDF → Import DB → Complete scores
```

La base de données n'est remplie qu'après le parsing PDF. Un match dont le
PDF n'est pas disponible (ou pas encore joué) n'apparaît simplement pas en
base, sauf si le `ScoreCompletionService` est exécuté séparément.

### P6. Pas de traçabilité source/statut (sévérité : MOYENNE)

Pas de champ `source_url` (URL du calendrier d'origine) ni de `parsing_status`
(enum : discovered / scraped / parsed) pour suivre l'état de traitement de
chaque match. `source_pdf` et `parsed_at` existent mais ne couvrent que la
partie PDF.

---

## 6. Architecture cible : approche en deux phases

### Phase 1 : Construction de la base de données (scraping)

```
vbspo_calendrier_export.php ──→ CSV structuré (40 colonnes)
              │
              ├──→ Découverte automatique des poules
              ├──→ Création des matchs en DB (code, date, heure, lieu, journée)
              ├──→ Identification des clubs par code FFVB (n° club)
              ├──→ Identification des équipes par nom + club
              ├──→ Enregistrement des scores (source = "export")
              ├──→ Enregistrement des arbitres (licence, nom, ligue, CD)
              └──→ Construction de l'URL de la feuille de match
                   + statut parsing = "discovered"
```

**Résultat** : La base de données contient **tous** les matchs avec leurs
métadonnées complètes, même ceux dont la feuille de match n'a pas encore été
parsée.

### Phase 2 : Complétion par parsing PDF

```
DB (matchs avec parsing_status = "discovered")
       │
       ├──→ Téléchargement du PDF
       │         statut → "downloaded"
       │
       ├──→ Parsing du PDF (MatchSheetParser)
       │         statut → "parsed"
       │
       └──→ Import des détails : compositions, changements,
            formations, sanctions, timeouts, services
            score_source → "pdf"
```

**Résultat** : Les matchs en base sont enrichis avec les données granulaires
extraites des feuilles de match (compositions d'équipe, formations par set,
statistiques de service, etc.)

### Avantages de cette approche

1. **Couverture complète dès la Phase 1** : Tous les matchs sont en base,
   y compris ceux à venir ou sans PDF.
2. **Identification fiable des clubs** : Le code FFVB du club (7 chiffres)
   est disponible dans l'export CSV.
3. **Traçabilité** : Chaque match porte un `parsing_status` et une
   `source_url`.
4. **Reprise sur erreur** : On peut relancer la Phase 2 pour les matchs
   non encore parsés sans refaire la Phase 1.
5. **Rapidité** : L'export CSV est une seule requête HTTP par entité au lieu
   de dizaines de requêtes HTML.

---

## 7. Plan d'action détaillé

### Étape 1 : Nouveau scraper basé sur l'export CSV

Créer un module `scrapers/ffvb/export_scraper.py` qui :

```python
@dataclass
class ExportMatchInfo:
    """Match enrichi depuis l'export CSV FFVB."""
    code_match: str
    entite_code: str
    poule_code: str       # Déduit du code_match
    saison: str
    journee: Optional[str] = None

    # Équipes (avec codes club FFVB)
    equipe_a_nom: Optional[str] = None
    equipe_b_nom: Optional[str] = None
    club_a_code_ffvb: Optional[str] = None  # "0590005"
    club_b_code_ffvb: Optional[str] = None

    # Résultat
    sets: list[tuple[int, int]] = field(default_factory=list)
    vainqueur: Optional[str] = None
    forfait: bool = False

    # Métadonnées
    date: Optional[str] = None
    heure: Optional[str] = None
    salle: Optional[str] = None

    # Arbitrage
    arbitre_1_licence: Optional[str] = None
    arbitre_1_nom: Optional[str] = None
    arbitre_1_ligue: Optional[str] = None
    arbitre_1_cd: Optional[str] = None
    arbitre_2_licence: Optional[str] = None
    arbitre_2_nom: Optional[str] = None
    arbitre_2_ligue: Optional[str] = None
    arbitre_2_cd: Optional[str] = None

    # Officiels
    juges_de_ligne: list[str] = field(default_factory=list)
    marqueur: Optional[str] = None

    # URL de la feuille de match (construite)
    feuille_match_url: Optional[str] = None
```

**Fonctionnement** :
1. Requête GET vers `vbspo_calendrier_export.php?saison=X&codent=X&calend=COMPLET`
2. Parse le CSV avec le module `csv` Python (pas de dépendance supplémentaire)
3. Pour chaque ligne, crée un `ExportMatchInfo` avec toutes les données
4. Détecte les poules uniques à partir des préfixes des codes de match
5. Construit l'URL de la feuille de match : `ffvolley_fdme.php?codmatch=CODE&codent=ENTITE`

### Étape 2 : Scraper de clubs via `planning_club_class.php`

Créer un module `scrapers/ffvb/club_scraper.py` qui :

1. À partir des codes club FFVB extraits de l'export CSV, requête
   `planning_club_class.php?codent=X&saison=X&cnclub=XXXXXXX`
2. Parse la page HTML pour extraire :
   - Nom officiel du club
   - Ville / département
   - Liste des équipes engagées avec leur division
   - Classement de chaque équipe
3. Met à jour `ClubDB.code_ffvb`, `ClubDB.ville`, `ClubDB.departement`
4. Enrichit les alias de club automatiquement

### Étape 3 : Modifications du schéma DB

```python
# MatchDB — nouveaux champs
source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # URL du calendrier / export d'où le match a été découvert
parsing_status: Mapped[str] = mapped_column(
    String(20), default="discovered"
)  # "discovered" → "downloaded" → "parsed" → "error"
club_a_code_ffvb: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
club_b_code_ffvb: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

# ArbitreDB — nouveaux champs (depuis l'export CSV)
licence_ffvb: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, unique=True)
ligue: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
comite_departemental: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
```

### Étape 4 : Service d'import Phase 1

Créer `database/export_import_service.py` qui :

1. Prend une liste d'`ExportMatchInfo`
2. Pour chaque match :
   - Résout ou crée le `ClubDB` par `code_ffvb` (correspondance exacte, déterministe)
   - Résout ou crée l'`EquipeDB` par nom + club + compétition
   - Résout ou crée le `PouleDB` par préfixe du code match
   - Crée le `MatchDB` avec `parsing_status = "discovered"`, `source_url`, etc.
   - Enregistre les scores si disponibles (`score_source = "export"`)
   - Enregistre les arbitres avec leur licence FFVB

### Étape 5 : Refactoring du pipeline existant

- **Fusionner** `matches.py` et `score_scraper.py` → un seul module parse
  le calendrier HTML quand l'export CSV n'est pas disponible (fallback).
- **Supprimer** `patterns.py` (remplacé par la découverte via export).
- **Adapter** `ScoreCompletionService` pour utiliser l'export CSV au lieu du
  parsing HTML cellule par cellule.
- **Mettre à jour** `MatchImportService` pour préférer le matching par
  `code_ffvb` quand disponible, avec fallback sur le matching par nom.

### Étape 6 : Pipeline intégré

```python
class PyVolleyPipeline:
    """Pipeline complet en deux phases."""

    def phase1_build_database(self, saison: str, entite_codes: list[str]):
        """Phase 1 : Construction de la base depuis les exports CSV."""
        for entite in entite_codes:
            # 1. Télécharger l'export CSV complet
            matches = self.export_scraper.get_all_matches(entite, saison)

            # 2. Importer tous les matchs en DB
            for match in matches:
                self.export_import.import_match(match)

            # 3. Identifier les clubs uniques et enrichir via planning_club_class
            club_codes = {m.club_a_code_ffvb for m in matches}
            club_codes |= {m.club_b_code_ffvb for m in matches}
            for code in club_codes:
                if code:
                    self.club_scraper.enrich_club(entite, saison, code)

    def phase2_parse_pdfs(self, saison: str, limit: int = None):
        """Phase 2 : Enrichissement par parsing des feuilles de match."""
        # Récupérer les matchs avec parsing_status = "discovered"
        matches = self.session.scalars(
            select(MatchDB)
            .where(MatchDB.parsing_status == "discovered")
            .where(MatchDB.match_joue == True)
            .limit(limit)
        )
        for match_db in matches:
            try:
                # 1. Télécharger le PDF
                pdf_path = self.download_pdf(match_db)
                match_db.parsing_status = "downloaded"

                # 2. Parser le PDF
                parsed = self.parser.parse(pdf_path)
                match_db.parsing_status = "parsed"

                # 3. Importer les détails (formations, joueurs, etc.)
                self.import_service.import_details(match_db, parsed)
                match_db.score_source = "pdf"
                match_db.has_details = True

            except Exception as e:
                match_db.parsing_status = "error"
                match_db.remarques = str(e)
```

---

## 8. Modifications de schéma proposées

### Migration Alembic

```python
"""Add export scraping fields and parsing status."""

def upgrade():
    # MatchDB
    op.add_column('matchs', sa.Column('source_url', sa.String(500), nullable=True))
    op.add_column('matchs', sa.Column('parsing_status', sa.String(20),
                  server_default='discovered', nullable=False))
    op.add_column('matchs', sa.Column('club_a_code_ffvb', sa.String(20), nullable=True))
    op.add_column('matchs', sa.Column('club_b_code_ffvb', sa.String(20), nullable=True))

    # ArbitreDB
    op.add_column('arbitres', sa.Column('licence_ffvb', sa.String(20), nullable=True))
    op.add_column('arbitres', sa.Column('ligue', sa.String(50), nullable=True))
    op.add_column('arbitres', sa.Column('comite_departemental', sa.String(10), nullable=True))

    # Index
    op.create_index('ix_matchs_parsing_status', 'matchs', ['parsing_status'])
    op.create_index('ix_matchs_club_a_code', 'matchs', ['club_a_code_ffvb'])
    op.create_index('ix_matchs_club_b_code', 'matchs', ['club_b_code_ffvb'])
    op.create_unique_constraint('uq_arbitre_licence', 'arbitres', ['licence_ffvb'])

def downgrade():
    op.drop_index('ix_matchs_parsing_status')
    op.drop_index('ix_matchs_club_a_code')
    op.drop_index('ix_matchs_club_b_code')
    op.drop_constraint('uq_arbitre_licence', 'arbitres')
    op.drop_column('matchs', 'source_url')
    op.drop_column('matchs', 'parsing_status')
    op.drop_column('matchs', 'club_a_code_ffvb')
    op.drop_column('matchs', 'club_b_code_ffvb')
    op.drop_column('arbitres', 'licence_ffvb')
    op.drop_column('arbitres', 'ligue')
    op.drop_column('arbitres', 'comite_departemental')
```

### Valeurs de `parsing_status`

| Statut | Signification |
|--------|--------------|
| `discovered` | Match trouvé dans l'export CSV, pas encore de PDF |
| `downloaded` | PDF téléchargé localement |
| `parsed` | PDF parsé avec succès, détails importés |
| `error` | Erreur lors du download ou parsing |
| `no_pdf` | Match sans feuille de match (à venir, forfait, etc.) |

---

## 9. Estimations et priorités

### Priorité 1 — Export CSV scraper (impact maximal, effort modéré)

| Tâche | Effort estimé |
|-------|--------------|
| `export_scraper.py` : téléchargement et parsing CSV | 1-2 jours |
| `export_import_service.py` : import Phase 1 en DB | 2-3 jours |
| Migration Alembic (nouveaux champs) | 0.5 jour |
| Tests unitaires et d'intégration | 1-2 jours |
| **Total** | **~5-7 jours** |

**Impact** : Résout P1, P2, P3, P5 d'un coup. Couverture 100% des matchs,
identification déterministe des clubs par code FFVB.

### Priorité 2 — Club scraper (complément d'identification)

| Tâche | Effort estimé |
|-------|--------------|
| `club_scraper.py` : parsing de `planning_club_class.php` | 1 jour |
| Enrichissement automatique des `ClubDB` | 1 jour |
| Tests | 0.5 jour |
| **Total** | **~2.5 jours** |

### Priorité 3 — Refactoring du pipeline (nettoyage)

| Tâche | Effort estimé |
|-------|--------------|
| Fusion `matches.py` + `score_scraper.py` | 1-2 jours |
| Suppression de `patterns.py` | 0.5 jour |
| Adaptation du `ScoreCompletionService` | 1 jour |
| Mise à jour du `MatchImportService` (matching par code FFVB) | 1 jour |
| Pipeline intégré Phase 1 / Phase 2 | 1-2 jours |
| **Total** | **~5-7 jours** |

### Priorité 4 — Traçabilité et monitoring

| Tâche | Effort estimé |
|-------|--------------|
| Ajout `source_url` et `parsing_status` sur les matchs existants | 1 jour |
| Dashboard / rapport de couverture | 1-2 jours |
| **Total** | **~2-3 jours** |

---

## Annexe A — Exemple d'export CSV FFVB

Requête :
```
GET https://www.ffvbbeach.org/ffvbapp/resu/vbspo_calendrier_export.php?saison=2025/2026&codent=ABCCS&poule=EMA&calend=COMPLET
```

Colonnes typiques (séparateur tabulation, 40 colonnes) :
```
[0]  EntitÈ      [10] Score       [20] Arb2_CD     [30] Mrq1_Nom
[1]  Jo           [11] Total       [21] Jdl1_Lic    [31] Mrq2_Lic
[2]  Match        [12] Salle       [22] Jdl1_Nom    [32] Mrq2_Nom
[3]  Date         [13] Arb1_Lic    [23] Jdl2_Lic    [33] Sup_Lic
[4]  Heure        [14] Arb1_Nom    [24] Jdl2_Nom    [34] Sup_Nom
[5]  EQA_no       [15] Arb1_LR     [25] Jdl3_Lic    [35] Slnv_Lic
[6]  EQA_nom      [16] Arb1_CD     [26] Jdl3_Nom    [36] Slnv_Nom
[7]  EQB_no       [17] Arb2_Lic    [27] Jdl4_Lic    [37] Vid_Lic
[8]  EQB_nom      [18] Arb2_Nom    [28] Jdl4_Nom    [38] Vid_Nom
[9]  Set          [19] Arb2_LR     [29] Mrq1_Lic    [39] (vide)
```

Exemple de ligne :
```
ABCCS  01  2FA001  2025-09-28  15:00  0136082  VITROLLES SPORTS VOLLEY-BALL  ...  xxxxx  ...  LEO LAGRANGE  ...
```

## Annexe B — Endpoints FFVB complets

| Endpoint | Méthode | Paramètres | Format | Auth |
|----------|---------|-----------|--------|------|
| `vbspo_calendrier_export.php` | GET | `saison`, `codent`, `poule`(opt), `calend=COMPLET` | CSV/TSV | Non |
| `vbspo_calendrier_export_club.php` | GET | `saison`, `codent`, `cnclub` | CSV/TSV | Non |
| `planning_club_class.php` | GET | `codent`, `saison`, `cnclub` | HTML | Non |
| `planning_club.php` | GET | `codent`, `cnclub` | HTML | Non |
| `planning_volley.php` | GET | — | HTML | Non |
| `vbspo.php` | GET | `codent`, `saison` | HTML | Non |
| `vbspo_calendrier.php` | GET | `codent`, `saison`, `poession`, `poession2`, `codpool` | HTML | Non |
| `fiche_match_ffvb.php` | POST | `codmatch`, `codent` | HTML | Non |
| `adressier.php` | GET | `codent`, `saison`, `typ_edition=E` | Excel | Non |
| `engag_division.php` | GET | — | HTML | Non |

## Annexe C — Tests de validation recommandés

### Test 1 : Complétude export vs scraper

```python
def test_export_coverage():
    """Vérifie que l'export CSV contient tous les matchs du calendrier HTML."""
    # Pour chaque entité, comparer le nombre de matchs
    # entre la page calendrier et l'export CSV
    export_matches = get_export_matches("ABCCS", "EMA")
    calendar_matches = get_calendar_matches("ABCCS", "EMA")
    assert len(export_matches) >= len(calendar_matches)
```

### Test 2 : Identification des clubs par code FFVB

```python
def test_club_identification():
    """Vérifie que le code FFVB permet une identification déterministe."""
    export = get_export_matches("ABCCS", "EMA")
    clubs_with_code = [m for m in export if m.club_a_code_ffvb]
    assert len(clubs_with_code) / len(export) > 0.95  # >95% ont un code
```

### Test 3 : Régression poules

```python
def test_poule_discovery():
    """Vérifie que l'export CSV retrouve toutes les poules existantes."""
    export_poules = get_poules_from_export("ABCCS")
    assert "LBM" in export_poules  # Poule manquante dans le scraper actuel
    assert "MSL" in export_poules
    assert "SPS" in export_poules
```

### Test 4 : Pipeline Phase 1 end-to-end

```python
def test_phase1_import():
    """Vérifie que la Phase 1 crée tous les matchs avec les bonnes métadonnées."""
    pipeline = PyVolleyPipeline(session)
    pipeline.phase1_build_database("2025-2026", ["ABCCS"])

    match = session.scalar(
        select(MatchDB).where(MatchDB.code_match == "EMA001")
    )
    assert match is not None
    assert match.parsing_status == "discovered"
    assert match.club_a_code_ffvb is not None
    assert match.equipe_a is not None
    assert match.date_match is not None
    assert match.source_url is not None
```
