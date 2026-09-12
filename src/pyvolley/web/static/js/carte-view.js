/**
 * PyVolley — Hub Carte Interactive (Modern Sports Edition)
 *
 * Contrôleur Alpine.js pour la vue cartographique dédiée /carte.
 * Initialisé par défaut sur la France métropolitaine en vue Satellite Hybride.
 * Affiche les clubs et salles avec navigation rapide par zones géographiques,
 * clustering ultra-rapide par lot, calcul de distance GPS, et recherche intelligente.
 */

(function () {
  'use strict';

  // ══════════════════════════════════════════════════════════════
  // Zones Géographiques Prédéfinies
  // ══════════════════════════════════════════════════════════════

  const GEO_ZONES = {
    metropole:  {
      name: 'France métropolitaine',
      center: [46.6, 2.3],
      zoom: 6,
      minZoom: 5,
      bounds: [[39.0, -8.5], [53.0, 12.5]],
    },
    corse:      {
      name: 'Corse',
      center: [42.15, 9.15],
      zoom: 9,
      minZoom: 7,
      bounds: [[41.0, 8.0], [43.5, 10.2]],
    },
    guadeloupe: {
      name: 'Guadeloupe',
      center: [16.25, -61.55],
      zoom: 10,
      minZoom: 8,
      bounds: [[15.5, -62.3], [17.0, -60.8]],
    },
    martinique: {
      name: 'Martinique',
      center: [14.64, -61.02],
      zoom: 10,
      minZoom: 8,
      bounds: [[14.1, -61.5], [15.1, -60.5]],
    },
    guyane:     {
      name: 'Guyane',
      center: [4.4, -53.12],
      zoom: 8,
      minZoom: 6,
      bounds: [[1.8, -55.5], [6.2, -51.0]],
    },
    reunion:    {
      name: 'La Réunion',
      center: [-21.11, 55.53],
      zoom: 10,
      minZoom: 8,
      bounds: [[-21.6, 54.9], [-20.6, 56.1]],
    },
    mayotte:    {
      name: 'Mayotte',
      center: [-12.82, 45.16],
      zoom: 11,
      minZoom: 9,
      bounds: [[-13.2, 44.8], [-12.4, 45.5]],
    },
  };

  // ══════════════════════════════════════════════════════════════
  // Palettes de Couleurs & Icônes SVG
  // ══════════════════════════════════════════════════════════════

  const ICON_COLORS = {
    blue:   { bg: '#2563eb', border: '#1d4ed8', glow: 'rgba(37,99,235,0.5)' },
    cyan:   { bg: '#0891b2', border: '#0e7490', glow: 'rgba(8,145,178,0.5)' },
    green:  { bg: '#16a34a', border: '#15803d', glow: 'rgba(22,163,74,0.5)' },
    red:    { bg: '#dc2626', border: '#b91c1c', glow: 'rgba(220,38,38,0.5)' },
    gold:   { bg: '#d97706', border: '#b45309', glow: 'rgba(217,119,6,0.5)' },
    purple: { bg: '#9333ea', border: '#7e22ce', glow: 'rgba(147,51,234,0.5)' },
  };

  const SVG_SYMBOLS = {
    club: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" fill="white" transform="translate(4, 5) scale(0.66)"/>',
    salle: '<path d="M3 21h18M5 21V7l8-4v18M19 21V11l-6-3M9 9v.01M9 12v.01M9 15v.01M9 18v.01" stroke="white" stroke-width="1.8" stroke-linecap="round" fill="none" transform="translate(4, 4) scale(0.66)"/>',
    dot: '<circle cx="12" cy="12" r="5" fill="white"/>',
  };

  function createMarkerIcon(iconType, colorKey, isSelected) {
    var c = ICON_COLORS[colorKey] || ICON_COLORS.blue;
    var symbolHtml = SVG_SYMBOLS.dot;

    if (iconType === 'club') {
      symbolHtml = SVG_SYMBOLS.club;
    } else if (iconType === 'salle') {
      symbolHtml = SVG_SYMBOLS.salle;
    }

    var scale = isSelected ? 'scale(1.32)' : 'scale(1)';
    var strokeWidth = isSelected ? '2.5' : '1.5';
    var strokeColor = isSelected ? '#ffffff' : c.border;
    var filterGlow = isSelected ? 'filter: drop-shadow(0 0 8px ' + c.glow + ');' : '';

    var svg =
      '<svg class="pyvolley-pin" style="transform: ' + scale + '; ' + filterGlow + ' transform-origin: 14px 40px;" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28 40" width="28" height="40">' +
        '<path d="M14 0C6.3 0 0 6.3 0 14c0 10.5 14 26 14 26s14-15.5 14-26C28 6.3 21.7 0 14 0z" ' +
              'fill="' + c.bg + '" stroke="' + strokeColor + '" stroke-width="' + strokeWidth + '"/>' +
        '<circle cx="14" cy="14" r="9.5" fill="rgba(0,0,0,0.25)"/>' +
        '<g transform="translate(2, 2)">' + symbolHtml + '</g>' +
      '</svg>';

    return L.divIcon({
      html: svg,
      className: 'pyvolley-marker-icon' + (isSelected ? ' is-selected' : ''),
      iconSize: [28, 40],
      iconAnchor: [14, 40],
      popupAnchor: [0, -40],
    });
  }

  // ══════════════════════════════════════════════════════════════
  // Calcul de Distance GPS (Haversine en km)
  // ══════════════════════════════════════════════════════════════

  function haversineDistanceKm(lat1, lon1, lat2, lon2) {
    var R = 6371; // Rayon de la Terre en km
    var dLat = (lat2 - lat1) * Math.PI / 180;
    var dLon = (lon2 - lon1) * Math.PI / 180;
    var a =
      Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
      Math.sin(dLon / 2) * Math.sin(dLon / 2);
    var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
  }

  function formatDistance(km) {
    if (km == null || isNaN(km)) return '';
    if (km < 1) {
      return Math.round(km * 1000) + ' m';
    }
    return km < 10 ? km.toFixed(1) + ' km' : Math.round(km) + ' km';
  }

  // ══════════════════════════════════════════════════════════════
  // Dictionnaire des Départements Français (Code → Nom)
  // ══════════════════════════════════════════════════════════════

  const DEPT_NAMES = {
    '01': 'Ain', '02': 'Aisne', '03': 'Allier', '04': 'Alpes-de-Haute-Provence', '05': 'Hautes-Alpes',
    '06': 'Alpes-Maritimes', '07': 'Ardèche', '08': 'Ardennes', '09': 'Ariège', '10': 'Aube',
    '11': 'Aude', '12': 'Aveyron', '13': 'Bouches-du-Rhône', '14': 'Calvados', '15': 'Cantal',
    '16': 'Charente', '17': 'Charente-Maritime', '18': 'Cher', '19': 'Corrèze', '2A': 'Corse-du-Sud',
    '2B': 'Haute-Corse', '21': "Côte-d'Or", '22': "Côtes-d'Armor", '23': 'Creuse', '24': 'Dordogne',
    '25': 'Doubs', '26': 'Drôme', '27': 'Eure', '28': 'Eure-et-Loir', '29': 'Finistère',
    '30': 'Gard', '31': 'Haute-Garonne', '32': 'Gers', '33': 'Gironde', '34': 'Hérault',
    '35': 'Ille-et-Vilaine', '36': 'Indre', '37': 'Indre-et-Loire', '38': 'Isère', '39': 'Jura',
    '40': 'Landes', '41': 'Loir-et-Cher', '42': 'Loire', '43': 'Haute-Loire', '44': 'Loire-Atlantique',
    '45': 'Loiret', '46': 'Lot', '47': 'Lot-et-Garonne', '48': 'Lozère', '49': 'Maine-et-Loire',
    '50': 'Manche', '51': 'Marne', '52': 'Haute-Marne', '53': 'Mayenne', '54': 'Meurthe-et-Moselle',
    '55': 'Meuse', '56': 'Morbihan', '57': 'Moselle', '58': 'Nièvre', '59': 'Nord',
    '60': 'Oise', '61': 'Orne', '62': 'Pas-de-Calais', '63': 'Puy-de-Dôme', '64': 'Pyrénées-Atlantiques',
    '65': 'Hautes-Pyrénées', '66': 'Pyrénées-Orientales', '67': 'Bas-Rhin', '68': 'Haut-Rhin', '69': 'Rhône',
    '70': 'Haute-Saône', '71': 'Saône-et-Loire', '72': 'Sarthe', '73': 'Savoie', '74': 'Haute-Savoie',
    '75': 'Paris', '76': 'Seine-Maritime', '77': 'Seine-et-Marne', '78': 'Yvelines', '79': 'Deux-Sèvres',
    '80': 'Somme', '81': 'Tarn', '82': 'Tarn-et-Garonne', '83': 'Var', '84': 'Vaucluse',
    '85': 'Vendée', '86': 'Vienne', '87': 'Haute-Vienne', '88': 'Vosges', '89': 'Yonne',
    '90': 'Territoire de Belfort', '91': 'Essonne', '92': 'Hauts-de-Seine', '93': 'Seine-Saint-Denis',
    '94': 'Val-de-Marne', '95': "Val-d'Oise", '971': 'Guadeloupe', '972': 'Martinique',
    '973': 'Guyane', '974': 'La Réunion', '976': 'Mayotte',
  };

  // Normalisation de chaîne (insensible aux accents et majuscules)
  function normalizeStr(str) {
    if (!str) return '';
    return str
      .toString()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .trim();
  }

  // ══════════════════════════════════════════════════════════════
  // Fournisseurs de Fonds de Carte (Tile Layers)
  // ══════════════════════════════════════════════════════════════

  const TILE_LAYERS = {
    satellite: {
      name: 'Satellite Hybride (Esri)',
      icon: 'globe',
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      labelsUrl: 'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
      attrib: 'Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community',
      subdomains: '',
      maxZoom: 18,
    },
    osm: {
      name: 'Standard (OpenStreetMap)',
      icon: 'map',
      url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      attrib: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      subdomains: 'abc',
      maxZoom: 19,
    },
  };

  // ══════════════════════════════════════════════════════════════
  // Alpine.js Component: carteView
  // ══════════════════════════════════════════════════════════════

  document.addEventListener('alpine:init', function () {
    Alpine.data('carteView', function (initialConfig) {
      initialConfig = initialConfig || {};

      return {
        // ── Filtres (Toujours toutes saisons confondues) ─────
        entityType:     (initialConfig.entityType && initialConfig.entityType !== 'match') ? initialConfig.entityType : 'club',
        selectedZone:   initialConfig.selectedZone || 'metropole',
        ligue:          initialConfig.ligue || '',
        departement:    initialConfig.departement || '',
        competitionId:  initialConfig.competitionId ? parseInt(initialConfig.competitionId, 10) : null,
        clubId:         initialConfig.clubId ? parseInt(initialConfig.clubId, 10) : null,
        searchQuery:    initialConfig.searchQuery || '',

        // ── États d'Affichage & Cartographie ─────────────────
        map:                 null,
        tileLayer:           null,
        labelsTileLayer:     null,
        currentTileKey:      'satellite',
        clusteringEnabled:   true,
        markerGroup:         null,
        activePinLayer:      null, // Calque dédié Leaflet pour le pin/halo actif (sub-pixel stable)
        allMarkersData:      [],
        displayedMarkers:    [],
        markerInstances:     new Map(),
        selectedPoint:       null,
        showDrawer:          true,
        showLayersMenu:      false,
        isFullscreen:        false,
        loading:             true,
        error:               false,
        userLocationMarker:  null,
        userCoords:          null, // [lat, lng]
        sortByDistance:      false,
        filterByVisibleBounds: false,

        // ── Rendu Progressif du Drawer (Anti-Lag DOM) ────────
        drawerLimit:         80,
        drawerIncrement:     60,

        // ── Toast Notifications ──────────────────────────────
        showToast:           false,
        toastMessage:        '',
        toastTimer:          null,


        // ── Compteurs KPIs ───────────────────────────────────
        totalCount:  0,
        clubCount:   0,
        salleCount:  0,

        // ── Initialisation ───────────────────────────────────
        async init() {
          await this.$nextTick();
          this.initMap();
          await this.loadLocations();
          this.setupEvents();
          if (window.lucide) {
            window.lucide.createIcons();
          }
        },

        // ── Initialisation Leaflet ───────────────────────────
        initMap() {
          var container = this.$refs.mapContainer;
          if (!container) return;

          var initialZone = GEO_ZONES[this.selectedZone] || GEO_ZONES.metropole;

          this.map = L.map(container, {
            center: initialZone.center,
            zoom: initialZone.zoom,
            minZoom: initialZone.minZoom || 5,
            maxZoom: 18,
            maxBounds: initialZone.bounds,
            maxBoundsViscosity: 0.85,
            scrollWheelZoom: true,
            zoomControl: false,
          });

          L.control.zoom({ position: 'bottomleft' }).addTo(this.map);
          L.control.scale({ imperial: false, metric: true, position: 'bottomleft' }).addTo(this.map);

          // Vue par défaut : Satellite Hybride (photos + labels)
          this.setTileLayer('satellite');
          this.initMarkerLayer();

          // Calque dédié pour le pin actif / halo sélectionné (ancrage natif Leaflet)
          this.activePinLayer = L.layerGroup().addTo(this.map);

          var self = this;
          this.map.on('click', function () {
            self.showLayersMenu = false;
          });

          // Écoute des déplacements et zooms pour le filtre par emprise visible
          this.map.on('moveend zoomend', function () {
            if (self.filterByVisibleBounds) {
              self.filterAndRenderMarkers(false);
            }
          });
        },

        initMarkerLayer() {
          if (this.markerGroup) {
            this.map.removeLayer(this.markerGroup);
          }

          if (this.clusteringEnabled && typeof L.markerClusterGroup === 'function') {
            this.markerGroup = L.markerClusterGroup({
              maxClusterRadius: 42,
              spiderfyOnMaxZoom: true,
              showCoverageOnHover: false,
              zoomToBoundsOnClick: true,
              chunkedLoading: true,
              iconCreateFunction: function (cluster) {
                var count = cluster.getChildCount();
                var size = count < 15 ? 'small' : count < 60 ? 'medium' : 'large';
                return L.divIcon({
                  html: '<div class="pyvolley-cluster pyvolley-cluster-' + size + '">' + count + '</div>',
                  className: 'pyvolley-cluster-icon',
                  iconSize: L.point(42, 42),
                });
              },
            });
          } else {
            this.markerGroup = L.layerGroup();
          }

          this.markerGroup.addTo(this.map);
        },

        // ── Gestion des Calques de Fond ──────────────────────
        setTileLayer(key) {
          if (!TILE_LAYERS[key]) key = 'satellite';

          if (this.tileLayer) {
            this.map.removeLayer(this.tileLayer);
            this.tileLayer = null;
          }
          if (this.labelsTileLayer) {
            this.map.removeLayer(this.labelsTileLayer);
            this.labelsTileLayer = null;
          }

          var conf = TILE_LAYERS[key];
          this.tileLayer = L.tileLayer(conf.url, {
            attribution: conf.attrib,
            subdomains: conf.subdomains,
            maxZoom: conf.maxZoom,
          }).addTo(this.map);

          // Si calque satellite, superposer le calque de libellés de voiries et frontières
          if (conf.labelsUrl) {
            this.labelsTileLayer = L.tileLayer(conf.labelsUrl, {
              pane: 'shadowPane',
              maxZoom: conf.maxZoom,
              opacity: 0.95,
            }).addTo(this.map);
          }

          this.currentTileKey = key;
          this.showLayersMenu = false;
        },

        // ── Navigation Rapide par Zone Géographique ───────────
        goToZone(zoneKey) {
          this.selectedZone = zoneKey || 'metropole';
          var zone = GEO_ZONES[this.selectedZone] || GEO_ZONES.metropole;
          if (this.map) {
            this.map.setMinZoom(zone.minZoom || 5);
            this.map.setMaxBounds(zone.bounds);
            this.map.flyTo(zone.center, zone.zoom, {
              duration: 1.2,
              easeLinearity: 0.25,
            });
          }
          this.updateUrl();
        },

        // ── Toggle du Clustering ─────────────────────────────
        toggleClustering() {
          this.clusteringEnabled = !this.clusteringEnabled;
          this.initMarkerLayer();
          this.renderMarkers(this.displayedMarkers);
        },

        // ── Changement de Département / Ligue ────────────────
        onDepartementChange() {
          this.loadLocations(true);
        },

        onLigueChange() {
          this.loadLocations(true);
        },

        // ── Chargement des Données depuis l'API ──────────────
        async loadLocations(autoFit) {
          this.loading = true;
          this.error = false;
          this.selectedPoint = null;
          if (this.activePinLayer) {
            this.activePinLayer.clearLayers();
          }

          try {
            var params = new URLSearchParams();
            if (this.entityType && this.entityType !== 'all') {
              params.set('entity_type', this.entityType);
            } else {
              params.set('entity_type', 'club,salle');
            }
            if (this.ligue)         params.set('ligue', this.ligue);
            if (this.departement)   params.set('departement', this.departement);
            if (this.competitionId) params.set('competition_id', this.competitionId);
            if (this.clubId)        params.set('club_id', this.clubId);
            params.set('limit', '4000');

            var url = '/api/map/locations?' + params.toString();
            var resp = await fetch(url);
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            var data = await resp.json();

            var rawMarkers = data.markers || [];
            this.allMarkersData = rawMarkers.filter(function (m) {
              return m.entity_type !== 'match';
            });

            // Si coordonnées utilisateur déjà connues, recalculer les distances
            if (this.userCoords) {
              this.calculateDistances();
            }

            this.filterAndRenderMarkers(false);
            this.updateUrl();

            // Cadrage cartographique intelligent
            if (this.displayedMarkers.length > 0 && (this.departement || this.ligue || this.clubId || this.competitionId || autoFit)) {
              var validCoords = [];
              for (var i = 0; i < this.displayedMarkers.length; i++) {
                var dm = this.displayedMarkers[i];
                if (dm.lat != null && dm.lng != null) {
                  validCoords.push([dm.lat, dm.lng]);
                }
              }
              if (validCoords.length > 0) {
                var bounds = L.latLngBounds(validCoords);
                if (bounds.isValid()) {
                  this.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 13 });
                }
              }
            } else if (!this.departement && !this.ligue) {
              var zone = GEO_ZONES[this.selectedZone] || GEO_ZONES.metropole;
              this.map.setMinZoom(zone.minZoom || 5);
              this.map.setMaxBounds(zone.bounds);
              this.map.setView(zone.center, zone.zoom);
            }
          } catch (e) {
            console.error('[PyVolley Carte] Échec du chargement des marqueurs:', e);
            this.error = true;
          } finally {
            this.loading = false;
            this.$nextTick(function () {
              if (window.lucide) window.lucide.createIcons();
            });
          }
        },

        // ── Calcul des distances par rapport à l'utilisateur ─
        calculateDistances() {
          if (!this.userCoords) return;
          var uLat = this.userCoords[0];
          var uLng = this.userCoords[1];

          for (var i = 0; i < this.allMarkersData.length; i++) {
            var m = this.allMarkersData[i];
            m.distance_km = haversineDistanceKm(uLat, uLng, m.lat, m.lng);
            m.distance_formatted = formatDistance(m.distance_km);
          }
        },

        toggleDistanceSort() {
          if (!this.userCoords) {
            this.locateUser();
            return;
          }
          this.sortByDistance = !this.sortByDistance;
          this.filterAndRenderMarkers(false);
        },

        toggleBoundsFilter() {
          this.filterByVisibleBounds = !this.filterByVisibleBounds;
          this.filterAndRenderMarkers(false);
        },

        // ── Filtrage Côté Client (Recherche Instantanée & Départements) ─────
        filterAndRenderMarkers(autoFit) {
          var rawQuery = (this.searchQuery || '').trim();
          var query = normalizeStr(rawQuery);
          var filtered = this.allMarkersData;

          // 1. Filtre par recherche textuelle intelligente (Nom, Ville, Dép. code, Dép. nom)
          if (query) {
            var depMatch = query.match(/(?:dep|dep\.|departement|dép|dép\.)\s*([0-9]{1,3}|2a|2b)/i);
            var queryDepCode = depMatch ? depMatch[1].padStart(2, '0').toUpperCase() : null;

            filtered = filtered.filter(function (m) {
              var matchLabel = normalizeStr(m.label).includes(query);
              var matchSub = normalizeStr(m.sublabel).includes(query);
              var matchVille = normalizeStr(m.ville).includes(query);

              var deptCode = (m.departement || '').toString().trim().toUpperCase();
              var deptName = DEPT_NAMES[deptCode] || '';
              var normDeptName = normalizeStr(deptName);

              var matchDept = false;
              if (queryDepCode) {
                matchDept = (deptCode === queryDepCode);
              } else {
                matchDept = (deptCode && deptCode === query.toUpperCase()) ||
                            (deptCode && ('dep ' + deptCode).includes(query)) ||
                            (normDeptName && normDeptName.includes(query));
              }

              return matchLabel || matchSub || matchVille || matchDept;
            });
          }

          // 2. Filtre par emprise visible sur la carte (Bounding Box)
          if (this.filterByVisibleBounds && this.map) {
            var bounds = this.map.getBounds();
            filtered = filtered.filter(function (m) {
              return bounds.contains([m.lat, m.lng]);
            });
          }

          // 3. Tri par distance (si activé)
          if (this.sortByDistance && this.userCoords) {
            filtered = filtered.slice().sort(function (a, b) {
              var da = a.distance_km != null ? a.distance_km : 999999;
              var db = b.distance_km != null ? b.distance_km : 999999;
              return da - db;
            });
          }

          this.displayedMarkers = filtered;
          this.drawerLimit = 80;
          this.renderMarkers(filtered);
          this.updateCounts(filtered);

          // Cadrage automatique si la recherche filtre précisément
          if (autoFit && filtered.length > 0 && query.length >= 2) {
            var validCoords = [];
            for (var k = 0; k < filtered.length; k++) {
              if (filtered[k].lat != null && filtered[k].lng != null) {
                validCoords.push([filtered[k].lat, filtered[k].lng]);
              }
            }
            if (validCoords.length > 0) {
              var b = L.latLngBounds(validCoords);
              if (b.isValid()) {
                this.map.fitBounds(b, { padding: [50, 50], maxZoom: 13 });
              }
            }
          }
        },

        // ── Rendu Ultra-Rapide par Lot (addLayers) ────────────
        renderMarkers(markersData) {
          this.markerGroup.clearLayers();
          this.markerInstances.clear();

          var self = this;
          var markersToBatch = [];

          for (var i = 0; i < markersData.length; i++) {
            var m = markersData[i];
            var isSel = self.selectedPoint &&
                        self.selectedPoint.entity_type === m.entity_type &&
                        self.selectedPoint.entity_id === m.entity_id;

            var icon = createMarkerIcon(m.icon_type || m.entity_type, m.icon_color || 'blue', isSel);
            var marker = L.marker([m.lat, m.lng], { icon: icon });

            marker.bindPopup(m.popup_html, {
              maxWidth: 320,
              className: 'pyvolley-popup',
            });

            // Événement clic et fermeture popup
            (function (markerData, markerInstance) {
              markerInstance.on('click', function () {
                self.selectPoint(markerData);
                self.ensurePointVisibleInDrawer(markerData);
              });
              markerInstance.on('popupclose', function () {
                if (self.selectedPoint &&
                    self.selectedPoint.entity_type === markerData.entity_type &&
                    self.selectedPoint.entity_id === markerData.entity_id) {
                  self.selectedPoint = null;
                  if (self.activePinLayer) {
                    self.activePinLayer.clearLayers();
                  }
                }
              });
            })(m, marker);

            markersToBatch.push(marker);
            var key = m.entity_type + '_' + m.entity_id;
            this.markerInstances.set(key, marker);
          }

          if (typeof this.markerGroup.addLayers === 'function') {
            this.markerGroup.addLayers(markersToBatch);
          } else {
            for (var j = 0; j < markersToBatch.length; j++) {
              this.markerGroup.addLayer(markersToBatch[j]);
            }
          }
        },

        updateCounts(markers) {
          this.totalCount = markers.length;
          var c = 0, s = 0;
          for (var i = 0; i < markers.length; i++) {
            var type = markers[i].entity_type;
            if (type === 'club') c++;
            else if (type === 'salle') s++;
          }
          this.clubCount = c;
          this.salleCount = s;
        },

        // ── Accesseurs pour les marqueurs affichés dans le drawer
        getVisibleDrawerMarkers() {
          return (this.displayedMarkers || []).slice(0, this.drawerLimit);
        },

        hasMoreDrawer() {
          return (this.displayedMarkers || []).length > this.drawerLimit;
        },

        loadMoreDrawer() {
          this.drawerLimit += this.drawerIncrement;
        },

        handleDrawerScroll(e) {
          var target = e.target;
          if (target.scrollTop + target.clientHeight >= target.scrollHeight - 100) {
            if (this.hasMoreDrawer()) {
              this.loadMoreDrawer();
            }
          }
        },

        // ── Survol d'une carte dans le Drawer ────────────────
        highlightMarker(point, isHighlighted) {
          if (!point) return;
          var key = point.entity_type + '_' + point.entity_id;
          var marker = this.markerInstances.get(key);
          if (marker) {
            var el = marker.getElement();
            if (el) {
              if (isHighlighted) {
                el.classList.add('is-hovered');
              } else {
                el.classList.remove('is-hovered');
              }
            }
          }
        },

        // ── Clic sur un Point (Drawer ou Carte) — Ancrage Stable ──
        selectPoint(point) {
          if (!point) return;
          this.selectedPoint = point;
          if (!this.map) return;

          // Si le point est en dehors des limites de la zone active, ajuster la zone
          var currentZone = GEO_ZONES[this.selectedZone] || GEO_ZONES.metropole;
          var curBounds = L.latLngBounds(currentZone.bounds);
          if (!curBounds.contains([point.lat, point.lng])) {
            for (var zk in GEO_ZONES) {
              var zb = L.latLngBounds(GEO_ZONES[zk].bounds);
              if (zb.contains([point.lat, point.lng])) {
                this.selectedZone = zk;
                this.map.setMinZoom(GEO_ZONES[zk].minZoom || 5);
                this.map.setMaxBounds(GEO_ZONES[zk].bounds);
                break;
              }
            }
          }

          // Nettoyer le halo précédent
          if (this.activePinLayer) {
            this.activePinLayer.clearLayers();
          }

          // Poser un halo natif Leaflet qui suit parfaitement les zooms et déplacements
          var halo = L.circleMarker([point.lat, point.lng], {
            radius: 20,
            color: '#3b82f6',
            weight: 3,
            opacity: 0.95,
            fillColor: '#60a5fa',
            fillOpacity: 0.25,
            className: 'pyvolley-active-pin-halo',
            interactive: false,
          });
          this.activePinLayer.addLayer(halo);

          var key = point.entity_type + '_' + point.entity_id;
          var marker = this.markerInstances.get(key);
          var self = this;

          if (marker) {
            // Si MarkerClusterGroup est actif, zoomToShowLayer déplie le cluster proprement
            if (this.clusteringEnabled && this.markerGroup && typeof this.markerGroup.zoomToShowLayer === 'function') {
              this.markerGroup.zoomToShowLayer(marker, function () {
                marker.openPopup();
              });
            } else {
              var targetZoom = Math.max(this.map.getZoom(), 14);
              this.map.flyTo([point.lat, point.lng], targetZoom, { duration: 0.6 });
              this.map.once('moveend', function () {
                marker.openPopup();
              });
            }
          } else {
            this.map.flyTo([point.lat, point.lng], Math.max(this.map.getZoom(), 14), { duration: 0.6 });
          }
        },

        ensurePointVisibleInDrawer(point) {
          var self = this;
          this.$nextTick(function () {
            var card = document.getElementById('drawer-item-' + point.entity_type + '-' + point.entity_id);
            if (card) {
              card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
          });
        },

        // ── Changement de Filtre Type ────────────────────────
        setEntityType(type) {
          this.entityType = type;
          this.loadLocations(false);
        },

        // ── Recentrage sur la Zone Active ─────────────────────
        recenter() {
          if (!this.map) return;
          var zone = GEO_ZONES[this.selectedZone] || GEO_ZONES.metropole;
          this.map.setMinZoom(zone.minZoom || 5);
          this.map.setMaxBounds(zone.bounds);
          this.map.flyTo(zone.center, zone.zoom, { duration: 0.8 });
        },

        // ── Géolocalisation Utilisateur ──────────────────────
        locateUser() {
          if (!navigator.geolocation) {
            this.triggerToast('La géolocalisation n’est pas supportée par votre navigateur.');
            return;
          }

          var self = this;
          this.triggerToast('Localisation GPS en cours…');

          navigator.geolocation.getCurrentPosition(
            function (position) {
              var lat = position.coords.latitude;
              var lng = position.coords.longitude;
              self.userCoords = [lat, lng];

              if (self.userLocationMarker) {
                self.map.removeLayer(self.userLocationMarker);
              }

              var pulseHtml =
                '<div class="carte-user-location-marker">' +
                  '<div class="carte-user-location-pulse"></div>' +
                  '<div class="carte-user-location-center"></div>' +
                '</div>';

              var userIcon = L.divIcon({
                html: pulseHtml,
                className: 'carte-user-icon',
                iconSize: [24, 24],
                iconAnchor: [12, 12],
              });

              self.userLocationMarker = L.marker([lat, lng], { icon: userIcon })
                .bindPopup('<div class="text-xs font-bold p-1">📍 Votre position actuelle</div>')
                .addTo(self.map);

              self.calculateDistances();
              self.filterAndRenderMarkers(false);
              self.map.flyTo([lat, lng], 12, { duration: 1.2 });
              self.triggerToast('Position GPS détectée !');
            },
            function (err) {
              console.warn('[PyVolley Carte] Erreur de géolocalisation:', err.message);
              self.triggerToast('Impossible d’obtenir votre position GPS.');
            },
            { enableHighAccuracy: true, timeout: 8000 }
          );
        },

        // ── Copier le Lien de Partage ────────────────────────
        copyShareLink() {
          var url = window.location.href;
          var self = this;
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(url).then(function () {
              self.triggerToast('Lien de la carte copié dans le presse-papier !');
            }).catch(function () {
              self.fallbackCopyText(url);
            });
          } else {
            self.fallbackCopyText(url);
          }
        },

        fallbackCopyText(text) {
          var input = document.createElement('textarea');
          input.value = text;
          document.body.appendChild(input);
          input.select();
          document.execCommand('copy');
          document.body.removeChild(input);
          this.triggerToast('Lien copié dans le presse-papier !');
        },

        triggerToast(msg) {
          this.toastMessage = msg;
          this.showToast = true;
          clearTimeout(this.toastTimer);
          var self = this;
          this.toastTimer = setTimeout(function () {
            self.showToast = false;
          }, 2800);
        },

        // ── Plein Écran ──────────────────────────────────────
        toggleFullscreen() {
          var container = this.$refs.carteContainer;
          if (!container) return;

          this.isFullscreen = !this.isFullscreen;
          container.classList.toggle('is-fullscreen', this.isFullscreen);

          var self = this;
          setTimeout(function () {
            if (self.map) {
              self.map.invalidateSize();
            }
          }, 150);
        },

        // ── Réinitialisation des Filtres ─────────────────────
        resetFilters() {
          this.entityType = 'club';
          this.selectedZone = 'metropole';
          this.ligue = '';
          this.departement = '';
          this.competitionId = null;
          this.clubId = null;
          this.searchQuery = '';
          this.sortByDistance = false;
          this.filterByVisibleBounds = false;
          this.selectedPoint = null;
          if (this.activePinLayer) {
            this.activePinLayer.clearLayers();
          }
          var zone = GEO_ZONES.metropole;
          if (this.map) {
            this.map.setMinZoom(zone.minZoom || 5);
            this.map.setMaxBounds(zone.bounds);
          }
          this.loadLocations(false);
          this.recenter();
          this.triggerToast('Filtres réinitialisés.');
        },

        // ── Mise à Jour de l'URL (Deep Linking) ──────────────
        updateUrl() {
          var p = new URLSearchParams();
          if (this.entityType)    p.set('entity_type', this.entityType);
          if (this.selectedZone && this.selectedZone !== 'metropole') {
            p.set('zone', this.selectedZone);
          }
          if (this.ligue)         p.set('ligue', this.ligue);
          if (this.departement)   p.set('departement', this.departement);
          if (this.competitionId) p.set('competition_id', this.competitionId);
          if (this.clubId)        p.set('club_id', this.clubId);
          if (this.searchQuery)   p.set('q', this.searchQuery);

          var newSearch = p.toString();
          var newUrl = window.location.pathname + (newSearch ? '?' + newSearch : '');
          window.history.replaceState({}, '', newUrl);
        },

        // ── Événements Fenêtre ───────────────────────────────
        setupEvents() {
          var self = this;
          window.addEventListener('resize', function () {
            if (self.map) self.map.invalidateSize();
          });
        },
      };
    });
  });
})();
