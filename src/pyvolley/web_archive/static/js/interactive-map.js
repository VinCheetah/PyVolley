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
  function createMarkerIcon(iconType, colorKey) {
    var c = ICON_COLORS[colorKey] || ICON_COLORS.blue;
    var symbolHtml = SVG_SYMBOLS.dot;

    if (iconType === 'club') {
      symbolHtml = SVG_SYMBOLS.club;
    } else if (iconType === 'salle') {
      symbolHtml = SVG_SYMBOLS.salle;
    } else if (iconType && iconType.startsWith('match')) {
      symbolHtml = SVG_SYMBOLS.volleyball;
    }

    var svg =
      '<svg class="pyvolley-pin" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28 40" width="28" height="40">' +
        // Pin body
        '<path d="M14 0C6.3 0 0 6.3 0 14c0 10.5 14 26 14 26s14-15.5 14-26C28 6.3 21.7 0 14 0z" ' +
              'fill="' + c.bg + '" stroke="' + c.border + '" stroke-width="1.5"/>' +
        // Pin center badge
        '<circle cx="14" cy="14" r="9.5" fill="rgba(0,0,0,0.22)"/>' +
        // Pictogram
        '<g transform="translate(2, 2)">' + symbolHtml + '</g>' +
      '</svg>';

    return L.divIcon({
      html: svg,
      className: 'pyvolley-marker-icon',
      iconSize: [28, 40],
      iconAnchor: [14, 40],
      popupAnchor: [0, -38],
    });
  }

  // ══════════════════════════════════════════════════════════════
  // Map Tile Layer Providers
  // ══════════════════════════════════════════════════════════════

  const TILE_LAYERS = {
    dark: {
      url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
      attrib: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19,
    },
    light: {
      url: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
      attrib: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19,
    },
    osm: {
      url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      attrib: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      subdomains: 'abc',
      maxZoom: 19,
    },
  };

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
        saisonId:      config.saisonId      || null,
        departement:   config.departements  || config.departement || null,
        height:        config.height        || '420px',
        showFilter:    !!config.showFilter,
        showSearch:    config.showSearch !== false,
        showLegend:    config.showLegend !== false,

        // ── State ────────────────────────────────────────────
        map:             null,
        tileLayer:       null,
        currentTileKey:  'dark',
        markerLayer:     null,
        allMarkersData:  [],
        markers:         [],
        loading:         true,
        error:           false,
        markerCount:     0,
        isFullscreen:    false,
        searchQuery:     '',
        showWheelNotice: false,
        wheelNoticeTimer: null,

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
            scrollWheelZoom: false,
            zoomControl: true,
          });

          // Set default tile layer
          this.setTileLayer('dark');

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
          if (!TILE_LAYERS[key]) key = 'dark';
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
        },

        toggleTileLayer() {
          var next = this.currentTileKey === 'dark' ? 'light' : this.currentTileKey === 'light' ? 'osm' : 'dark';
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

        // ── Data Loading ─────────────────────────────────────
        async loadMarkers() {
          this.loading = true;
          this.error = false;

          try {
            var params = new URLSearchParams();
            var entityType = this.filterEntityType || this.entityType;
            if (entityType)         params.set('entity_type', entityType);
            if (this.clubId)        params.set('club_id', this.clubId);
            if (this.competitionId) params.set('competition_id', this.competitionId);
            if (this.equipeId)      params.set('equipe_id', this.equipeId);
            if (this.joueurId)      params.set('joueur_id', this.joueurId);
            if (this.saisonId)      params.set('saison_id', this.saisonId);
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

        // ── In-Map Client-Side Search & Render ─────────────────
        filterAndRenderMarkers() {
          var query = (this.searchQuery || '').trim().toLowerCase();
          var filtered = this.allMarkersData;

          if (query) {
            filtered = this.allMarkersData.filter(function (m) {
              return (
                (m.label && m.label.toLowerCase().includes(query)) ||
                (m.sublabel && m.sublabel.toLowerCase().includes(query))
              );
            });
          }

          this.renderMarkers(filtered);
          this.markerCount = filtered.length;
        },

        renderMarkers(markersData) {
          this.markerLayer.clearLayers();
          this.markers = [];

          for (var i = 0; i < markersData.length; i++) {
            var m = markersData[i];
            var icon = createMarkerIcon(m.icon_type || m.entity_type, m.icon_color || 'blue');
            var marker = L.marker([m.lat, m.lng], { icon: icon });

            marker.bindPopup(m.popup_html, {
              maxWidth: 320,
              className: 'pyvolley-popup',
            });

            this.markerLayer.addLayer(marker);
            this.markers.push(marker);
          }

          // Cadrage automatique sans écrasement
          if (this.markers.length > 1) {
            var group = L.featureGroup(this.markers);
            this.map.fitBounds(group.getBounds().pad(0.12), { animate: false });
          } else if (this.markers.length === 1) {
            this.map.setView([markersData[0].lat, markersData[0].lng], 12);
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
