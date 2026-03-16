/**
 * PyVolley — Interactive Map Component
 *
 * Reusable Leaflet-based map with marker clustering for visualising
 * clubs, venues, matches and competitions on an interactive map.
 *
 * Uses Alpine.js for reactivity and fetches data from /api/map/locations.
 *
 * Usage in template:
 *   <div x-data="interactiveMap({
 *       entityType: 'club',
 *       clubId: 42,
 *       height: '400px'
 *   })">
 *     <div x-ref="mapContainer" :style="'height:' + height"></div>
 *   </div>
 */

(function () {
  'use strict';

  // ══════════════════════════════════════════════════════════════
  // Marker icon colours (matching the project's Volley palette)
  // ══════════════════════════════════════════════════════════════

  const ICON_COLORS = {
    blue:   { bg: '#3b82f6', border: '#2563eb' },
    cyan:   { bg: '#06b6d4', border: '#0891b2' },
    gold:   { bg: '#f59e0b', border: '#d97706' },
    green:  { bg: '#22c55e', border: '#16a34a' },
    red:    { bg: '#ef4444', border: '#dc2626' },
    purple: { bg: '#a855f7', border: '#9333ea' },
  };

  /**
   * Create a coloured SVG marker icon for Leaflet.
   */
  function createMarkerIcon(color) {
    var c = ICON_COLORS[color] || ICON_COLORS.blue;
    var svg =
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 36" width="24" height="36">' +
        '<path d="M12 0C5.4 0 0 5.4 0 12c0 9 12 24 12 24s12-15 12-24C24 5.4 18.6 0 12 0z" ' +
              'fill="' + c.bg + '" stroke="' + c.border + '" stroke-width="1.5"/>' +
        '<circle cx="12" cy="12" r="5" fill="white" opacity="0.9"/>' +
      '</svg>';
    return L.divIcon({
      html: svg,
      className: 'pyvolley-marker-icon',
      iconSize: [24, 36],
      iconAnchor: [12, 36],
      popupAnchor: [0, -34],
    });
  }

  // ══════════════════════════════════════════════════════════════
  // Alpine.js component: interactiveMap
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
        departement:   config.departement   || null,
        height:        config.height        || '400px',

        // ── State ────────────────────────────────────────────
        map:           null,
        markerLayer:   null,
        markers:       [],
        loading:       true,
        error:         false,
        markerCount:   0,

        // ── Filter state ─────────────────────────────────────
        filterEntityType: config.entityType || '',

        // ── Lifecycle ────────────────────────────────────────
        async init() {
          await this.$nextTick();
          this.initMap();
          await this.loadMarkers();
        },

        // ── Map Initialisation ───────────────────────────────
        initMap() {
          var container = this.$refs.mapContainer;
          if (!container) return;

          this.map = L.map(container, {
            center: [46.6, 2.3],
            zoom: 6,
            scrollWheelZoom: true,
            zoomControl: true,
          });

          // Dark-themed tile layer (matches the project's dark UI)
          L.tileLayer(
            'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
            {
              attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> ' +
                           '&copy; <a href="https://carto.com/">CARTO</a>',
              subdomains: 'abcd',
              maxZoom: 19,
            }
          ).addTo(this.map);

          // MarkerCluster group
          if (typeof L.markerClusterGroup === 'function') {
            this.markerLayer = L.markerClusterGroup({
              maxClusterRadius: 50,
              spiderfyOnMaxZoom: true,
              showCoverageOnHover: false,
              iconCreateFunction: function (cluster) {
                var count = cluster.getChildCount();
                var size = count < 10 ? 'small' : count < 50 ? 'medium' : 'large';
                return L.divIcon({
                  html: '<div class="pyvolley-cluster pyvolley-cluster-' + size + '">' + count + '</div>',
                  className: 'pyvolley-cluster-icon',
                  iconSize: L.point(40, 40),
                });
              },
            });
          } else {
            this.markerLayer = L.layerGroup();
          }

          this.markerLayer.addTo(this.map);
        },

        // ── Data Loading ─────────────────────────────────────
        async loadMarkers() {
          this.loading = true;
          this.error = false;

          try {
            var params = new URLSearchParams();
            var entityType = this.filterEntityType || this.entityType;
            if (entityType)       params.set('entity_type', entityType);
            if (this.clubId)      params.set('club_id', this.clubId);
            if (this.competitionId) params.set('competition_id', this.competitionId);
            if (this.equipeId)    params.set('equipe_id', this.equipeId);
            if (this.joueurId)    params.set('joueur_id', this.joueurId);
            if (this.saisonId)    params.set('saison_id', this.saisonId);
            if (this.departement) params.set('departement', this.departement);

            var url = '/api/map/locations?' + params.toString();
            var resp = await fetch(url);
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            var data = await resp.json();

            this.renderMarkers(data.markers);
            this.markerCount = data.markers.length;

            if (data.markers.length > 0) {
              this.map.setView([data.center_lat, data.center_lng], data.zoom);
            }
          } catch (e) {
            console.error('[PyVolley] Map data load failed:', e);
            this.error = true;
          } finally {
            this.loading = false;
          }
        },

        // ── Render Markers ───────────────────────────────────
        renderMarkers(markersData) {
          this.markerLayer.clearLayers();
          this.markers = [];

          for (var i = 0; i < markersData.length; i++) {
            var m = markersData[i];
            var icon = createMarkerIcon(m.icon_color);
            var marker = L.marker([m.lat, m.lng], { icon: icon });
            marker.bindPopup(m.popup_html, {
              maxWidth: 280,
              className: 'pyvolley-popup',
            });
            this.markerLayer.addLayer(marker);
            this.markers.push(marker);
          }

          // Fit bounds if multiple markers
          if (this.markers.length > 1) {
            var group = L.featureGroup(this.markers);
            this.map.fitBounds(group.getBounds().pad(0.1));
          }
        },

        // ── Filter Change ────────────────────────────────────
        async applyFilter() {
          await this.loadMarkers();
        },

        // ── Cleanup ──────────────────────────────────────────
        destroy() {
          if (this.map) {
            this.map.remove();
            this.map = null;
          }
        },
      };
    });
  });
})();
