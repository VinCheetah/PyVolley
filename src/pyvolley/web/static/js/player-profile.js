/**
 * PyVolley — Player Profile Interactive Visualizations
 * 
 * Manages Chart.js renderings for:
 * 1. Radar Profile (offensive & tactical dimensions)
 * 2. Level Distribution (pie/doughnut of competition tiers)
 * 3. Match Level Timeline (historical career level progression)
 * 4. Match Performance Evolution (points, side-out %, break ratio)
 */

(function () {
    'use strict';

    const chartColors = {
        green: '#22c55e',
        red: '#ef4444',
        blue: '#3b82f6',
        gold: '#f59e0b',
        cyan: '#06b6d4',
        purple: '#a855f7',
    };
    const gridColor = 'rgba(71, 85, 105, 0.25)';
    const textColor = '#94a3b8';

    function initRadarChart(aggregatedStats) {
        const radarCtx = document.getElementById('playerProfileRadarChart');
        if (!radarCtx || !aggregatedStats || (Number(aggregatedStats.matchs_joues) || 0) <= 0) {
            return;
        }

        const clampPct = (value) => Math.max(0, Math.min(100, Number(value) || 0));
        const matchCount = Math.max(1, Number(aggregatedStats.matchs_joues) || 1);
        const setsPlayed = Math.max(1, Number(aggregatedStats.total_sets_joues) || 1);
        const avgPointsPlayed = (Number(aggregatedStats.total_points_joues) || 0) / matchCount;
        const avgSideoutPoints = (Number(aggregatedStats.total_points_gagnes_sideout) || 0) / matchCount;

        const radarValues = [
            clampPct(avgPointsPlayed * 2.8),
            clampPct((Number(aggregatedStats.ratio_points_gagnes_global) || 0) * 100),
            clampPct((Number(aggregatedStats.break_point_ratio_global) || 0) * 100),
            clampPct((Number(aggregatedStats.ratio_points_gagnes_sideout_global) || 0) * 100),
            clampPct(((Number(aggregatedStats.total_sets_titulaire) || 0) / setsPlayed) * 100),
            clampPct((Number(aggregatedStats.moyenne_points_par_tour) || 0) * 35),
            clampPct(avgSideoutPoints * 6),
        ];

        const radarGradient = radarCtx.getContext('2d').createLinearGradient(0, 0, 0, 280);
        radarGradient.addColorStop(0, 'rgba(6, 182, 212, 0.42)');
        radarGradient.addColorStop(0.55, 'rgba(59, 130, 246, 0.2)');
        radarGradient.addColorStop(1, 'rgba(59, 130, 246, 0.04)');

        new Chart(radarCtx, {
            type: 'radar',
            data: {
                labels: [
                    'Volume points',
                    'Efficacité globale',
                    'Break',
                    'Side-out',
                    'Régularité titulaire',
                    'Impact service',
                    'Production side-out',
                ],
                datasets: [{
                    label: 'Profil',
                    data: radarValues,
                    borderColor: '#22d3ee',
                    backgroundColor: radarGradient,
                    pointBackgroundColor: '#93c5fd',
                    pointBorderColor: '#0b0e17',
                    pointBorderWidth: 1.5,
                    pointRadius: 3,
                    borderWidth: 2.2,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    r: {
                        min: 0,
                        max: 100,
                        beginAtZero: true,
                        angleLines: { color: 'rgba(71, 85, 105, 0.35)' },
                        grid: { color: 'rgba(71, 85, 105, 0.35)' },
                        pointLabels: { color: textColor, font: { size: 10 } },
                        ticks: { display: false, stepSize: 20 },
                    },
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `${ctx.label}: ${Math.round(ctx.parsed.r)} / 100`,
                        },
                    },
                },
            },
        });
    }

    function initLevelDistributionChart(levelData) {
        const levelCtx = document.getElementById('levelDistributionChart');
        if (!levelCtx || !Array.isArray(levelData) || levelData.length <= 1) {
            return;
        }

        new Chart(levelCtx, {
            type: 'doughnut',
            data: {
                labels: levelData.map(item => item.label),
                datasets: [{
                    data: levelData.map(item => item.count),
                    backgroundColor: [
                        'rgba(59, 130, 246, 0.8)',
                        'rgba(6, 182, 212, 0.8)',
                        'rgba(34, 197, 94, 0.8)',
                        'rgba(245, 158, 11, 0.8)',
                        'rgba(168, 85, 247, 0.8)',
                        'rgba(239, 68, 68, 0.8)',
                    ],
                    borderColor: 'rgba(11, 14, 23, 0.9)',
                    borderWidth: 2,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: textColor,
                            usePointStyle: true,
                            pointStyle: 'circle',
                            boxWidth: 10,
                        },
                    },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                const value = ctx.parsed || 0;
                                const total = levelData.reduce((acc, item) => acc + (item.count || 0), 0);
                                const pct = total > 0 ? ((value / total) * 100).toFixed(1) : '0.0';
                                return `${ctx.label}: ${value} match(s) (${pct}%)`;
                            },
                        },
                    },
                },
                cutout: '58%',
            },
        });
    }

    function initLevelTimelineChart(levelTimeline, levelRankLabels) {
        const levelTimelineCtx = document.getElementById('matchLevelTimelineChart');
        const levelTimelineRange = document.getElementById('matchLevelTimelineRange');
        if (!levelTimelineCtx || !Array.isArray(levelTimeline) || levelTimeline.length <= 1) {
            return;
        }

        const rankLabelMap = new Map((levelRankLabels || []).map((item) => [Number(item.rank), item.label]));
        const knownReferenceRanks = (levelRankLabels || [])
            .map((item) => Number(item.rank))
            .filter((rank) => Number.isInteger(rank))
            .sort((a, b) => a - b);
        const minReferenceRank = knownReferenceRanks.length ? knownReferenceRanks[0] : 0;
        const maxReferenceRank = knownReferenceRanks.length ? knownReferenceRanks[knownReferenceRanks.length - 1] : 8;
        let levelTimelineChart = null;

        const parseWindowSize = (value) => {
            if (!value || value === 'all') return null;
            const parsed = Number.parseInt(value, 10);
            return Number.isInteger(parsed) && parsed > 1 ? parsed : null;
        };

        const renderLevelTimeline = () => {
            const selectedWindow = parseWindowSize(levelTimelineRange ? levelTimelineRange.value : 'all');
            const timelineSlice = selectedWindow ? levelTimeline.slice(-selectedWindow) : levelTimeline.slice();
            const rawRanks = timelineSlice.map((item) => (
                typeof item.level_rank === 'number' ? item.level_rank : null
            ));
            const knownRanks = rawRanks.filter((value) => typeof value === 'number');

            const minKnownRank = knownRanks.length ? Math.min(...knownRanks) : minReferenceRank;
            const maxKnownRank = knownRanks.length ? Math.max(...knownRanks) : maxReferenceRank;
            const yMin = Math.max(minReferenceRank, minKnownRank - 1);
            const yMax = Math.min(maxReferenceRank, maxKnownRank + 1);

            const pointColors = timelineSlice.map((item) => {
                if (item.victoire === true) return chartColors.green;
                if (item.victoire === false) return chartColors.red;
                return chartColors.blue;
            });

            if (levelTimelineChart) {
                levelTimelineChart.destroy();
            }

            const gradientFill = levelTimelineCtx.getContext('2d').createLinearGradient(0, 0, 0, 320);
            gradientFill.addColorStop(0, 'rgba(6, 182, 212, 0.34)');
            gradientFill.addColorStop(0.5, 'rgba(59, 130, 246, 0.15)');
            gradientFill.addColorStop(1, 'rgba(59, 130, 246, 0.03)');

            levelTimelineChart = new Chart(levelTimelineCtx, {
                type: 'line',
                data: {
                    labels: timelineSlice.map((m, i) => (
                        m.date
                            ? new Date(m.date).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' })
                            : `M${i + 1}`
                    )),
                    datasets: [{
                        label: 'Niveau du match',
                        data: rawRanks,
                        borderColor: chartColors.cyan,
                        backgroundColor: gradientFill,
                        borderWidth: 2.6,
                        fill: true,
                        tension: 0.2,
                        pointRadius: 3.5,
                        pointHoverRadius: 6,
                        pointBackgroundColor: pointColors,
                        pointBorderColor: '#0b0e17',
                        pointBorderWidth: 1.5,
                        spanGaps: true,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    scales: {
                        y: {
                            min: yMin,
                            max: yMax,
                            grid: { color: gridColor },
                            ticks: {
                                color: textColor,
                                stepSize: 1,
                                callback: (value) => {
                                    const tickValue = Number(value);
                                    if (!Number.isInteger(tickValue)) return '';
                                    return rankLabelMap.get(tickValue) || '';
                                },
                            },
                        },
                        x: {
                            grid: { display: false },
                            ticks: { color: textColor, maxRotation: 55, font: { size: 10 } },
                        },
                    },
                    plugins: {
                        legend: { labels: { color: textColor } },
                        tooltip: {
                            callbacks: {
                                title: (ctx) => {
                                    const first = ctx && ctx.length ? ctx[0] : null;
                                    const index = first ? first.dataIndex : 0;
                                    const item = timelineSlice[index];
                                    if (item && item.date) {
                                        return new Date(item.date).toLocaleDateString('fr-FR');
                                    }
                                    return `Match ${index + 1}`;
                                },
                                label: (ctx) => {
                                    const item = timelineSlice[ctx.dataIndex];
                                    if (!item || item.level_rank === null || item.level_rank === undefined) {
                                        return 'Niveau inconnu';
                                    }
                                    const resultat = item.victoire === true
                                        ? 'Victoire'
                                        : (item.victoire === false ? 'Défaite' : 'Résultat inconnu');
                                    return `${item.niveau} (${resultat})`;
                                },
                                afterLabel: (ctx) => {
                                    const item = timelineSlice[ctx.dataIndex];
                                    return item && item.adversaire ? `Adversaire: ${item.adversaire}` : '';
                                },
                            },
                        },
                    },
                },
            });
        };

        renderLevelTimeline();
        if (levelTimelineRange) {
            levelTimelineRange.addEventListener('change', renderLevelTimeline);
        }
    }

    function initMatchEvolutionChart(evolutionData) {
        const evolutionCtx = document.getElementById('matchEvolutionChart');
        if (!evolutionCtx || !Array.isArray(evolutionData) || evolutionData.length <= 1) {
            return;
        }

        new Chart(evolutionCtx, {
            type: 'line',
            data: {
                labels: evolutionData.map((m, i) => m.date ? new Date(m.date).toLocaleDateString('fr-FR') : `M${i + 1}`),
                datasets: [
                    {
                        label: 'Points joués',
                        data: evolutionData.map(m => m.points_joues || 0),
                        borderColor: chartColors.cyan,
                        backgroundColor: 'rgba(6, 182, 212, 0.15)',
                        borderWidth: 2,
                        tension: 0.25,
                        pointRadius: 2,
                    },
                    {
                        label: '% points gagnés',
                        data: evolutionData.map(m => m.ratio_points_pct || 0),
                        borderColor: chartColors.gold,
                        backgroundColor: 'rgba(245, 158, 11, 0.12)',
                        borderWidth: 2,
                        borderDash: [6, 4],
                        tension: 0.25,
                        pointRadius: 2,
                        yAxisID: 'y1',
                    },
                    {
                        label: 'Break ratio %',
                        data: evolutionData.map(m => m.break_point_ratio_pct || 0),
                        borderColor: chartColors.purple,
                        backgroundColor: 'rgba(168, 85, 247, 0.12)',
                        borderWidth: 2,
                        borderDash: [4, 3],
                        tension: 0.25,
                        pointRadius: 2,
                        yAxisID: 'y1',
                    },
                    {
                        label: 'Contribution side-out %',
                        data: evolutionData.map(m => m.sideout_contribution_pct || 0),
                        borderColor: chartColors.blue,
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        borderWidth: 2,
                        borderDash: [2, 4],
                        tension: 0.25,
                        pointRadius: 2,
                        yAxisID: 'y1',
                    },
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: gridColor },
                        ticks: { color: textColor },
                    },
                    y1: {
                        beginAtZero: true,
                        max: 100,
                        position: 'right',
                        grid: { display: false },
                        ticks: { color: chartColors.gold, callback: v => `${v}%` },
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: textColor, maxRotation: 45, font: { size: 10 } },
                    },
                },
                plugins: {
                    legend: { labels: { color: textColor } },
                },
            },
        });
    }

    window.initPlayerProfile = function (config) {
        if (!config) return;
        if (config.aggregatedStats) initRadarChart(config.aggregatedStats);
        if (config.levelDistribution) initLevelDistributionChart(config.levelDistribution);
        if (config.levelTimeline) initLevelTimelineChart(config.levelTimeline, config.levelRankLabels);
        if (config.matchEvolutionStats) initMatchEvolutionChart(config.matchEvolutionStats);
    };
})();
