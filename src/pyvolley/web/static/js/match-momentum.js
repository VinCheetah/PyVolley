/* ═══════════════════════════════════════════════════════════════
   PyVolley — Match Momentum Visualizer
   Builds smooth point-by-point score differential charts with
   substitutions/timeouts markers for each set and whole match.
   ═══════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    const diag = {
        startedAt: new Date().toISOString(),
        checks: [],
        setDiagnostics: [],
        chartsBuilt: 0,
        status: 'booting',
        reason: null,
        error: null,
    };

    function pushCheck(name, ok, detail) {
        diag.checks.push({ name, ok: Boolean(ok), detail: detail || '' });
    }

    function setHealthMessage(message, isError) {
        const node = document.getElementById('momentum-health');
        if (!node) return;
        node.textContent = message;
        node.style.color = isError ? 'var(--accent-red)' : 'var(--accent-green-light)';
    }

    function renderDebugPanels() {
        if (!window.PYVOLLEY_MOMENTUM_DEBUG) return;

        const summaryNode = document.getElementById('momentum-debug-summary');
        if (summaryNode) {
            const okChecks = diag.checks.filter((c) => c.ok).length;
            summaryNode.textContent = [
                `status: ${diag.status}`,
                `reason: ${diag.reason || '-'}`,
                `charts: ${diag.chartsBuilt}`,
                `checks: ${okChecks}/${diag.checks.length}`,
                diag.error ? `error: ${diag.error}` : null,
            ].filter(Boolean).join('\n');
        }

        const setsNode = document.getElementById('momentum-debug-sets');
        if (setsNode) {
            const lines = diag.setDiagnostics.map((item) =>
                `set ${item.set}: services=${item.hasServices ? 'yes' : 'no'}, strict=${item.strict ? 'ok' : 'fallback'}, points=${item.points}`
            );
            setsNode.textContent = lines.length ? lines.join('\n') : 'Aucune timeline set générée';
        }
    }

    function publishDiag(status, reason, errorMessage) {
        diag.status = status;
        diag.reason = reason || null;
        diag.error = errorMessage || null;
        window.PYVOLLEY_MOMENTUM_DIAG = diag;
        renderDebugPanels();
    }

    const chartAvailable = typeof Chart !== 'undefined';
    pushCheck('Chart.js loaded', chartAvailable, chartAvailable ? '' : 'Chart is undefined');

    const hasTimelineFlag = Boolean(window.PYVOLLEY_HAS_POINT_TIMELINE);
    pushCheck('has_point_timeline', hasTimelineFlag, hasTimelineFlag ? '' : 'Flag false');

    const match = window.PYVOLLEY_MATCH_DATA;
    const momentumData = window.PYVOLLEY_MOMENTUM_DATA;
    const coachAnalysis = momentumData && momentumData.coach_analysis ? momentumData.coach_analysis : null;
    const momentumSets = momentumData && Array.isArray(momentumData.sets) ? momentumData.sets : [];
    const hasMomentumSets = momentumSets.length > 0;
    pushCheck('momentum data', hasMomentumSets, hasMomentumSets ? `sets=${momentumSets.length}` : 'No backend momentum sets');

    const shouldRenderMomentum = chartAvailable && hasTimelineFlag && hasMomentumSets;

    const teamNames = {
        A: (momentumData.teams && momentumData.teams.A) || (match && match.equipe_a && match.equipe_a.nom) || 'Équipe A',
        B: (momentumData.teams && momentumData.teams.B) || (match && match.equipe_b && match.equipe_b.nom) || 'Équipe B',
    };

    const rootStyle = getComputedStyle(document.documentElement);
    const token = (name, fallback) => rootStyle.getPropertyValue(name).trim() || fallback;

    const colors = {
        teamA: token('--team-a-light', '#60a5fa'),
        teamABorder: token('--team-a', '#3b82f6'),
        teamB: token('--team-b-light', '#f87171'),
        teamBBorder: token('--team-b', '#ef4444'),
        gold: token('--accent-gold', '#f59e0b'),
        text: token('--text-secondary', '#8b92a8'),
        textMuted: token('--text-muted', '#5a6178'),
        grid: 'rgba(42, 48, 80, 0.45)',
    };

    const charts = [];

    function toInt(value) {
        const n = Number(value);
        return Number.isFinite(n) ? n : null;
    }

    function toNumber(value) {
        const n = Number(value);
        return Number.isFinite(n) ? n : null;
    }

    function signed(value, digits = 1) {
        const n = Number(value);
        if (!Number.isFinite(n)) return '0.0';
        const fixed = n.toFixed(digits);
        return n > 0 ? `+${fixed}` : fixed;
    }

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function coachImpactClass(score) {
        const n = Number(score || 0);
        if (n >= 12) return 'coach-impact-positive';
        if (n <= -12) return 'coach-impact-negative';
        return 'coach-impact-neutral';
    }

    function shorten(text, maxLen) {
        const raw = (text || '').trim();
        if (!raw || raw.length <= maxLen) return raw;
        return `${raw.slice(0, Math.max(0, maxLen - 1))}…`;
    }

    function formatServerLabel(server) {
        if (!server || typeof server !== 'object') return null;

        const numero = (server.numero || '').toString().trim();
        const nom = (server.nom || '').toString().trim();
        const prenom = (server.prenom || '').toString().trim();
        const fullName = [nom, prenom].filter(Boolean).join(' ').trim();

        const identityParts = [];
        if (numero) identityParts.push(`N°${numero}`);
        if (fullName) identityParts.push(fullName);
        const identity = identityParts.join(' ').trim();

        const teamLabel = server.team === 'A'
            ? teamNames.A
            : (server.team === 'B' ? teamNames.B : null);

        if (identity && teamLabel) return `${identity} (${teamLabel})`;
        return identity || teamLabel || null;
    }

    function parseServices(raw) {
        const parsed = {};
        if (!raw || typeof raw !== 'object') return parsed;

        Object.entries(raw).forEach(([k, v]) => {
            const pos = parseInt(k, 10);
            if (!Number.isInteger(pos) || !Array.isArray(v)) return;
            const scores = v
                .map((item) => toInt(item))
                .filter((item) => item !== null)
                .sort((a, b) => a - b);
            if (scores.length > 0) parsed[pos] = scores;
        });

        return parsed;
    }

    function extractSetEvents(setData) {
        const events = [];

        function pushEvents(items, team, kind) {
            (items || []).forEach((item) => {
                const scoreA = toInt(item.score_a);
                const scoreB = toInt(item.score_b);
                if (scoreA === null || scoreB === null) return;

                events.push({
                    team,
                    kind,
                    scoreA,
                    scoreB,
                    x: scoreA + scoreB,
                    y: scoreA - scoreB,
                    decisionId: item.decision_id || null,
                    impactScore: toNumber(item.impact_score),
                    impactLabel: item.impact_label || null,
                    trendDeltaWinRatePct: toNumber(item.trend_delta_win_rate_pct),
                    confidencePct: toNumber(item.confidence_pct),
                });
            });
        }

        pushEvents(setData.timeouts_a, 'A', 'timeout');
        pushEvents(setData.timeouts_b, 'B', 'timeout');
        pushEvents(setData.changements_a, 'A', 'sub');
        pushEvents(setData.changements_b, 'B', 'sub');

        return events.sort((a, b) => (a.x - b.x) || (a.kind > b.kind ? 1 : -1));
    }

    function normalizeSetTimeline(setData) {
        const rawPoints = Array.isArray(setData.points) ? setData.points : [];
        if (!rawPoints.length) return null;
        const setNumber = toInt(setData.numero) || setData.numero;

        const points = rawPoints
            .map((point) => ({
                x: toInt(point.x),
                y: toInt(point.y),
                scoreA: toInt(point.score_a),
                scoreB: toInt(point.score_b),
                setNumber: toInt(point.set_numero) || setNumber,
                server: point.server && typeof point.server === 'object' ? point.server : null,
            }))
            .filter((point) => point.x !== null && point.y !== null && point.scoreA !== null && point.scoreB !== null)
            .sort((a, b) => a.x - b.x);

        if (!points.length) return null;

        const events = extractSetEvents({
            timeouts_a: (setData.events || []).filter((event) => event.type === 'timeout' && event.team === 'A'),
            timeouts_b: (setData.events || []).filter((event) => event.type === 'timeout' && event.team === 'B'),
            changements_a: (setData.events || []).filter((event) => event.type === 'sub' && event.team === 'A'),
            changements_b: (setData.events || []).filter((event) => event.type === 'sub' && event.team === 'B'),
        }).map((event) => ({
            ...event,
            setNumber,
        }));

        const finalPoint = points[points.length - 1];
        const timeline = {
            numero: setNumber,
            finalA: finalPoint.scoreA,
            finalB: finalPoint.scoreB,
            points,
            events,
        };

        diag.setDiagnostics.push({
            set: setData.numero,
            hasServices: true,
            strict: true,
            points: points.length,
        });

        return timeline;
    }

    function getYBounds(points, events) {
        const yValues = points.map((p) => p.y).concat(events.map((e) => e.y));
        const min = Math.min(...yValues, 0);
        const max = Math.max(...yValues, 0);
        const padding = Math.max(3, Math.ceil((max - min) * 0.2));
        return { min: min - padding, max: max + padding };
    }

    function buildEventDatasets(events, bounds) {
        const topTimeoutY = bounds.max - 0.8;
        const topSubY = bounds.max - 1.7;
        const bottomTimeoutY = bounds.min + 0.8;
        const bottomSubY = bounds.min + 1.7;

        const grouped = {
            aTimeout: [],
            aSub: [],
            bTimeout: [],
            bSub: [],
        };

        events.forEach((evt) => {
            const point = {
                x: evt.x,
                y: evt.team === 'A'
                    ? (evt.kind === 'timeout' ? topTimeoutY : topSubY)
                    : (evt.kind === 'timeout' ? bottomTimeoutY : bottomSubY),
                eventKind: evt.kind,
                team: evt.team,
                scoreA: evt.scoreA,
                scoreB: evt.scoreB,
                decisionId: evt.decisionId || null,
                impactScore: toNumber(evt.impactScore),
                impactLabel: evt.impactLabel || null,
                trendDeltaWinRatePct: toNumber(evt.trendDeltaWinRatePct),
                confidencePct: toNumber(evt.confidencePct),
            };

            if (evt.team === 'A' && evt.kind === 'timeout') grouped.aTimeout.push(point);
            if (evt.team === 'A' && evt.kind === 'sub') grouped.aSub.push(point);
            if (evt.team === 'B' && evt.kind === 'timeout') grouped.bTimeout.push(point);
            if (evt.team === 'B' && evt.kind === 'sub') grouped.bSub.push(point);
        });

        return [
            {
                data: grouped.aTimeout,
                team: 'A',
                label: 'Temps mort A',
                borderColor: colors.teamABorder,
                backgroundColor: colors.teamABorder,
                pointStyle: 'circle',
            },
            {
                data: grouped.aSub,
                team: 'A',
                label: 'Changement A',
                borderColor: colors.teamA,
                backgroundColor: colors.teamA,
                pointStyle: 'rectRot',
            },
            {
                data: grouped.bTimeout,
                team: 'B',
                label: 'Temps mort B',
                borderColor: colors.teamBBorder,
                backgroundColor: colors.teamBBorder,
                pointStyle: 'circle',
            },
            {
                data: grouped.bSub,
                team: 'B',
                label: 'Changement B',
                borderColor: colors.teamB,
                backgroundColor: colors.teamB,
                pointStyle: 'rectRot',
            },
        ]
            .filter((dataset) => dataset.data.length > 0)
            .map((dataset) => ({
                type: 'scatter',
                data: dataset.data,
                showLine: false,
                borderColor: dataset.borderColor,
                backgroundColor: dataset.backgroundColor,
                pointStyle: dataset.pointStyle,
                pointRadius: 4,
                pointHoverRadius: 7,
                borderWidth: 2,
                parsing: false,
                momentumEvent: true,
                momentumTeam: dataset.team,
                label: dataset.label,
            }));
    }

    function createMomentumChart(canvasId, title, timeline, xLabel, chartMeta = {}) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || !timeline) return;

        const isMatchChart = Boolean(chartMeta.isMatchChart);
        const setSegments = Array.isArray(chartMeta.setSegments) ? chartMeta.setSegments : [];

        const points = timeline.points.map((point) => ({
            x: point.x,
            y: point.y,
            scoreA: point.scoreA,
            scoreB: point.scoreB,
            setNumber: point.setNumber || timeline.numero || null,
            server: point.server || null,
        }));

        const events = timeline.events.map((event) => ({
            ...event,
            x: event.x,
            y: event.y,
            scoreA: event.scoreA,
            scoreB: event.scoreB,
            setNumber: event.setNumber || timeline.numero || null,
        }));

        const bounds = getYBounds(points, events);

        const backdropPlugin = {
            id: `momentum-backdrop-${canvasId}`,
            beforeDatasetsDraw(chart) {
                const { ctx, chartArea, scales } = chart;
                if (!chartArea || !scales || !scales.x || !scales.y) return;

                if (isMatchChart && setSegments.length > 0) {
                    setSegments.forEach((segment, idx) => {
                        const startPx = scales.x.getPixelForValue(segment.startX);
                        const endPx = scales.x.getPixelForValue(segment.endX);
                        const left = Math.max(chartArea.left, Math.min(startPx, endPx));
                        const right = Math.min(chartArea.right, Math.max(startPx, endPx));

                        if (right > left) {
                            ctx.save();
                            ctx.fillStyle = idx % 2 === 0 ? colors.teamA : colors.teamB;
                            ctx.globalAlpha = 0.06;
                            ctx.fillRect(left, chartArea.top, right - left, chartArea.bottom - chartArea.top);
                            ctx.restore();

                            ctx.save();
                            ctx.fillStyle = 'rgba(139, 146, 168, 0.65)';
                            ctx.font = '600 10px ui-sans-serif, system-ui, sans-serif';
                            ctx.textAlign = 'center';
                            ctx.textBaseline = 'top';
                            ctx.fillText(`Set ${segment.numero}`, left + ((right - left) / 2), chartArea.top + 6);
                            ctx.restore();
                        }

                        if (idx > 0) {
                            const sepX = scales.x.getPixelForValue(segment.startX);
                            if (sepX >= chartArea.left && sepX <= chartArea.right) {
                                ctx.save();
                                ctx.strokeStyle = 'rgba(245, 158, 11, 0.38)';
                                ctx.lineWidth = 1.1;
                                ctx.setLineDash([4, 3]);
                                ctx.beginPath();
                                ctx.moveTo(sepX, chartArea.top);
                                ctx.lineTo(sepX, chartArea.bottom);
                                ctx.stroke();
                                ctx.restore();
                            }
                        }
                    });
                }

                const zeroY = scales.y.getPixelForValue(0);
                const topY = chartArea.top + ((zeroY - chartArea.top) * 0.5);
                const bottomY = zeroY + ((chartArea.bottom - zeroY) * 0.5);
                const textX = chartArea.left + 8;
                const fontSize = Math.max(11, Math.min(16, Math.round((chartArea.bottom - chartArea.top) / 16)));

                ctx.save();
                ctx.font = `700 ${fontSize}px ui-sans-serif, system-ui, sans-serif`;
                ctx.textAlign = 'left';
                ctx.textBaseline = 'middle';
                ctx.globalAlpha = 0.22;
                ctx.fillStyle = colors.teamA;
                ctx.fillText(shorten(teamNames.A, 28), textX, topY);
                ctx.fillStyle = colors.teamB;
                ctx.fillText(shorten(teamNames.B, 28), textX, bottomY);
                ctx.restore();
            },
        };

        const datasets = [
            {
                type: 'line',
                label: title,
                data: points,
                borderColor: colors.gold,
                backgroundColor: 'rgba(245, 158, 11, 0.16)',
                fill: true,
                tension: 0.35,
                cubicInterpolationMode: 'monotone',
                pointRadius: 0,
                pointHoverRadius: 0,
                borderWidth: 2.5,
                parsing: false,
            },
            ...buildEventDatasets(events, bounds),
        ];

        const chart = new Chart(canvas, {
            type: 'line',
            data: { datasets },
            plugins: [backdropPlugin],
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: {
                    duration: 600,
                    easing: 'easeOutQuart',
                },
                interaction: {
                    mode: 'nearest',
                    intersect: false,
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        displayColors: false,
                        backgroundColor: 'rgba(10, 14, 23, 0.95)',
                        borderColor: 'rgba(42, 48, 80, 0.9)',
                        borderWidth: 1,
                        titleColor: '#e8eaf0',
                        bodyColor: '#c7cedf',
                        callbacks: {
                            title(items) {
                                if (!items.length) return '';
                                const item = items[0];
                                if (item.dataset.momentumEvent) {
                                    return `${item.raw.team === 'A' ? teamNames.A : teamNames.B}`;
                                }
                                const setLabel = item.raw.setNumber ? ` · Set ${item.raw.setNumber}` : '';
                                return `Point ${item.raw.x}${setLabel}`;
                            },
                            label(context) {
                                if (context.dataset.momentumEvent) {
                                    const raw = context.raw;
                                    const label = raw.eventKind === 'timeout' ? 'Temps mort' : 'Changement';
                                    const lines = [`${label} à ${raw.scoreA}-${raw.scoreB}`];
                                    if (raw.decisionId) {
                                        lines.push(`Décision: ${raw.decisionId}`);
                                    }
                                    if (raw.impactScore !== null && raw.impactScore !== undefined) {
                                        lines.push(`Impact: ${signed(raw.impactScore, 1)}`);
                                    }
                                    if (raw.trendDeltaWinRatePct !== null && raw.trendDeltaWinRatePct !== undefined) {
                                        lines.push(`Δ tendance: ${signed(raw.trendDeltaWinRatePct, 1)} pts`);
                                    }
                                    if (raw.confidencePct !== null && raw.confidencePct !== undefined) {
                                        lines.push(`Confiance: ${Number(raw.confidencePct).toFixed(1)}%`);
                                    }
                                    return lines;
                                }
                                const raw = context.raw;
                                const score = `${raw.scoreA}-${raw.scoreB}`;
                                const gap = `${raw.y > 0 ? '+' : ''}${raw.y}`;
                                const lines = [`Score: ${score}`, `Écart: ${gap}`];
                                const serverLabel = formatServerLabel(raw.server);
                                if (serverLabel) lines.push(`Service: ${serverLabel}`);
                                return lines;
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        type: 'linear',
                        title: {
                            display: true,
                            text: xLabel,
                            color: colors.text,
                            font: { size: 11, weight: 600 },
                        },
                        grid: { color: colors.grid },
                        ticks: {
                            color: colors.textMuted,
                            stepSize: Math.max(1, Math.ceil(points.length / 14)),
                        },
                    },
                    y: {
                        min: bounds.min,
                        max: bounds.max,
                        title: {
                            display: true,
                            text: `Écart (${teamNames.A} − ${teamNames.B})`,
                            color: colors.text,
                            font: { size: 11, weight: 600 },
                        },
                        grid: {
                            color(ctx) {
                                return ctx.tick.value === 0 ? 'rgba(245, 158, 11, 0.45)' : colors.grid;
                            },
                            lineWidth(ctx) {
                                return ctx.tick.value === 0 ? 1.4 : 1;
                            },
                        },
                        ticks: {
                            color: colors.textMuted,
                            callback(value) {
                                const num = Number(value);
                                if (Number.isNaN(num)) return value;
                                return num > 0 ? `+${num}` : `${num}`;
                            },
                        },
                    },
                },
            },
        });

        charts.push(chart);
        diag.chartsBuilt += 1;
    }

    function buildMatchTimeline(setTimelines) {
        let offsetX = 0;
        let cumA = 0;
        let cumB = 0;

        const points = [];
        const events = [];
        const setSegments = [];

        setTimelines.forEach((timeline, idx) => {
            const setStartX = offsetX;
            const baseDiff = cumA - cumB;

            timeline.points.forEach((point, pointIdx) => {
                if (idx > 0 && pointIdx === 0) return;
                points.push({
                    x: setStartX + point.x,
                    y: baseDiff + point.y,
                    scoreA: cumA + point.scoreA,
                    scoreB: cumB + point.scoreB,
                    setNumber: timeline.numero,
                    server: point.server || null,
                });
            });

            timeline.events.forEach((event) => {
                events.push({
                    ...event,
                    x: setStartX + event.x,
                    y: baseDiff + event.y,
                    scoreA: cumA + event.scoreA,
                    scoreB: cumB + event.scoreB,
                    setNumber: timeline.numero,
                });
            });

            const setEndX = setStartX + timeline.finalA + timeline.finalB;
            setSegments.push({
                numero: timeline.numero,
                startX: setStartX,
                endX: setEndX,
            });

            offsetX = setEndX;
            cumA += timeline.finalA;
            cumB += timeline.finalB;
        });

        if (points.length === 0) {
            points.push({ x: 0, y: 0, scoreA: 0, scoreB: 0, setNumber: null, server: null });
        }

        return { points, events, setSegments };
    }

    function renderSetCharts(setTimelinesByNumero) {
        Object.entries(setTimelinesByNumero).forEach(([numero, timeline]) => {
            createMomentumChart(
                `set-momentum-${numero}`,
                `Set ${numero}`,
                timeline,
                'Points joués dans le set'
            );
        });
    }

    function renderMatchChart(setTimelines) {
        const matchTimeline = buildMatchTimeline(setTimelines);
        createMomentumChart(
            'match-momentum-total',
            'Match',
            matchTimeline,
            'Points joués cumulés',
            {
                isMatchChart: true,
                setSegments: matchTimeline.setSegments,
            }
        );
    }

    function renderCoachDecisionInsights() {
        const card = document.getElementById('coach-decisions-card');
        if (!card) return;

        const emptyNode = document.getElementById('coach-decisions-empty');
        const contentNode = document.getElementById('coach-decisions-content');
        const tbody = document.getElementById('coach-decisions-body');

        const analysis = coachAnalysis && typeof coachAnalysis === 'object' ? coachAnalysis : null;
        const decisions = analysis && Array.isArray(analysis.decisions) ? analysis.decisions : [];

        const showEmpty = (message) => {
            if (emptyNode) {
                emptyNode.textContent = message;
                emptyNode.style.display = 'block';
            }
            if (contentNode) {
                contentNode.style.display = 'none';
            }
        };

        if (!analysis || decisions.length === 0) {
            pushCheck('coach decisions', false, 'No decision payload');
            showEmpty('Aucune décision exploitable pour l\'analyse avant/après.');
            return;
        }

        pushCheck('coach decisions', true, `count=${decisions.length}`);

        const setText = (id, value) => {
            const node = document.getElementById(id);
            if (node) node.textContent = String(value);
        };

        setText('coach-decisions-total', analysis.total_decisions || decisions.length);
        setText('coach-decisions-subs', analysis.total_substitutions || 0);
        setText('coach-decisions-timeouts', analysis.total_timeouts || 0);
        setText('coach-decisions-average', signed(analysis.average_impact_score || 0, 1));

        const byTeam = analysis.by_team || {};
        const summarizeTeam = (side) => {
            const bucket = byTeam[side] || {};
            const count = Number(bucket.count || 0);
            const positive = Number(bucket.positive || 0);
            const negative = Number(bucket.negative || 0);
            const average = signed(bucket.average_impact_score || 0, 1);
            return `${count} décision(s) · +${positive} / -${negative} · Impact moyen ${average}`;
        };

        setText('coach-team-a-summary', summarizeTeam('A'));
        setText('coach-team-b-summary', summarizeTeam('B'));

        if (tbody) {
            tbody.innerHTML = decisions.map((decision) => {
                const isSub = decision.type === 'sub';
                const beforeRate = Number(decision.trend_before && decision.trend_before.win_rate_pct || 0);
                const afterRate = Number(decision.trend_after && decision.trend_after.win_rate_pct || 0);
                const deltaRate = Number(decision.trend_delta && decision.trend_delta.win_rate_pct || 0);
                const confidence = Number(decision.confidence_pct || 0);
                const impactScore = Number(decision.impact_score || 0);

                const decisionMeta = isSub
                    ? `↑ ${escapeHtml(decision.entrant || '?')} / ↓ ${escapeHtml(decision.sortant || '?')}`
                    : 'Temps mort';

                return `
                    <tr>
                        <td>
                            <div class="coach-decision-id">${escapeHtml(decision.id || '')}</div>
                            <div class="coach-decision-type ${isSub ? 'sub' : 'timeout'}">${isSub ? 'Changement' : 'Temps mort'} · ${escapeHtml(decision.team_name || decision.team || '')}</div>
                            <div class="text-xs mt-1" style="color: var(--text-secondary);">${decisionMeta}</div>
                        </td>
                        <td class="text-center">${escapeHtml(decision.set_numero || '')}</td>
                        <td class="text-center font-mono">${escapeHtml(`${decision.score_a || 0}-${decision.score_b || 0}`)}</td>
                        <td class="text-center">${beforeRate.toFixed(1)}%</td>
                        <td class="text-center">${afterRate.toFixed(1)}%</td>
                        <td class="text-center ${deltaRate >= 0 ? 'coach-impact-positive' : 'coach-impact-negative'}">${signed(deltaRate, 1)} pts</td>
                        <td class="text-center coach-impact-cell ${coachImpactClass(impactScore)}">${signed(impactScore, 1)}</td>
                        <td class="text-center">${confidence.toFixed(1)}%</td>
                    </tr>
                `;
            }).join('');
        }

        if (emptyNode) {
            emptyNode.style.display = 'none';
        }
        if (contentNode) {
            contentNode.style.display = 'block';
        }

        if (!chartAvailable) {
            pushCheck('coach charts', false, 'Chart.js unavailable for coach charts');
            return;
        }

        const labels = decisions.map((_, idx) => `D${idx + 1}`);
        const decisionTitles = decisions.map((decision) => `${decision.id || ''} (${decision.type === 'sub' ? 'Changement' : 'Temps mort'})`);

        const impactCtx = document.getElementById('coach-impact-chart');
        if (impactCtx) {
            const impactScores = decisions.map((decision) => Number(decision.impact_score || 0));
            const impactChart = new Chart(impactCtx, {
                type: 'bar',
                data: {
                    labels,
                    datasets: [
                        {
                            label: 'Impact',
                            data: impactScores,
                            borderWidth: 1,
                            borderRadius: 7,
                            backgroundColor: impactScores.map((value) => {
                                if (value >= 12) return 'rgba(34, 197, 94, 0.62)';
                                if (value <= -12) return 'rgba(239, 68, 68, 0.62)';
                                return 'rgba(245, 158, 11, 0.62)';
                            }),
                            borderColor: impactScores.map((value) => {
                                if (value >= 12) return '#22c55e';
                                if (value <= -12) return '#ef4444';
                                return '#f59e0b';
                            }),
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            min: -100,
                            max: 100,
                            grid: {
                                color(ctx) {
                                    return Number(ctx.tick.value) === 0 ? 'rgba(245, 158, 11, 0.45)' : colors.grid;
                                },
                            },
                            ticks: {
                                color: colors.textMuted,
                                callback(value) {
                                    return signed(value, 0);
                                },
                            },
                        },
                        x: {
                            grid: { display: false },
                            ticks: { color: colors.textMuted },
                        },
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                title(items) {
                                    if (!items.length) return '';
                                    const idx = items[0].dataIndex;
                                    return decisionTitles[idx] || labels[idx];
                                },
                                label(context) {
                                    const d = decisions[context.dataIndex] || {};
                                    const trendDelta = Number(d.trend_delta && d.trend_delta.win_rate_pct || 0);
                                    const confidence = Number(d.confidence_pct || 0);
                                    return [
                                        `Impact: ${signed(context.raw, 1)}`,
                                        `Δ tendance: ${signed(trendDelta, 1)} pts`,
                                        `Confiance: ${confidence.toFixed(1)}%`,
                                    ];
                                },
                            },
                        },
                    },
                },
            });
            charts.push(impactChart);
            diag.chartsBuilt += 1;
        }

        const trendCtx = document.getElementById('coach-trend-chart');
        if (trendCtx) {
            const trendChart = new Chart(trendCtx, {
                type: 'line',
                data: {
                    labels,
                    datasets: [
                        {
                            label: 'Avant (win rate %)',
                            data: decisions.map((decision) => Number(decision.trend_before && decision.trend_before.win_rate_pct || 0)),
                            borderColor: '#38bdf8',
                            backgroundColor: 'rgba(56, 189, 248, 0.16)',
                            tension: 0.3,
                            pointRadius: 3,
                            yAxisID: 'y',
                        },
                        {
                            label: 'Après (win rate %)',
                            data: decisions.map((decision) => Number(decision.trend_after && decision.trend_after.win_rate_pct || 0)),
                            borderColor: '#22c55e',
                            backgroundColor: 'rgba(34, 197, 94, 0.16)',
                            tension: 0.3,
                            pointRadius: 3,
                            yAxisID: 'y',
                        },
                        {
                            type: 'bar',
                            label: 'Δ tendance (pts)',
                            data: decisions.map((decision) => Number(decision.trend_delta && decision.trend_delta.win_rate_pct || 0)),
                            borderColor: '#a855f7',
                            backgroundColor: 'rgba(168, 85, 247, 0.22)',
                            borderWidth: 1,
                            borderRadius: 6,
                            yAxisID: 'y1',
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            min: 0,
                            max: 100,
                            ticks: {
                                color: colors.textMuted,
                                callback(value) {
                                    return `${value}%`;
                                },
                            },
                            grid: { color: colors.grid },
                        },
                        y1: {
                            min: -100,
                            max: 100,
                            position: 'right',
                            ticks: {
                                color: colors.textMuted,
                                callback(value) {
                                    return `${signed(value, 0)} pts`;
                                },
                            },
                            grid: { drawOnChartArea: false },
                        },
                        x: {
                            ticks: { color: colors.textMuted },
                            grid: { display: false },
                        },
                    },
                    plugins: {
                        legend: {
                            labels: { color: colors.text },
                        },
                        tooltip: {
                            callbacks: {
                                title(items) {
                                    if (!items.length) return '';
                                    const idx = items[0].dataIndex;
                                    return decisionTitles[idx] || labels[idx];
                                },
                            },
                        },
                    },
                },
            });
            charts.push(trendChart);
            diag.chartsBuilt += 1;
        }
    }

    function installResizeHooks() {
        const scheduleResize = () => {
            setTimeout(() => {
                charts.forEach((chart) => chart.resize());
            }, 80);
        };

        document.querySelectorAll('.pagination-btn').forEach((btn) => {
            btn.addEventListener('click', scheduleResize);
        });

        document.querySelectorAll('button').forEach((btn) => {
            const text = (btn.textContent || '').trim().toLowerCase();
            if (
                text.includes('sets')
                || text.includes('résumé')
                || text.includes('statistiques')
                || text.includes('équipes')
                || text.includes('joueurs')
            ) {
                btn.addEventListener('click', scheduleResize);
            }
        });

        window.addEventListener('resize', scheduleResize);
    }

    function init() {
        try {
            renderCoachDecisionInsights();
            installResizeHooks();

            if (!shouldRenderMomentum) {
                if (!chartAvailable) {
                    setHealthMessage('Visuel momentum non disponible: Chart.js non chargé.', true);
                    publishDiag('ready', 'chart_missing');
                } else if (!hasTimelineFlag) {
                    setHealthMessage('Visuel momentum non disponible: détails de points non détectés.', true);
                    publishDiag('ready', 'flag_false');
                } else {
                    setHealthMessage('Visuel momentum non disponible: données momentum absentes.', true);
                    publishDiag('ready', 'no_momentum_data');
                }
                return;
            }

            const setTimelines = [];
            const setTimelinesByNumero = {};

            momentumSets.forEach((setData) => {
                const timeline = normalizeSetTimeline(setData);
                if (!timeline) return;
                setTimelines.push(timeline);
                setTimelinesByNumero[String(setData.numero)] = timeline;
            });

            pushCheck('set timelines', setTimelines.length > 0, `count=${setTimelines.length}`);
            if (setTimelines.length === 0) {
                setHealthMessage('Visuel non construit: aucune timeline de set exploitable.', true);
                publishDiag('failed', 'no_set_timelines');
                return;
            }

            renderSetCharts(setTimelinesByNumero);
            renderMatchChart(setTimelines);

            setHealthMessage(`Visuel construit (${diag.chartsBuilt} graphique(s)).`, false);
            publishDiag('ready', 'ok');
        } catch (err) {
            const message = err && err.message ? err.message : String(err);
            setHealthMessage(`Erreur visuel: ${message}`, true);
            publishDiag('error', 'exception', message);
            console.error('[PyVolley Momentum] build failed:', err);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
