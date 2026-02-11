# PyVolley

PyVolley est un projet open-source visant à fournir une solution complète pour la gestion et l'analyse de données liées au volley-ball. Il offre des fonctionnalités de scraping, de parsing, d'importation de données en base, ainsi qu'une interface web pour visualiser les statistiques et les informations sur les matchs.

## Roadmap

- [x] Initialiser le projet avec une structure de base
- [x] Développer les scrapers pour récupérer les feuilles de match depuis le site de la FFVB
- [x] Télécharger les feuilles de match et les stocker localement
- [ ] Implémenter les parsers PDF pour extraire les données des feuilles de match
- [ ] Parser des données de test pour valider les parsers
- [ ] Création des statistiques et des visualisations basées sur les données extraites
- [ ] Créer une structure de base de données avec SQLAlchemy et Alembic
- [ ] Parser les données extraites et les importer dans la base de données
- [ ] Développer l'interface avec les fonctionnalités de base (affichage des matchs, statistiques, etc.)
- [ ] Ajouter des fonctionnalités avancées (comparaison de joueurs, tendances, etc.)



### Analyse

#### Match

- Date
- Compétition
- Équipes
- Score
- Lieu
- Arbitres


#### Joueur

- Nom
- Prénom
- Licence
- Equipe
- Position
- Jeu sur le terrain (par sets)
- Nombre de services (+ séries)


#### Equipe

- Nom
- Ville
- Division
- Entraîneur
- Joueurs (liste des joueurs avec leurs statistiques)
- Résultats (liste des matchs avec les scores et les statistiques)
- Classement (position dans la compétition, points, etc)

#### Club

- Nom
- Ville
- Equipes
- Entraîneurs
- Joueurs
- Résultats (liste des matchs avec les scores et les statistiques)
  
### Sites internet

#### Structure

Recherche :

- Avec ajout de badge, filtre, etc
- Recherche de club, arbitre, joueur, équipe, etc

#### Design

Carte de france interactive pour limiter la recherche, frise pour limiter la saison, etc

