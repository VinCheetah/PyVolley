/**
 * PyVolley — Hub Carte Interactive (Modern Sports Edition)
 *
 * Contrôleur Alpine.js pour la vue cartographique dédiée /carte.
 * Initialisé par défaut sur la France métropolitaine en vue Satellite.
 * Affiche uniquement les clubs par défaut, avec navigation rapide par zones
 * géographiques (Métropole, Corse, Guyane, Antilles, Réunion, Mayotte).
 */

(function () {
  'use strict';

  // ══════════════════════════════════════════════════════════════
  // Zones Géographiques Prédéfinies
  // ══════════════════════════════════════════════════════════════

  const GEO_ZONES = {
    metropole:  { name: 'France métropolitaine', center: [46.6, 2.3], zoom: 6 },
    corse:      { name: 'Corse', center: [42.15, 9.15], zoom: 9 },
    guadeloupe: { name: 'Guadeloupe', center: [16.25, -61.55], zoom: 10 },
    martinique: { name: 'Martinique', center: [14.64, -61.02], zoom: 10 },
    guyane:     { name: 'Guyane', center: [4.4, -53.12], zoom: 8 },
    reunion:    { name: 'La Réunion', center: [-21.11, 55.53], zoom: 10 },
    mayotte:    { name: 'Mayotte', center: [-12.82, 45.16], zoom: 11 },
  };

  // ══════════════════════════════════════════════════════════════
  // Palettes de Couleurs & Icônes SVG
  // ══════════════════════════════════════════════════════════════

  const ICON_COLORS = {
    blue:   { bg: '#2563eb', border: '#1d4ed8', glow: 'rgba(37,99,235,0.4)' },
    cyan:   { bg: '#0891b2', border: '#0e7490', glow: 'rgba(8,145,178,0.4)' },
    green:  { bg: '#16a34a', border: '#15803d', glow: 'rgba(22,163,74,0.4)' },
    red:    { bg: '#dc2626', border: '#b91c1c', glow: 'rgba(220,38,38,0.4)' },
    gold:   { bg: '#d97706', border: '#b45309', glow: 'rgba(217,119,6,0.4)' },
    purple: { bg: '#9333ea', border: '#7e22ce', glow: 'rgba(147,51,234,0.4)' },
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

    var scale = isSelected ? 'scale(1.28)' : 'scale(1)';
    var strokeWidth = isSelected ? '2.5' : '1.5';
    var strokeColor = isSelected ? '#ffffff' : c.border;

    var svg =
      '<svg class="pyvolley-pin" style="transform: ' + scale + ';" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28 40" width="28" height="40">' +
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
      popupAnchor: [0, -38],
    });
  }

  // ══════════════════════════════════════════════════════════════
  // Fournisseurs de Fonds de Carte (Tile Layers)
  // ══════════════════════════════════════════════════════════════

  const TILE_LAYERS = {
    satellite: {
      name: 'Satellite (Esri Imagery)',
      icon: 'globe',
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      attrib: 'Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community',
      subdomains: '',
      maxZoom: 18,
    },
    dark: {
      name: 'Sombre (Dark Matter)',
      icon: 'moon',
      url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
      attrib: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19,
    },
    voyager: {
      name: 'Clair (Voyager)',
      icon: 'sun',
      url: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
      attrib: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19,
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
        // ── Filtres ──────────────────────────────────────────
        // Clubs par défaut uniquement
        entityType:     (initialConfig.entityType && initialConfig.entityType !== 'match') ? initialConfig.entityType : 'club',
        selectedZone:   initialConfig.selectedZone || 'metropole',
        saisonId:       initialConfig.saisonId ? parseInt(initialConfig.saisonId, 10) : null,
        ligue:          initialConfig.ligue || '',
        departement:    initialConfig.departement || '',
        competitionId:  initialConfig.competitionId ? parseInt(initialConfig.competitionId, 10) : null,
        clubId:         initialConfig.clubId ? parseInt(initialConfig.clubId, 10) : null,
        searchQuery:    initialConfig.searchQuery || '',

        // ── États d'Affichage & Cartographie ─────────────────
        map:                 null,
        tileLayer:           null,
        currentTileKey:      'satellite', // Vue satellite par défaut
        clusteringEnabled:   true,
        markerGroup:         null,
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

          // Vue initiale calée sur la France métropolitaine à la bonne taille
          var initialZone = GEO_ZONES[this.selectedZone] || GEO_ZONES.metropole;

          this.map = L.map(container, {
            center: initialZone.center,
            zoom: initialZone.zoom,
            scrollWheelZoom: true,
            zoomControl: false,
          });

          L.control.zoom({ position: 'bottomleft' }).addTo(this.map);

          // Vue par défaut Satellite
          this.setTileLayer('satellite');
          this.initMarkerLayer();

          var self = this;
          this.map.on('click', function () {
            self.showLayersMenu = false;
          });
        },

        initMarkerLayer() {
          if (this.markerGroup) {
            this.map.removeLayer(this.markerGroup);
          }

          if (this.clusteringEnabled && typeof L.markerClusterGroup === 'function') {
            this.markerGroup = L.markerClusterGroup({
              maxClusterRadius: 40,
              spiderfyOnMaxZoom: true,
              showCoverageOnHover: false,
              zoomToBoundsOnClick: true,
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
          }
          var conf = TILE_LAYERS[key];
          this.tileLayer = L.tileLayer(conf.url, {
            attribution: conf.attrib,
            subdomains: conf.subdomains,
            maxZoom: conf.maxZoom,
          }).addTo(this.map);
          this.currentTileKey = key;
          this.showLayersMenu = false;
        },

        // ── Navigation Rapide par Zone Géographique ───────────
        goToZone(zoneKey) {
          this.selectedZone = zoneKey || 'metropole';
          var zone = GEO_ZONES[this.selectedZone] || GEO_ZONES.metropole;
          if (this.map) {
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

        // ── Chargement des Données depuis l'API ──────────────
        async loadLocations() {
          this.loading = true;
          this.error = false;
          this.selectedPoint = null;

          try {
            var params = new URLSearchParams();
            // Toujours filtrer sur l'entité choisie (club par défaut, jamais match)
            if (this.entityType && this.entityType !== 'all') {
              params.set('entity_type', this.entityType);
            }
            if (this.saisonId)      params.set('saison_id', this.saisonId);
            if (this.ligue)         params.set('ligue', this.ligue);
            if (this.departement)   params.set('departement', this.departement);
            if (this.competitionId) params.set('competition_id', this.competitionId);
            if (this.clubId)        params.set('club_id', this.clubId);
            params.set('limit', '4000');

            var url = '/api/map/locations?' + params.toString();
            var resp = await fetch(url);
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            var data = await resp.json();

            // Filtrer formellement pour exclure tout match
            var rawMarkers = data.markers || [];
            this.allMarkersData = rawMarkers.filter(function (m) {
              return m.entity_type !== 'match';
            });

            this.filterAndRenderMarkers();
            this.updateUrl();

            // Caler la vue initiale sur la zone choisie (France métropolitaine par défaut)
            var zone = GEO_ZONES[this.selectedZone] || GEO_ZONES.metropole;
            this.map.setView(zone.center, zone.zoom);
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

        // ── Filtrage Côté Client (Recherche Instantanée) ─────
        filterAndRenderMarkers() {
          var query = (this.searchQuery || '').trim().toLowerCase();
          var filtered = this.allMarkersData;

          if (query) {
            filtered = this.allMarkersData.filter(function (m) {
              var matchLabel = m.label && m.label.toLowerCase().includes(query);
              var matchSub = m.sublabel && m.sublabel.toLowerCase().includes(query);
              return matchLabel || matchSub;
            });
          }

          this.displayedMarkers = filtered;
          this.renderMarkers(filtered);
          this.updateCounts(filtered);
        },

        renderMarkers(markersData) {
          this.markerGroup.clearLayers();
          this.markerInstances.clear();

          var self = this;

          for (var i = 0; i < markersData.length; i++) {
            var m = markersData[i];
            var icon = createMarkerIcon(m.icon_type || m.entity_type, m.icon_color || 'blue', false);
            var marker = L.marker([m.lat, m.lng], { icon: icon });

            marker.bindPopup(m.popup_html, {
              maxWidth: 320,
              className: 'pyvolley-popup',
            });

            // Événement clic marqueur
            (function (markerData, markerInstance) {
              markerInstance.on('click', function () {
                self.selectedPoint = markerData;
                self.ensurePointVisibleInDrawer(markerData);
              });
            })(m, marker);

            this.markerGroup.addLayer(marker);
            var key = m.entity_type + '_' + m.entity_id;
            this.markerInstances.set(key, marker);
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

        // ── Clic sur un Point dans la Liste (Drawer) ─────────
        selectPoint(point) {
          this.selectedPoint = point;
          if (!this.map) return;

          // Vol fluide vers le point
          this.map.flyTo([point.lat, point.lng], Math.max(this.map.getZoom(), 14), {
            duration: 0.8,
            easeLinearity: 0.25,
          });

          // Ouvrir la popup
          var key = point.entity_type + '_' + point.entity_id;
          var marker = this.markerInstances.get(key);
          if (marker) {
            setTimeout(function () {
              marker.openPopup();
            }, 400);
          }
        },

        ensurePointVisibleInDrawer(point) {
          var card = document.getElementById('drawer-item-' + point.entity_type + '-' + point.entity_id);
          if (card) {
            card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          }
        },

        // ── Changement de Filtre Type ────────────────────────
        setEntityType(type) {
          this.entityType = type;
          this.loadLocations();
        },

        // ── Recentrage sur la Zone Active ─────────────────────
        recenter() {
          if (!this.map) return;
          var zone = GEO_ZONES[this.selectedZone] || GEO_ZONES.metropole;
          this.map.flyTo(zone.center, zone.zoom, { duration: 0.8 });
        },

        // ── Géolocalisation Utilisateur ──────────────────────
        locateUser() {
          if (!navigator.geolocation) {
            alert('La géolocalisation n’est pas supportée par votre navigateur.');
            return;
          }

          var self = this;
          navigator.geolocation.getCurrentPosition(
            function (position) {
              var lat = position.coords.latitude;
              var lng = position.coords.longitude;

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

              self.map.flyTo([lat, lng], 12, { duration: 1.2 });
            },
            function (err) {
              console.warn('[PyVolley Carte] Erreur de géolocalisation:', err.message);
              alert('Impossible d’obtenir votre position : ' + err.message);
            },
            { enableHighAccuracy: true, timeout: 8000 }
          );
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
          this.loadLocations();
        },

        // ── Mise à Jour de l'URL (Deep Linking) ──────────────
        updateUrl() {
          var p = new URLSearchParams();
          if (this.entityType)    p.set('entity_type', this.entityType);
          if (this.selectedZone && this.selectedZone !== 'metropole') {
            p.set('zone', this.selectedZone);
          }
          if (this.saisonId)      p.set('saison_id', this.saisonId);
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
