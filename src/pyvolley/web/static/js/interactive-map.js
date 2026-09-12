/**
 * PyVolley — Interactive Map Component (Modern Sports Edition)
 *
 * Reusable Leaflet-based map with marker clustering, custom volleyball SVG pins,
 * rich sports card popups, fullscreen toggle, in-map search, and responsive sizing.
 *
 * Uses Alpine.js for reactivity and fetches data from /api/map/locations.
 */

(function () {
  'use strict';

  // ══════════════════════════════════════════════════════════════
  // Marker Color & SVG Icon Palettes
  // ══════════════════════════════════════════════════════════════

  const ICON_COLORS = {
    blue:   { bg: '#2563eb', border: '#1d4ed8', glow: 'rgba(37,99,235,0.4)' },
    cyan:   { bg: '#0891b2', border: '#0e7490', glow: 'rgba(8,145,178,0.4)' },
    green:  { bg: '#16a34a', border: '#15803d', glow: 'rgba(22,163,74,0.4)' },
    red:    { bg: '#dc2626', border: '#b91c1c', glow: 'rgba(220,38,38,0.4)' },
    gold:   { bg: '#d97706', border: '#b45309', glow: 'rgba(217,119,6,0.4)' },
    purple: { bg: '#9333ea', border: '#7e22ce', glow: 'rgba(147,51,234,0.4)' },
  };

  /**
   * Internal icon SVG paths
   */
  const SVG_SYMBOLS = {
    // Shield icon for clubs
    club: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" fill="white" transform="translate(4, 5) scale(0.66)"/>',
    // Building / Stadium icon for venues
    salle: '<path d="M3 21h18M5 21V7l8-4v18M19 21V11l-6-3M9 9v.01M9 12v.01M9 15v.01M9 18v.01" stroke="white" stroke-width="1.8" stroke-linecap="round" fill="none" transform="translate(4, 4) scale(0.66)"/>',
    // Volleyball ball icon for matches
    volleyball: '<circle cx="12" cy="12" r="9" stroke="white" stroke-width="1.6" fill="none" transform="translate(2, 2) scale(0.83)"/><path d="M12 4.5a9 9 0 0 1 7.8 4.5M12 4.5a9 9 0 0 0-7.8 4.5M12 4.5v15M4.2 9a9 9 0 0 0 15.6 0M4.2 15a9 9 0 0 1 15.6 0" stroke="white" stroke-width="1.3" fill="none" transform="translate(2, 2) scale(0.83)"/>',
    // Default dot
    dot: '<circle cx="12" cy="12" r="5" fill="white"/>',
  };

  /**
   * Generate an SVG Marker Icon for Leaflet
   */
  function createMarkerIcon(iconType, colorKey, isSelected) {
    var c = ICON_COLORS[colorKey] || ICON_COLORS.blue;
    var symbolHtml = SVG_SYMBOLS.dot;

    if (iconType === 'club') {
      symbolHtml = SVG_SYMBOLS.club;
    } else if (iconType === 'salle') {
      symbolHtml = SVG_SYMBOLS.salle;
    } else if (iconType && iconType.startsWith('match')) {
      symbolHtml = SVG_SYMBOLS.volleyball;
    }

    var scale = isSelected ? 'scale(1.32)' : 'scale(1)';
    var strokeWidth = isSelected ? '2.5' : '1.5';
    var strokeColor = isSelected ? '#ffffff' : c.border;
    var filterGlow = isSelected ? 'filter: drop-shadow(0 0 8px ' + c.glow + ');' : '';

    var svg =
      '<svg class="pyvolley-pin" style="transform: ' + scale + '; ' + filterGlow + ' transform-origin: 14px 40px;" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28 40" width="28" height="40">' +
        // Pin body
        '<path d="M14 0C6.3 0 0 6.3 0 14c0 10.5 14 26 14 26s14-15.5 14-26C28 6.3 21.7 0 14 0z" ' +
              'fill="' + c.bg + '" stroke="' + strokeColor + '" stroke-width="' + strokeWidth + '"/>' +
        // Pin center badge
        '<circle cx="14" cy="14" r="9.5" fill="rgba(0,0,0,0.22)"/>' +
        // Pictogram
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
  // Map Tile Layer Providers (Harmonisés)
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
  // Limites Géographiques par Défaut (France Métropolitaine)
  // ══════════════════════════════════════════════════════════════

  const DEFAULT_MAP_BOUNDS = [
    [39.0, -8.5],
    [53.0, 12.5],
  ];

  // ══════════════════════════════════════════════════════════════
  // Alpine.js Component: interactiveMap
  // ══════════════════════════════════════════════════════════════

  document.addEventListener('alpine:init', function () {
    Alpine.data('interactiveMap', function (config) {
      config = config || {};
      return {
        // ── Configuration ────────────────────────────────────
        entityType:    config.entityType    || null,
        clubId:        config.clubId        || null,
        competitionId: config.competitionId || null,
        equipeId:      config.equipeId      || null,
        joueurId:      config.joueurId      || null,
        departement:   config.departements  || config.departement || null,
        height:        config.height        || '420px',
        showFilter:    !!config.showFilter,
        showSearch:    config.showSearch !== false,
        showLegend:    config.showLegend !== false,

        // ── State ────────────────────────────────────────────
        map:                 null,
        tileLayer:           null,
        labelsTileLayer:     null,
        currentTileKey:      'satellite',
        markerLayer:         null,
        activePinLayer:      null,
        allMarkersData:      [],
        markers:             [],
        selectedMarkerData:  null,
        loading:             true,
        error:               false,
        markerCount:         0,
        isFullscreen:        false,
        searchQuery:         '',
        showWheelNotice:     false,
        wheelNoticeTimer:    null,

        // ── Filter state ─────────────────────────────────────
        filterEntityType: config.entityType || '',

        // ── Lifecycle ────────────────────────────────────────
        async init() {
          await this.$nextTick();
          this.initMap();
          await this.loadMarkers();
          this.setupEvents();
        },

        // ── Map Initialisation ───────────────────────────────
        initMap() {
          var container = this.$refs.mapContainer;
          if (!container) return;

          // Scrollwheel zoom disabled by default to prevent scroll hijacking
          this.map = L.map(container, {
            center: [46.6, 2.3],
            zoom: 6,
            minZoom: 5,
            maxZoom: 18,
            maxBounds: DEFAULT_MAP_BOUNDS,
            maxBoundsViscosity: 0.85,
            scrollWheelZoom: false,
            zoomControl: true,
          });

          // Set default tile layer (Satellite Hybride)
          this.setTileLayer('satellite');

          // Calque dédié pour l'ancrage stable du pin/halo actif (sub-pixel)
          this.activePinLayer = L.layerGroup().addTo(this.map);

          // MarkerCluster group
          if (typeof L.markerClusterGroup === 'function') {
            this.markerLayer = L.markerClusterGroup({
              maxClusterRadius: 45,
              spiderfyOnMaxZoom: true,
              showCoverageOnHover: false,
              zoomToBoundsOnClick: true,
              iconCreateFunction: function (cluster) {
                var count = cluster.getChildCount();
                var size = count < 10 ? 'small' : count < 40 ? 'medium' : 'large';
                return L.divIcon({
                  html: '<div class="pyvolley-cluster pyvolley-cluster-' + size + '">' + count + '</div>',
                  className: 'pyvolley-cluster-icon',
                  iconSize: L.point(44, 44),
                });
              },
            });
          } else {
            this.markerLayer = L.layerGroup();
          }

          this.markerLayer.addTo(this.map);
          L.control.scale({ imperial: false, metric: true, position: 'bottomleft' }).addTo(this.map);

          // Handle smart scroll wheel behavior:
          // If user scrolls without Ctrl, show polite guidance notice
          var self = this;
          container.addEventListener('wheel', function (e) {
            if (!self.map.scrollWheelZoom.enabled()) {
              if (e.ctrlKey || e.metaKey) {
                self.map.scrollWheelZoom.enable();
              } else {
                self.triggerWheelNotice();
              }
            }
          }, { passive: true });

          // Enable wheel zoom on direct map click
          this.map.on('click', function () {
            self.map.scrollWheelZoom.enable();
          });
        },

        // ── Tile Layer Switcher ──────────────────────────────
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

          if (conf.labelsUrl) {
            this.labelsTileLayer = L.tileLayer(conf.labelsUrl, {
              pane: 'shadowPane',
              maxZoom: conf.maxZoom,
              opacity: 0.95,
            }).addTo(this.map);
          }

          this.currentTileKey = key;
        },

        toggleTileLayer() {
          var next = this.currentTileKey === 'satellite' ? 'osm' : 'satellite';
          this.setTileLayer(next);
        },

        // ── Observers & Tab Switch Listeners ──────────────────
        setupEvents() {
          var container = this.$refs.mapContainer;
          if (!container) return;
          var self = this;

          // 1. IntersectionObserver for hidden tabs (Alpine activeTab switches)
          if (typeof IntersectionObserver !== 'undefined') {
            var observer = new IntersectionObserver(function (entries) {
              entries.forEach(function (entry) {
                if (entry.isIntersecting && self.map) {
                  setTimeout(function () {
                    try {
                      self.map.invalidateSize();
                      self.recenter();
                    } catch (e) {}
                  }, 80);
                }
              });
            }, { threshold: 0.05 });
            observer.observe(container);
            this._visibilityObserver = observer;
          }

          // 2. Global window resize & custom tab-change events
          window.addEventListener('resize', function () {
            if (self.map) self.map.invalidateSize();
          });

          document.addEventListener('tab-change', function () {
            if (self.map) {
              setTimeout(function () {
                self.map.invalidateSize();
                self.recenter();
              }, 100);
            }
          });
        },

        // ── Data Loading (Toutes saisons confondues) ──────────
        async loadMarkers() {
          this.loading = true;
          this.error = false;
          this.selectedMarkerData = null;
          if (this.activePinLayer) {
            this.activePinLayer.clearLayers();
          }

          try {
            var params = new URLSearchParams();
            var entityType = this.filterEntityType || this.entityType;
            if (entityType)         params.set('entity_type', entityType);
            if (this.clubId)        params.set('club_id', this.clubId);
            if (this.competitionId) params.set('competition_id', this.competitionId);
            if (this.equipeId)      params.set('equipe_id', this.equipeId);
            if (this.joueurId)      params.set('joueur_id', this.joueurId);
            if (this.departement)   params.set('departement', this.departement);

            var url = '/api/map/locations?' + params.toString();
            var resp = await fetch(url);
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            var data = await resp.json();

            this.allMarkersData = data.markers || [];
            this.filterAndRenderMarkers();

            // Set initial position
            if (this.allMarkersData.length === 1) {
              this.map.setView([this.allMarkersData[0].lat, this.allMarkersData[0].lng], 13);
            } else if (this.allMarkersData.length === 0) {
              this.map.setView([data.center_lat || 46.6, data.center_lng || 2.3], data.zoom || 6);
            }
          } catch (e) {
            console.error('[PyVolley] Map data load failed:', e);
            this.error = true;
          } finally {
            this.loading = false;
          }
        },

        // ── In-Map Client-Side Search & Render (Recherche Intelligente) ──
        filterAndRenderMarkers() {
          var rawQuery = (this.searchQuery || '').trim();
          var query = normalizeStr(rawQuery);
          var filtered = this.allMarkersData;

          if (query) {
            var depMatch = query.match(/(?:dep|dep\.|departement|dép|dép\.)\s*([0-9]{1,3}|2a|2b)/i);
            var queryDepCode = depMatch ? depMatch[1].padStart(2, '0').toUpperCase() : null;

            filtered = this.allMarkersData.filter(function (m) {
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

          this.renderMarkers(filtered);
          this.markerCount = filtered.length;
        },

        renderMarkers(markersData) {
          this.markerLayer.clearLayers();
          this.markers = [];
          var self = this;
          var markersToBatch = [];

          for (var i = 0; i < markersData.length; i++) {
            var m = markersData[i];
            var isSel = self.selectedMarkerData &&
                        self.selectedMarkerData.entity_type === m.entity_type &&
                        self.selectedMarkerData.entity_id === m.entity_id;

            var icon = createMarkerIcon(m.icon_type || m.entity_type, m.icon_color || 'blue', isSel);
            var marker = L.marker([m.lat, m.lng], { icon: icon });

            marker.bindPopup(m.popup_html, {
              maxWidth: 320,
              className: 'pyvolley-popup',
            });

            (function (markerData, markerInstance) {
              markerInstance.on('click', function () {
                self.selectMarker(markerData, markerInstance);
              });
              markerInstance.on('popupclose', function () {
                if (self.selectedMarkerData &&
                    self.selectedMarkerData.entity_type === markerData.entity_type &&
                    self.selectedMarkerData.entity_id === markerData.entity_id) {
                  self.selectedMarkerData = null;
                  if (self.activePinLayer) {
                    self.activePinLayer.clearLayers();
                  }
                }
              });
            })(m, marker);

            markersToBatch.push(marker);
            this.markers.push(marker);
          }

          if (typeof this.markerLayer.addLayers === 'function') {
            this.markerLayer.addLayers(markersToBatch);
          } else {
            for (var j = 0; j < markersToBatch.length; j++) {
              this.markerLayer.addLayer(markersToBatch[j]);
            }
          }

          // Adaptation des limites si des marqueurs se trouvent en outre-mer
          if (markersData.length > 0) {
            var validCoords = [];
            var hasOverseas = false;
            for (var k = 0; k < markersData.length; k++) {
              var p = markersData[k];
              if (p.lat != null && p.lng != null) {
                validCoords.push([p.lat, p.lng]);
                if (p.lat < 39.0 || p.lat > 53.0 || p.lng < -8.5 || p.lng > 12.5) {
                  hasOverseas = true;
                }
              }
            }
            if (hasOverseas && validCoords.length > 0) {
              var b = L.latLngBounds(validCoords).pad(0.6);
              this.map.setMinZoom(4);
              this.map.setMaxBounds(b);
            } else {
              this.map.setMinZoom(5);
              this.map.setMaxBounds(DEFAULT_MAP_BOUNDS);
            }
          }

          // Cadrage automatique sans écrasement
          if (this.markers.length > 1) {
            var group = L.featureGroup(this.markers);
            this.map.fitBounds(group.getBounds().pad(0.12), { animate: false });
          } else if (this.markers.length === 1) {
            this.map.setView([markersData[0].lat, markersData[0].lng], 12);
          }
        },

        // ── Sélection d'un Marqueur (Halo Natif Sub-pixel Stable) ───────
        selectMarker(point, marker) {
          if (!point) return;
          this.selectedMarkerData = point;
          if (!this.map) return;

          if (this.activePinLayer) {
            this.activePinLayer.clearLayers();
          }

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

          if (marker) {
            if (this.markerLayer && typeof this.markerLayer.zoomToShowLayer === 'function') {
              this.markerLayer.zoomToShowLayer(marker, function () {
                marker.openPopup();
              });
            } else {
              marker.openPopup();
            }
          }
        },

        // ── Actions ──────────────────────────────────────────
        recenter() {
          if (!this.map) return;
          if (this.markers.length > 1) {
            var group = L.featureGroup(this.markers);
            this.map.fitBounds(group.getBounds().pad(0.12));
          } else if (this.markers.length === 1) {
            this.map.setView(this.markers[0].getLatLng(), 13);
          } else {
            this.map.setMinZoom(5);
            this.map.setMaxBounds(DEFAULT_MAP_BOUNDS);
            this.map.setView([46.6, 2.3], 6);
          }
        },

        toggleFullscreen() {
          var wrapper = this.$refs.mapWrapper;
          if (!wrapper) return;

          this.isFullscreen = !this.isFullscreen;
          wrapper.classList.toggle('is-fullscreen', this.isFullscreen);

          var self = this;
          setTimeout(function () {
            if (self.map) {
              self.map.invalidateSize();
              self.recenter();
            }
          }, 100);
        },

        triggerWheelNotice() {
          this.showWheelNotice = true;
          clearTimeout(this.wheelNoticeTimer);
          var self = this;
          this.wheelNoticeTimer = setTimeout(function () {
            self.showWheelNotice = false;
          }, 1800);
        },

        async applyFilter() {
          await this.loadMarkers();
        },

        // ── Cleanup ──────────────────────────────────────────
        destroy() {
          if (this._visibilityObserver) {
            this._visibilityObserver.disconnect();
          }
          if (this.map) {
            this.map.remove();
            this.map = null;
          }
        },
      };
    });
  });
})();
