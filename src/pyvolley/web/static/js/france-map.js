/**
 * PyVolley — France Map Geographic Filter
 *
 * Interactive SVG map of France for filtering data by department/region.
 * Uses Alpine.js for reactivity and fetches GeoJSON data from a public CDN.
 *
 * Data source: france-geojson by Grégoire David (public domain, IGN data)
 *   https://github.com/gregoiredavid/france-geojson
 *
 * Usage in template:
 *   <div x-data="geoFilter({ selected: ['38', '69'] })"> ... </div>
 */

(function () {
  'use strict';

  const SVG_NS = 'http://www.w3.org/2000/svg';

  // ══════════════════════════════════════════════════════════════════
  // GeoJSON data sources (public domain, CORS-enabled CDN)
  // ══════════════════════════════════════════════════════════════════

  const GEOJSON_URLS = {
    departments: [
      '/static/data/departements.geojson',
      'https://cdn.jsdelivr.net/gh/gregoiredavid/france-geojson/departements-version-simplifiee.geojson',
      'https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/departements-version-simplifiee.geojson',
    ],
    regions: [
      '/static/data/regions.geojson',
      'https://cdn.jsdelivr.net/gh/gregoiredavid/france-geojson/regions-version-simplifiee.geojson',
      'https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/regions-version-simplifiee.geojson',
    ],
  };

  // ══════════════════════════════════════════════════════════════════
  // Region ↔ Department mapping (metropolitan France, 13 regions)
  // ══════════════════════════════════════════════════════════════════

  const REGIONS = {
    '84': { name: 'Auvergne-Rhône-Alpes',       color: '#1e2d52', depts: ['01','03','07','15','26','38','42','43','63','69','73','74'] },
    '27': { name: 'Bourgogne-Franche-Comté',     color: '#23344a', depts: ['21','25','39','58','70','71','89','90'] },
    '53': { name: 'Bretagne',                    color: '#1a3048', depts: ['22','29','35','56'] },
    '24': { name: 'Centre-Val de Loire',         color: '#253050', depts: ['18','28','36','37','41','45'] },
    '94': { name: 'Corse',                      color: '#20284a', depts: ['2A','2B'] },
    '44': { name: 'Grand Est',                   color: '#1c2b4e', depts: ['08','10','51','52','54','55','57','67','68','88'] },
    '32': { name: 'Hauts-de-France',             color: '#222e50', depts: ['02','59','60','62','80'] },
    '11': { name: 'Île-de-France',               color: '#28354e', depts: ['75','77','78','91','92','93','94','95'] },
    '28': { name: 'Normandie',                   color: '#1e3350', depts: ['14','27','50','61','76'] },
    '75': { name: 'Nouvelle-Aquitaine',          color: '#202c54', depts: ['16','17','19','23','24','33','40','47','64','79','86','87'] },
    '76': { name: 'Occitanie',                   color: '#26304c', depts: ['09','11','12','30','31','32','34','46','48','65','66','81','82'] },
    '52': { name: 'Pays de la Loire',            color: '#1c2e4c', depts: ['44','49','53','72','85'] },
    '93': { name: "Provence-Alpes-Côte d'Azur",  color: '#243152', depts: ['04','05','06','13','83','84'] },
  };

  // Reverse mapping
  const DEPT_TO_REGION = {};
  const METRO_DEPTS = new Set();
  for (const [regionCode, info] of Object.entries(REGIONS)) {
    for (const dept of info.depts) {
      DEPT_TO_REGION[dept] = regionCode;
      METRO_DEPTS.add(dept);
    }
  }

  const REGION_CODES = Object.keys(REGIONS);

  // ══════════════════════════════════════════════════════════════════
  // Projection: WGS84 → SVG coordinates
  // ══════════════════════════════════════════════════════════════════

  function createProjection(svgWidth, svgHeight, padding) {
    padding = padding || 20;
    // Metropolitan France bounds
    const lngMin = -5.5, lngMax = 10;
    const latMin = 41, latMax = 51.5;
    const cosCenter = Math.cos(46.5 * Math.PI / 180);

    const geoWidth = (lngMax - lngMin) * cosCenter;
    const geoHeight = latMax - latMin;
    const usableW = svgWidth - 2 * padding;
    const usableH = svgHeight - 2 * padding;

    const scale = Math.min(usableW / geoWidth, usableH / geoHeight);
    const mapW = geoWidth * scale;
    const mapH = geoHeight * scale;
    const offsetX = padding + (usableW - mapW) / 2;
    const offsetY = padding + (usableH - mapH) / 2;

    return function (lng, lat) {
      return [
        offsetX + (lng - lngMin) * cosCenter * scale,
        offsetY + (latMax - lat) * scale,
      ];
    };
  }

  // ══════════════════════════════════════════════════════════════════
  // GeoJSON → SVG path conversion
  // ══════════════════════════════════════════════════════════════════

  function geometryToPath(geometry, project) {
    var d = '';
    function processRing(ring) {
      for (var i = 0; i < ring.length; i++) {
        var pt = project(ring[i][0], ring[i][1]);
        d += (i === 0 ? 'M' : 'L') + pt[0].toFixed(1) + ',' + pt[1].toFixed(1);
      }
      d += 'Z';
    }
    if (geometry.type === 'Polygon') {
      geometry.coordinates.forEach(processRing);
    } else if (geometry.type === 'MultiPolygon') {
      geometry.coordinates.forEach(function (poly) { poly.forEach(processRing); });
    }
    return d;
  }

  // ══════════════════════════════════════════════════════════════════
  // Network: fetch with fallback URLs
  // ══════════════════════════════════════════════════════════════════

  async function fetchWithFallback(urls) {
    for (const url of urls) {
      try {
        const resp = await fetch(url);
        if (resp.ok) return await resp.json();
      } catch (_) { /* try next */ }
    }
    throw new Error('All GeoJSON URLs failed');
  }

  // ══════════════════════════════════════════════════════════════════
  // Alpine.js Component
  // ══════════════════════════════════════════════════════════════════

  window.geoFilter = function (config) {
    config = config || {};

    function normalizeDeptCodes(values) {
      var source = Array.isArray(values) ? values : [];
      var normalized = source
        .map(function (v) { return String(v).trim().toUpperCase(); })
        .filter(function (code) { return METRO_DEPTS.has(code); });
      return Array.from(new Set(normalized));
    }

    return {
      // ── State ────────────────────────────────────────────────
      mode: 'regions',
      selectedDepts: normalizeDeptCodes(config.selected || []),
      hoveredArea: null,
      hoveredName: '',
      loaded: false,
      error: false,
      open: (config.selected || []).length > 0,
      tooltipX: 0,
      tooltipY: 0,

      // ── Internal ─────────────────────────────────────────────
      svgWidth: 550,
      svgHeight: 560,
      _deptsData: null,
      _regionsData: null,
      _deptNames: {},

      // ── Computed ─────────────────────────────────────────────
      get hasSelection() {
        return this.selectedDepts.length > 0;
      },
      get regionEntries() {
        return Object.entries(REGIONS)
          .map(function (e) { return { code: e[0], name: e[1].name }; })
          .sort(function (a, b) { return a.name.localeCompare(b.name, 'fr'); });
      },
      get selectionLabel() {
        var n = this.selectedDepts.length;
        if (n === 0) return 'Cliquez sur la carte pour sélectionner';
        return n + ' département' + (n > 1 ? 's' : '') + ' sélectionné' + (n > 1 ? 's' : '');
      },

      /**
       * Returns selected items grouped for display:
       * - In region mode: groups by region, showing region names for fully selected regions
       * - In department mode: shows individual departments
       */
      get selectionBadges() {
        if (this.mode === 'regions') {
          var badges = [];
          var handledDepts = new Set();
          var self = this;
          // Group by region
          for (var i = 0; i < REGION_CODES.length; i++) {
            var rc = REGION_CODES[i];
            var info = REGIONS[rc];
            var selectedInRegion = info.depts.filter(function (d) { return self.selectedDepts.indexOf(d) >= 0; });
            if (selectedInRegion.length === 0) continue;

            if (selectedInRegion.length === info.depts.length) {
              // Fully selected region
              badges.push({ type: 'region', code: rc, label: info.name, count: info.depts.length });
            } else {
              // Partially selected region — show region name with count
              badges.push({ type: 'region-partial', code: rc, label: info.name + ' (' + selectedInRegion.length + '/' + info.depts.length + ')', count: selectedInRegion.length });
            }
            selectedInRegion.forEach(function (d) { handledDepts.add(d); });
          }
          return badges;
        }
        // Department mode: individual badges
        var self = this;
        return this.selectedDepts.slice().sort().map(function (code) {
          return { type: 'dept', code: code, label: (self._deptNames[code] || code), count: 1 };
        });
      },

      // ── Lifecycle ────────────────────────────────────────────
      async init() {
        var self = this;
        this.selectedDepts = normalizeDeptCodes(this.selectedDepts);
        this.$watch('mode', function () {
          if (self.loaded) self.renderMap();
        });
        await this.loadData();
      },

      // ── Data Loading ─────────────────────────────────────────
      async loadData() {
        try {
          var results = await Promise.all([
            fetchWithFallback(GEOJSON_URLS.departments),
            fetchWithFallback(GEOJSON_URLS.regions),
          ]);
          this._deptsData = results[0];
          this._regionsData = results[1];

          // Build lookup
          for (var i = 0; i < this._deptsData.features.length; i++) {
            var f = this._deptsData.features[i];
            this._deptNames[f.properties.code] = f.properties.nom;
          }

          this.loaded = true;
          var self = this;
          this.$nextTick(function () { self.renderMap(); });
        } catch (e) {
          console.error('[PyVolley] Failed to load France GeoJSON:', e);
          this.error = true;
        }
      },

      // ── Map Rendering ────────────────────────────────────────
      renderMap() {
        var svg = this.$refs.mapSvg;
        if (!svg) return;
        svg.innerHTML = '';

        // Add CSS class for mode-specific styling (department borders)
        svg.classList.remove('mode-departments', 'mode-regions');
        svg.classList.add('mode-' + this.mode);

        var project = createProjection(this.svgWidth, this.svgHeight);
        var self = this;

        if (this.mode === 'regions') {
          // Region mode: render region outlines from region GeoJSON,
          // but use them only for visual boundaries.
          // Selection toggles entire regions.
          var data = this._regionsData;
          for (var i = 0; i < data.features.length; i++) {
            var feature = data.features[i];
            var code = feature.properties.code;
            var name = feature.properties.nom;

            if (!REGIONS[code]) continue;

            var pathD = geometryToPath(feature.geometry, project);
            if (!pathD) continue;

            var fillColor = REGIONS[code] ? REGIONS[code].color : '#1e2340';

            var group = document.createElementNS(SVG_NS, 'g');
            group.setAttribute('class', 'map-area');
            group.setAttribute('data-code', code);
            group.setAttribute('data-name', name);

            var path = document.createElementNS(SVG_NS, 'path');
            path.setAttribute('d', pathD);
            path.style.fill = fillColor;
            group.appendChild(path);

            (function (c, n) {
              group.addEventListener('click', function () { self.handleClick(c); });
              group.addEventListener('mouseenter', function (e) {
                self.hoveredArea = c;
                self.hoveredName = self._buildTooltipText(c, n);
                self._updateTooltip(e);
              });
              group.addEventListener('mousemove', function (e) { self._updateTooltip(e); });
              group.addEventListener('mouseleave', function () { self.hoveredArea = null; });
            })(code, name);

            svg.appendChild(group);
          }
        } else {
          // Department mode: render each department individually
          var data = this._deptsData;
          for (var i = 0; i < data.features.length; i++) {
            var feature = data.features[i];
            var code = feature.properties.code;
            var name = feature.properties.nom;

            if (!METRO_DEPTS.has(code)) continue;

            var pathD = geometryToPath(feature.geometry, project);
            if (!pathD) continue;

            var regionCode = DEPT_TO_REGION[code] || '00';
            var fillColor = REGIONS[regionCode] ? REGIONS[regionCode].color : '#1e2340';

            var group = document.createElementNS(SVG_NS, 'g');
            group.setAttribute('class', 'map-area');
            group.setAttribute('data-code', code);
            group.setAttribute('data-name', name);

            var path = document.createElementNS(SVG_NS, 'path');
            path.setAttribute('d', pathD);
            path.style.fill = fillColor;
            group.appendChild(path);

            (function (c, n) {
              group.addEventListener('click', function () { self.handleClick(c); });
              group.addEventListener('mouseenter', function (e) {
                self.hoveredArea = c;
                self.hoveredName = self._buildTooltipText(c, n);
                self._updateTooltip(e);
              });
              group.addEventListener('mousemove', function (e) { self._updateTooltip(e); });
              group.addEventListener('mouseleave', function () { self.hoveredArea = null; });
            })(code, name);

            svg.appendChild(group);
          }
        }

        this.updateStyles();
      },

      _buildTooltipText(code, name) {
        if (this.mode === 'regions') {
          var info = REGIONS[code];
          if (info) {
            var sel = info.depts.filter(function (d) { return this.selectedDepts.indexOf(d) >= 0; }.bind(this));
            var label = name + ' — Championnat régional';
            if (sel.length > 0 && sel.length < info.depts.length) {
              label += ' (' + sel.length + '/' + info.depts.length + ' dép.)';
            }
            return label;
          }
          return name;
        }
        // Department mode: show "Name (XX) — Championnat départemental"
        var region = DEPT_TO_REGION[code];
        var regionName = region ? REGIONS[region].name : '';
        return name + ' (' + code + ') — Champ. départemental' + (regionName ? ' · ' + regionName : '');
      },

      _updateTooltip(e) {
        var container = this.$refs.mapContainer;
        if (!container) return;
        var rect = container.getBoundingClientRect();
        this.tooltipX = e.clientX - rect.left;
        this.tooltipY = e.clientY - rect.top - 12;
      },

      // ── Selection Logic ──────────────────────────────────────
      handleClick(code) {
        if (this.mode === 'regions') {
          this.toggleRegion(code);
        } else {
          this.toggleDept(code);
        }
        this.updateStyles();
      },

      toggleRegion(regionCode) {
        var info = REGIONS[regionCode];
        if (!info) return;
        var depts = info.depts;
        var self = this;
        var allSelected = depts.every(function (d) { return self.selectedDepts.indexOf(d) >= 0; });

        if (allSelected) {
          this.selectedDepts = this.selectedDepts.filter(function (d) { return depts.indexOf(d) < 0; });
        } else {
          var merged = new Set(this.selectedDepts.concat(depts));
          this.selectedDepts = Array.from(merged);
        }
        this.selectedDepts = normalizeDeptCodes(this.selectedDepts);
      },

      toggleDept(code) {
        code = String(code).trim().toUpperCase();
        if (!METRO_DEPTS.has(code)) return;
        var idx = this.selectedDepts.indexOf(code);
        if (idx >= 0) {
          this.selectedDepts.splice(idx, 1);
        } else {
          this.selectedDepts.push(code);
        }
        this.selectedDepts = normalizeDeptCodes(this.selectedDepts);
      },

      removeDepartment(code) {
        code = String(code).trim().toUpperCase();
        this.selectedDepts = this.selectedDepts.filter(function (d) { return d !== code; });
        this.selectedDepts = normalizeDeptCodes(this.selectedDepts);
        this.updateStyles();
      },

      removeRegion(regionCode) {
        var info = REGIONS[regionCode];
        if (!info) return;
        var depts = info.depts;
        this.selectedDepts = this.selectedDepts.filter(function (d) { return depts.indexOf(d) < 0; });
        this.selectedDepts = normalizeDeptCodes(this.selectedDepts);
        this.updateStyles();
      },

      removeBadge(badge) {
        if (badge.type === 'region' || badge.type === 'region-partial') {
          this.removeRegion(badge.code);
        } else {
          this.removeDepartment(badge.code);
        }
      },

      clearAll() {
        this.selectedDepts = [];
        this.updateStyles();
      },

      // ── Selection Queries ────────────────────────────────────
      isRegionFullySelected(regionCode) {
        var info = REGIONS[regionCode];
        if (!info || info.depts.length === 0) return false;
        var self = this;
        return info.depts.every(function (d) { return self.selectedDepts.indexOf(d) >= 0; });
      },

      isRegionPartiallySelected(regionCode) {
        var info = REGIONS[regionCode];
        if (!info) return false;
        var self = this;
        var some = info.depts.some(function (d) { return self.selectedDepts.indexOf(d) >= 0; });
        return some && !this.isRegionFullySelected(regionCode);
      },

      // ── Style Updates (no re-render) ─────────────────────────
      updateStyles() {
        var svg = this.$refs.mapSvg;
        if (!svg) return;
        var self = this;

        svg.querySelectorAll('.map-area').forEach(function (group) {
          var code = group.getAttribute('data-code');
          var selected = false;
          var partial = false;

          if (self.mode === 'regions') {
            selected = self.isRegionFullySelected(code);
            partial = self.isRegionPartiallySelected(code);
          } else {
            selected = self.selectedDepts.indexOf(code) >= 0;
          }

          group.classList.toggle('selected', selected);
          group.classList.toggle('partial', partial);
        });
      },

      // ── Name Lookups ─────────────────────────────────────────
      getDeptName(code) {
        return this._deptNames[code] || code;
      },

      getDeptRegionName(code) {
        var r = DEPT_TO_REGION[code];
        return r ? REGIONS[r].name : '';
      },

      // ── URL Integration ──────────────────────────────────────
      applyFilter() {
        this.selectedDepts = normalizeDeptCodes(this.selectedDepts);
        var params = new URLSearchParams(window.location.search);
        if (this.selectedDepts.length > 0) {
          params.set('departements', this.selectedDepts.slice().sort().join(','));
        } else {
          params.delete('departements');
        }
        params.delete('page');
        var qs = params.toString();
        window.location.href = window.location.pathname + (qs ? '?' + qs : '');
      },

      resetFilter() {
        this.selectedDepts = [];
        this.updateStyles();
        var params = new URLSearchParams(window.location.search);
        params.delete('departements');
        params.delete('page');
        var qs = params.toString();
        window.location.href = window.location.pathname + (qs ? '?' + qs : '');
      },
    };
  };

})();
