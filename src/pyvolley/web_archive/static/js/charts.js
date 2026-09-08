/* ═══════════════════════════════════════════════════════════════
   PyVolley — Chart.js Helpers
   Shared defaults, color palettes, and factory for Chart.js charts.
   ═══════════════════════════════════════════════════════════════ */
window.PyVolleyCharts = (function() {
    'use strict';

    // ── Color palettes ──
    const colors = {
        blue: '#3b82f6',
        blueLight: '#60a5fa',
        red: '#ef4444',
        redLight: '#f87171',
        green: '#22c55e',
        greenLight: '#4ade80',
        gold: '#f59e0b',
        purple: '#a855f7',
        cyan: '#06b6d4',
        pink: '#ec4899',
        gridLine: 'rgba(42, 48, 80, 0.5)',
        text: '#5a6178',
        textLight: '#8b92a8',
    };

    // 20 distinct colors for multi-team charts
    const teamPalette = [
        '#3b82f6', '#ef4444', '#22c55e', '#f59e0b', '#a855f7',
        '#06b6d4', '#ec4899', '#14b8a6', '#f97316', '#8b5cf6',
        '#10b981', '#e11d48', '#0ea5e9', '#84cc16', '#d946ef',
        '#6366f1', '#f43f5e', '#34d399', '#fbbf24', '#c084fc',
    ];

    // ── Default scale configuration ──
    const defaultScales = {
        x: {
            grid: { color: colors.gridLine },
            ticks: { color: colors.text, font: { size: 11 } },
        },
        y: {
            grid: { color: colors.gridLine },
            ticks: { color: colors.text, font: { size: 11 } },
            beginAtZero: true,
        },
    };

    // ── Deep merge utility ──
    function deepMerge(target, source) {
        const out = Object.assign({}, target);
        for (const key in source) {
            if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
                out[key] = deepMerge(out[key] || {}, source[key]);
            } else {
                out[key] = source[key];
            }
        }
        return out;
    }

    // ── Visibility Observer for Tabs ──
    const visibilityObserver = (typeof IntersectionObserver !== 'undefined')
        ? new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const canvas = entry.target;
                    const chart = canvas._chartInstance || (typeof Chart !== 'undefined' ? Chart.getChart(canvas) : null);
                    if (chart) {
                        try {
                            chart.resize();
                            chart.update('none');
                        } catch (e) {
                            /* ignore transient resize errors */
                        }
                    }
                }
            });
        }, { threshold: 0.01 })
        : null;

    function observeCanvas(canvas, chart) {
        if (!canvas) return;
        canvas._chartInstance = chart;
        if (visibilityObserver) {
            visibilityObserver.observe(canvas);
        }
    }

    // Global resize trigger
    if (typeof window !== 'undefined') {
        window.addEventListener('resize', () => {
            document.querySelectorAll('canvas').forEach(canvas => {
                const chart = canvas._chartInstance || (typeof Chart !== 'undefined' ? Chart.getChart(canvas) : null);
                if (chart && canvas.offsetWidth > 0 && canvas.offsetHeight > 0) {
                    try { chart.resize(); } catch (e) {}
                }
            });
        });
    }

    /**
     * Create a Chart.js chart with PyVolley defaults.
     * @param {string} canvasId - The canvas element ID
     * @param {string} type - Chart type ('bar', 'line', 'doughnut', 'bubble', etc.)
     * @param {object} config - Chart.js config (data, options, plugins)
     * @returns {Chart|null} The created chart instance, or null if canvas not found
     */
    function create(canvasId, type, config) {
        const canvas = typeof canvasId === 'string' ? document.getElementById(canvasId) : canvasId;
        if (!canvas) return null;

        // Destroy existing chart on canvas if present to prevent canvas reuse errors
        if (typeof Chart !== 'undefined') {
            const existing = Chart.getChart(canvas);
            if (existing) {
                try { existing.destroy(); } catch (e) {}
            }
        }

        const defaults = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
            },
        };

        // Only add scales for non-radial chart types
        if (type !== 'doughnut' && type !== 'pie' && type !== 'polarArea' && type !== 'radar') {
            defaults.scales = JSON.parse(JSON.stringify(defaultScales));
        }

        const mergedOptions = deepMerge(defaults, config.options || {});

        const chart = new Chart(canvas, {
            type: type,
            data: config.data,
            options: mergedOptions,
            plugins: config.plugins || [],
        });

        observeCanvas(canvas, chart);
        return chart;
    }

    /**
     * Create a horizontal bar chart (common pattern for rankings).
     * @param {string} canvasId - Canvas element ID
     * @param {string[]} labels - Team/entity names
     * @param {number[]} values - Values to plot
     * @param {object} opts - Optional overrides {colors, label, maxBarThickness}
     */
    function horizontalBar(canvasId, labels, values, opts) {
        opts = opts || {};
        const barColors = opts.colors || labels.map((_, i) => teamPalette[i % teamPalette.length]);

        return create(canvasId, 'bar', {
            data: {
                labels: labels,
                datasets: [{
                    data: values,
                    backgroundColor: barColors,
                    borderColor: barColors,
                    borderWidth: 1,
                    borderRadius: 4,
                    maxBarThickness: opts.maxBarThickness || 28,
                }],
            },
            options: {
                indexAxis: 'y',
                scales: {
                    x: {
                        grid: { color: colors.gridLine },
                        ticks: { color: colors.text, font: { size: 11 } },
                    },
                    y: {
                        grid: { display: false },
                        ticks: {
                            color: colors.textLight,
                            font: { size: 11 },
                            callback: function(value) {
                                const label = this.getLabelForValue(value);
                                return label.length > 25 ? label.substring(0, 25) + '…' : label;
                            },
                        },
                    },
                },
                plugins: {
                    tooltip: {
                        callbacks: {
                            label: function(ctx) {
                                return (opts.label || '') + ctx.parsed.x;
                            },
                        },
                    },
                },
            },
        });
    }

    return { colors, teamPalette, defaultScales, create, horizontalBar, observeCanvas };
})();
