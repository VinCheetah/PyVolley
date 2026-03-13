/* ═══════════════════════════════════════════════════════════════
   PyVolley — Match Simulation Viewer
   Inline replay of volleyball match events, court rendering,
   player positions, animations, and keyboard controls.

   Expects window.PYVOLLEY_MATCH_DATA to be set before this script loads.
   ═══════════════════════════════════════════════════════════════ */
(function() {
    'use strict';

    const MATCH = window.PYVOLLEY_MATCH_DATA;
    if (!MATCH || !MATCH.sets || MATCH.sets.length === 0) return;

    // ── État global ──
    const sim = {
        currentSet: 0, currentEvent: -1,
        playing: false, playTimer: null, speed: 5,
        scoreA: 0, scoreB: 0, setsA: 0, setsB: 0,
        currentServer: null,
        positionsA: {}, positionsB: {},
        timelines: [],
    };

    // ── Positions terrain ──
    const COURT_POS = {
        A: { 1:{x:112,y:90}, 6:{x:250,y:90}, 5:{x:388,y:90}, 2:{x:112,y:250}, 3:{x:250,y:250}, 4:{x:388,y:250} },
        B: { 4:{x:112,y:430}, 3:{x:250,y:430}, 2:{x:388,y:430}, 5:{x:112,y:590}, 6:{x:250,y:590}, 1:{x:388,y:590} },
    };

    // ── Utilitaires ──
    function strip(v) { return String(v).replace(/^0+/, '') || v; }
    function short(n) { if (!n) return ''; const w = n.split(/\s+/); return w.length <= 2 ? n : w.slice(0,2).join(' '); }
    function getPlayer(team, num) {
        const eq = team === 'A' ? MATCH.equipe_a : MATCH.equipe_b;
        const sn = strip(num);
        return eq.joueurs.find(j => strip(j.numero) === sn);
    }
    function pName(p) { if (!p) return '?'; return (p.prenom ? p.prenom.charAt(0)+'. ' : '') + p.nom; }
    function clonePos(o) { return {1:o[1],2:o[2],3:o[3],4:o[4],5:o[5],6:o[6]}; }
    function rotate(pos) { const old1=pos[1]; pos[1]=pos[2]; pos[2]=pos[3]; pos[3]=pos[4]; pos[4]=pos[5]; pos[5]=pos[6]; pos[6]=old1; }

    // ══════════════════════════════════════════════
    // TIMELINE RECONSTRUCTION
    // ══════════════════════════════════════════════
    function buildTimeline(setData) {
        const events = [];
        const srvInit = setData.service_initial;
        const formA = setData.formation_a || {};
        const formB = setData.formation_b || {};

        // Set start
        events.push({
            type: 'set_start', set: setData.numero, scoreA: 0, scoreB: 0,
            server: srvInit,
            formationA: Object.assign({}, formA),
            formationB: Object.assign({}, formB),
            desc: 'Début du Set ' + setData.numero,
            detail: 'Service : ' + (srvInit === 'A' ? short(MATCH.equipe_a.nom) : short(MATCH.equipe_b.nom)),
            icon: '🏐'
        });

        // Services data (from core model if available)
        const servicesA = setData.services_a || {};
        const servicesB = setData.services_b || {};
        const hasServices = Object.keys(servicesA).length > 0 || Object.keys(servicesB).length > 0;

        // Collect non-point events
        const otherEvts = [];
        (setData.changements_a || []).forEach(c => otherEvts.push({
            type:'sub', team:'A', scoreA:c.score_a, scoreB:c.score_b,
            entrant:c.joueur_entrant, sortant:c.joueur_sortant, position:c.position
        }));
        (setData.changements_b || []).forEach(c => otherEvts.push({
            type:'sub', team:'B', scoreA:c.score_a, scoreB:c.score_b,
            entrant:c.joueur_entrant, sortant:c.joueur_sortant, position:c.position
        }));
        (setData.timeouts_a || []).forEach(t => otherEvts.push({type:'timeout', team:'A', scoreA:t.score_a, scoreB:t.score_b}));
        (setData.timeouts_b || []).forEach(t => otherEvts.push({type:'timeout', team:'B', scoreA:t.score_a, scoreB:t.score_b}));

        // Sanctions
        (MATCH.sanctions || []).forEach(s => {
            if (s.set_numero === setData.numero)
                otherEvts.push({type:'sanction', team:s.equipe, scoreA:s.score_a, scoreB:s.score_b, sanctionType:s.type, joueurNumero:s.joueur_numero});
        });

        // Initial positions
        const posA = {}, posB = {};
        for (let p = 1; p <= 6; p++) {
            posA[p] = formA['position_' + p] || '';
            posB[p] = formB['position_' + p] || '';
        }

        let scoreA = 0, scoreB = 0;
        let currentSrv = srvInit;
        const finalA = setData.score_a, finalB = setData.score_b;

        function insertOthers(sA, sB) {
            const matching = [];
            for (let i = otherEvts.length - 1; i >= 0; i--) {
                if (otherEvts[i].scoreA === sA && otherEvts[i].scoreB === sB)
                    matching.push(otherEvts.splice(i, 1)[0]);
            }
            matching.reverse();
            matching.forEach(e => {
                if (e.type === 'timeout') {
                    const tn = e.team === 'A' ? short(MATCH.equipe_a.nom) : short(MATCH.equipe_b.nom);
                    events.push({type:'timeout', team:e.team, set:setData.numero, scoreA:e.scoreA, scoreB:e.scoreB,
                        desc:'Temps mort — '+tn, detail:e.scoreA+' – '+e.scoreB, icon:'⏸️',
                        posA:clonePos(posA), posB:clonePos(posB), server:currentSrv});
                } else if (e.type === 'sub') {
                    const tn = e.team === 'A' ? short(MATCH.equipe_a.nom) : short(MATCH.equipe_b.nom);
                    const positions = e.team === 'A' ? posA : posB;
                    for (let p = 1; p <= 6; p++) {
                        if (strip(positions[p]) === strip(e.sortant)) { positions[p] = e.entrant; break; }
                    }
                    const pIn = getPlayer(e.team, e.entrant), pOut = getPlayer(e.team, e.sortant);
                    events.push({type:'substitution', team:e.team, set:setData.numero, scoreA:e.scoreA, scoreB:e.scoreB,
                        entrant:e.entrant, sortant:e.sortant,
                        desc:'Changement '+tn,
                        detail:'#'+strip(e.sortant||'')+' '+pName(pOut)+' ➡ #'+strip(e.entrant)+' '+pName(pIn),
                        icon:'🔄', posA:clonePos(posA), posB:clonePos(posB), server:currentSrv});
                } else if (e.type === 'sanction') {
                    const tn = e.team === 'A' ? short(MATCH.equipe_a.nom) : short(MATCH.equipe_b.nom);
                    const sanctionNames = {A:'Avertissement',P:'Pénalité',E:'Expulsion',D:'Disqualification'};
                    const player = e.joueurNumero ? getPlayer(e.team, e.joueurNumero) : null;
                    events.push({type:'sanction', team:e.team, set:setData.numero, scoreA:e.scoreA, scoreB:e.scoreB,
                        sanctionType:e.sanctionType,
                        desc:(sanctionNames[e.sanctionType]||'Sanction')+' — '+tn,
                        detail:player ? '#'+strip(e.joueurNumero)+' '+pName(player) : '',
                        icon:e.sanctionType==='A'?'🟡':'🔴',
                        posA:clonePos(posA), posB:clonePos(posB), server:currentSrv});
                }
            });
        }

        // ── Point-by-point reconstruction ──
        if (hasServices) {
            function getServiceTurns(services) {
                const posData = {};
                for (const pos in services) { posData[parseInt(pos)] = services[pos].slice(); }
                return posData;
            }
            function buildOrderedTurns(posData, isInitialServer) {
                const startPos = isInitialServer ? 1 : 2;
                const ordered = [];
                const counters = {};
                for (let p = 1; p <= 6; p++) counters[p] = 0;
                let totalTurns = 0;
                for (const k in posData) totalTurns += posData[k].length;
                let pos = startPos;
                for (let i = 0; i < totalTurns; i++) {
                    const ps = posData[pos];
                    if (ps && counters[pos] < ps.length) {
                        ordered.push({position:pos, endScore:ps[counters[pos]]});
                        counters[pos]++;
                    } else {
                        let found = false;
                        for (let attempt = 0; attempt < 6; attempt++) {
                            pos = (pos % 6) + 1;
                            const ps2 = posData[pos];
                            if (ps2 && counters[pos] < ps2.length) {
                                ordered.push({position:pos, endScore:ps2[counters[pos]]});
                                counters[pos]++;
                                found = true; break;
                            }
                        }
                        if (!found) break;
                    }
                    pos = (pos % 6) + 1;
                }
                return ordered;
            }

            const orderedA = buildOrderedTurns(getServiceTurns(servicesA), srvInit === 'A');
            const orderedB = buildOrderedTurns(getServiceTurns(servicesB), srvInit === 'B');
            let idxA = 0, idxB = 0;
            let safety = 0;

            while ((scoreA < finalA || scoreB < finalB) && safety < 500) {
                safety++;
                if (currentSrv === 'A') {
                    const turnA = orderedA[idxA];
                    if (!turnA) {
                        while (scoreA < finalA && safety < 500) {
                            safety++; scoreA++;
                            insertOthers(scoreA, scoreB);
                            events.push({type:'point',team:'A',set:setData.numero,scoreA,scoreB,desc:'Point '+short(MATCH.equipe_a.nom),detail:scoreA+' – '+scoreB,icon:'🔵',posA:clonePos(posA),posB:clonePos(posB),server:'A'});
                        }
                        break;
                    }
                    const endScoreA = turnA.endScore;
                    while (scoreA < endScoreA && safety < 500) {
                        safety++; scoreA++;
                        insertOthers(scoreA, scoreB);
                        events.push({type:'point',team:'A',set:setData.numero,scoreA,scoreB,desc:'Point '+short(MATCH.equipe_a.nom),detail:scoreA+' – '+scoreB,icon:'🔵',posA:clonePos(posA),posB:clonePos(posB),server:'A'});
                    }
                    scoreB++;
                    if (scoreB > finalB) { scoreB = finalB; break; }
                    if (scoreA > finalA) { scoreA = finalA; break; }
                    idxA++; currentSrv = 'B';
                    rotate(posB);
                    insertOthers(scoreA, scoreB);
                    if (scoreB <= finalB) events.push({type:'point',team:'B',set:setData.numero,scoreA,scoreB,sideout:true,rotatedTeam:'B',desc:'Point '+short(MATCH.equipe_b.nom),detail:scoreA+' – '+scoreB,icon:'🔴',posA:clonePos(posA),posB:clonePos(posB),server:'B'});
                    if (scoreA >= finalA && scoreB >= finalB) break;
                } else {
                    const turnB = orderedB[idxB];
                    if (!turnB) {
                        while (scoreB < finalB && safety < 500) {
                            safety++; scoreB++;
                            insertOthers(scoreA, scoreB);
                            events.push({type:'point',team:'B',set:setData.numero,scoreA,scoreB,desc:'Point '+short(MATCH.equipe_b.nom),detail:scoreA+' – '+scoreB,icon:'🔴',posA:clonePos(posA),posB:clonePos(posB),server:'B'});
                        }
                        break;
                    }
                    const endScoreB = turnB.endScore;
                    while (scoreB < endScoreB && safety < 500) {
                        safety++; scoreB++;
                        insertOthers(scoreA, scoreB);
                        events.push({type:'point',team:'B',set:setData.numero,scoreA,scoreB,desc:'Point '+short(MATCH.equipe_b.nom),detail:scoreA+' – '+scoreB,icon:'🔴',posA:clonePos(posA),posB:clonePos(posB),server:'B'});
                    }
                    scoreA++;
                    if (scoreA > finalA) { scoreA = finalA; break; }
                    if (scoreB > finalB) { scoreB = finalB; break; }
                    idxB++; currentSrv = 'A';
                    rotate(posA);
                    insertOthers(scoreA, scoreB);
                    if (scoreA <= finalA) events.push({type:'point',team:'A',set:setData.numero,scoreA,scoreB,sideout:true,rotatedTeam:'A',desc:'Point '+short(MATCH.equipe_a.nom),detail:scoreA+' – '+scoreB,icon:'🔵',posA:clonePos(posA),posB:clonePos(posB),server:'A'});
                    if (scoreA >= finalA && scoreB >= finalB) break;
                }
            }
        } else {
            // Simplified alternation when no services data
            let safety = 0;
            while ((scoreA < finalA || scoreB < finalB) && safety < 500) {
                safety++;
                if (currentSrv === 'A') {
                    scoreA++; if (scoreA > finalA) { scoreA = finalA; break; }
                    insertOthers(scoreA, scoreB);
                    events.push({type:'point',team:'A',set:setData.numero,scoreA,scoreB,desc:'Point '+short(MATCH.equipe_a.nom),detail:scoreA+' – '+scoreB,icon:'🔵',posA:clonePos(posA),posB:clonePos(posB),server:'A'});
                    if (scoreA < finalA || scoreB < finalB) {
                        scoreB++; if (scoreB > finalB) { scoreB = finalB; break; }
                        currentSrv = 'B'; rotate(posB);
                        insertOthers(scoreA, scoreB);
                        events.push({type:'point',team:'B',set:setData.numero,scoreA,scoreB,sideout:true,rotatedTeam:'B',desc:'Point '+short(MATCH.equipe_b.nom),detail:scoreA+' – '+scoreB,icon:'🔴',posA:clonePos(posA),posB:clonePos(posB),server:'B'});
                    }
                } else {
                    scoreB++; if (scoreB > finalB) { scoreB = finalB; break; }
                    insertOthers(scoreA, scoreB);
                    events.push({type:'point',team:'B',set:setData.numero,scoreA,scoreB,desc:'Point '+short(MATCH.equipe_b.nom),detail:scoreA+' – '+scoreB,icon:'🔴',posA:clonePos(posA),posB:clonePos(posB),server:'B'});
                    if (scoreA < finalA || scoreB < finalB) {
                        scoreA++; if (scoreA > finalA) { scoreA = finalA; break; }
                        currentSrv = 'A'; rotate(posA);
                        insertOthers(scoreA, scoreB);
                        events.push({type:'point',team:'A',set:setData.numero,scoreA,scoreB,sideout:true,rotatedTeam:'A',desc:'Point '+short(MATCH.equipe_a.nom),detail:scoreA+' – '+scoreB,icon:'🔵',posA:clonePos(posA),posB:clonePos(posB),server:'A'});
                    }
                }
            }
        }

        // Set end
        const winner = finalA > finalB ? 'A' : 'B';
        const winnerName = winner === 'A' ? MATCH.equipe_a.nom : MATCH.equipe_b.nom;
        events.push({type:'set_end', set:setData.numero, scoreA:finalA, scoreB:finalB, winner,
            desc:'Fin du Set '+setData.numero,
            detail:finalA+' – '+finalB+' — '+short(winnerName)+' remporte le set',
            icon:'🏆', posA:clonePos(posA), posB:clonePos(posB), server:currentSrv,
            duration:setData.duree_minutes});

        return events;
    }

    function buildAllTimelines() { sim.timelines = MATCH.sets.map(s => buildTimeline(s)); }

    // ══════════════════════════════════════════════
    // INITIALISATION UI
    // ══════════════════════════════════════════════
    function initUI() {
        const courtA = document.getElementById('sim-court-label-a');
        const courtB = document.getElementById('sim-court-label-b');
        if (courtA) courtA.textContent = short(MATCH.equipe_a.nom).toUpperCase();
        if (courtB) courtB.textContent = short(MATCH.equipe_b.nom).toUpperCase();

        // Set chips
        const chipsDiv = document.getElementById('sim-sets-chips');
        chipsDiv.innerHTML = '';
        MATCH.sets.forEach((_, i) => {
            const chip = document.createElement('span');
            chip.className = 'sim-set-chip';
            chip.id = 'sim-chip-' + i;
            chip.textContent = '-';
            chipsDiv.appendChild(chip);
        });
    }

    // ══════════════════════════════════════════════
    // COURT RENDERING
    // ══════════════════════════════════════════════
    function renderCourt(animate, subInfo) {
        const group = document.getElementById('sim-players-group');
        const desired = {};

        for (let pos = 1; pos <= 6; pos++) {
            const numA = sim.positionsA[pos];
            if (numA) {
                const p = getPlayer('A', numA);
                const coord = COURT_POS.A[pos];
                const serving = sim.currentServer === 'A' && pos === 1;
                desired['A-'+strip(numA)] = {team:'A',pos,numero:numA,player:p,coord,serving,libero:p&&p.est_libero};
            }
            const numB = sim.positionsB[pos];
            if (numB) {
                const p = getPlayer('B', numB);
                const coord = COURT_POS.B[pos];
                const serving = sim.currentServer === 'B' && pos === 1;
                desired['B-'+strip(numB)] = {team:'B',pos,numero:numB,player:p,coord,serving,libero:p&&p.est_libero};
            }
        }

        const existing = {};
        group.querySelectorAll('.sim-court-player').forEach(el => { existing[el.id] = el; });

        const subEntrantKey = subInfo ? subInfo.team+'-'+strip(subInfo.entrant) : null;
        const subSortantKey = subInfo ? subInfo.team+'-'+strip(subInfo.sortant) : null;

        // Remove players no longer on court
        for (const id in existing) {
            const key = id.replace('sim-cp-', '');
            if (!desired[key]) {
                const el = existing[id];
                if (animate) {
                    const isSub = subSortantKey && key === subSortantKey;
                    el.classList.add(isSub ? 'sim-sub-leaving' : 'sim-leaving');
                    setTimeout(() => el.remove(), isSub ? 600 : 400);
                } else el.remove();
            }
        }

        // Add or update
        for (const dkey in desired) {
            const info = desired[dkey];
            const elId = 'sim-cp-' + dkey;
            const el = existing[elId];
            if (el) {
                el.setAttribute('transform', 'translate('+info.coord.x+','+info.coord.y+')');
                updatePlayerSVG(el, info);
            } else {
                const g = createPlayerSVG(info);
                g.id = elId;
                group.appendChild(g);
                if (animate) {
                    const isSubIn = subEntrantKey && dkey === subEntrantKey;
                    g.classList.add(isSubIn ? 'sim-sub-entering' : 'sim-entering');
                }
            }
        }
    }

    function createPlayerSVG(info) {
        const ns = 'http://www.w3.org/2000/svg';
        const g = document.createElementNS(ns, 'g');
        g.setAttribute('class', 'sim-court-player');
        g.setAttribute('transform', 'translate('+info.coord.x+','+info.coord.y+')');

        const fill = info.libero ? '#f59e0b' : (info.team === 'A' ? '#3b82f6' : '#ef4444');
        const stroke = info.serving ? '#f59e0b' : (info.team === 'A' ? '#2563eb' : '#dc2626');

        const circle = document.createElementNS(ns, 'circle');
        circle.setAttribute('class', 'player-bg');
        circle.setAttribute('cx', 0); circle.setAttribute('cy', 0); circle.setAttribute('r', 24);
        circle.setAttribute('fill', fill); circle.setAttribute('stroke', stroke);
        circle.setAttribute('stroke-width', info.serving ? 3 : 1.5);
        if (info.serving) circle.setAttribute('filter', 'url(#simGlow)');
        g.appendChild(circle);

        const numT = document.createElementNS(ns, 'text');
        numT.setAttribute('text-anchor','middle'); numT.setAttribute('dy','0.35em');
        numT.setAttribute('fill','white'); numT.setAttribute('font-size','14'); numT.setAttribute('font-weight','800');
        numT.textContent = strip(info.numero);
        g.appendChild(numT);

        if (info.player) {
            const nameT = document.createElementNS(ns, 'text');
            nameT.setAttribute('class','player-name-label');
            nameT.setAttribute('text-anchor','middle'); nameT.setAttribute('y', 38);
            nameT.setAttribute('fill','rgba(255,255,255,0.8)'); nameT.setAttribute('font-size','9'); nameT.setAttribute('font-weight','600');
            nameT.textContent = info.player.nom.length > 10 ? info.player.nom.substring(0,10)+'.' : info.player.nom;
            g.appendChild(nameT);
        }

        // Serve icon
        const srvT = document.createElementNS(ns, 'text');
        srvT.setAttribute('class','serve-icon');
        srvT.setAttribute('text-anchor','middle'); srvT.setAttribute('y',-32);
        srvT.setAttribute('fill','#f59e0b'); srvT.setAttribute('font-size','14');
        srvT.textContent = '🏐';
        srvT.style.opacity = info.serving ? 1 : 0;
        g.appendChild(srvT);

        // Position label
        const posT = document.createElementNS(ns, 'text');
        posT.setAttribute('class','pos-label');
        posT.setAttribute('text-anchor','middle'); posT.setAttribute('y',-30);
        posT.setAttribute('fill','rgba(255,255,255,0.3)'); posT.setAttribute('font-size','8');
        posT.textContent = 'P' + info.pos;
        posT.style.display = info.serving ? 'none' : '';
        g.appendChild(posT);

        return g;
    }

    function updatePlayerSVG(el, info) {
        const circle = el.querySelector('.player-bg');
        if (!circle) return;
        const fill = info.libero ? '#f59e0b' : (info.team === 'A' ? '#3b82f6' : '#ef4444');
        const stroke = info.serving ? '#f59e0b' : (info.team === 'A' ? '#2563eb' : '#dc2626');
        circle.setAttribute('fill', fill);
        circle.setAttribute('stroke', stroke);
        circle.setAttribute('stroke-width', info.serving ? 3 : 1.5);
        if (info.serving) circle.setAttribute('filter', 'url(#simGlow)');
        else circle.removeAttribute('filter');
        const srvIcon = el.querySelector('.serve-icon');
        if (srvIcon) srvIcon.style.opacity = info.serving ? 1 : 0;
        const posLabel = el.querySelector('.pos-label');
        if (posLabel) { posLabel.textContent = 'P'+info.pos; posLabel.style.display = info.serving ? 'none' : ''; }
    }

    // ══════════════════════════════════════════════
    // UI UPDATES
    // ══════════════════════════════════════════════
    function updateScoreboard(sA, sB, animate) {
        const elA = document.getElementById('sim-score-a');
        const elB = document.getElementById('sim-score-b');
        if (animate) {
            if (parseInt(elA.textContent) !== sA) { elA.classList.remove('sim-score-flash'); void elA.offsetWidth; elA.classList.add('sim-score-flash'); }
            if (parseInt(elB.textContent) !== sB) { elB.classList.remove('sim-score-flash'); void elB.offsetWidth; elB.classList.add('sim-score-flash'); }
        }
        elA.textContent = sA;
        elB.textContent = sB;
    }

    function updateService(srv) {
        document.getElementById('sim-serve-a').style.opacity = srv === 'A' ? '1' : '0';
        document.getElementById('sim-serve-b').style.opacity = srv === 'B' ? '1' : '0';
    }

    function updateSetInfo() {
        const sd = MATCH.sets[sim.currentSet];
        document.getElementById('sim-set-label').textContent = 'Set ' + sd.numero + (sd.duree_minutes ? ' • ' + sd.duree_minutes + ' min' : '');
        MATCH.sets.forEach((s, i) => {
            const chip = document.getElementById('sim-chip-' + i);
            if (!chip) return;
            chip.className = 'sim-set-chip';
            if (i < sim.currentSet || (i === sim.currentSet && sim.currentEvent >= sim.timelines[i].length - 1)) {
                chip.textContent = s.score_a + '-' + s.score_b;
                chip.classList.add(s.score_a > s.score_b ? 'won-a' : 'won-b');
            } else if (i === sim.currentSet) {
                chip.textContent = sim.scoreA + '-' + sim.scoreB;
                chip.classList.add('active');
            } else chip.textContent = '-';
        });
        document.querySelectorAll('.sim-set-btn').forEach(b => b.classList.toggle('active', parseInt(b.dataset.set) === sim.currentSet));
    }

    function updateEvent(evt) {
        const el = document.getElementById('sim-event-display');
        if (!evt) {
            el.removeAttribute('data-type');
            el.innerHTML = '<span class="text-lg mr-2">🏐</span><div><div class="text-sm font-semibold">Prêt à démarrer</div><div class="text-xs" style="color:var(--text-secondary)">Utilisez les contrôles pour lancer la simulation</div></div>';
            return;
        }

        if (evt.type === 'point') el.setAttribute('data-type', 'point_' + (evt.team === 'A' ? 'a' : 'b'));
        else if (evt.type === 'timeout') el.setAttribute('data-type', 'timeout');
        else if (evt.type === 'substitution') el.setAttribute('data-type', 'changement');
        else if (evt.type === 'set_start' || evt.type === 'set_end') el.setAttribute('data-type', evt.type);
        else if (evt.type === 'sanction') el.setAttribute('data-type', 'sanction');
        else el.removeAttribute('data-type');

        if (evt.type === 'substitution') {
            const pIn = getPlayer(evt.team, evt.entrant);
            const pOut = getPlayer(evt.team, evt.sortant);
            const tc = evt.team === 'A' ? 'var(--team-a-light)' : 'var(--team-b-light)';
            const tn = evt.team === 'A' ? short(MATCH.equipe_a.nom) : short(MATCH.equipe_b.nom);
            el.innerHTML = '<span class="text-lg mr-2">🔄</span>' +
                '<div><div class="text-sm font-semibold" style="color:'+tc+'">Changement '+tn+'</div>' +
                '<div class="flex items-center gap-2 mt-1 text-xs">' +
                '<span class="sim-sub-badge sim-sub-badge-out">#'+strip(evt.sortant||'')+' '+pName(pOut)+'</span>' +
                '<span style="color:var(--accent-green)">➡</span>' +
                '<span class="sim-sub-badge sim-sub-badge-in">#'+strip(evt.entrant)+' '+pName(pIn)+'</span>' +
                '</div></div>';
        } else {
            const sideout = evt.sideout ? ' <span style="font-size:10px;opacity:0.5">🔃</span>' : '';
            el.innerHTML = '<span class="text-lg mr-2">'+(evt.icon||'')+'</span><div><div class="text-sm font-semibold">'+(evt.desc||'')+sideout+'</div><div class="text-xs" style="color:var(--text-secondary)">'+(evt.detail||'')+'</div></div>';
        }
    }

    function updateProgress() {
        const tl = sim.timelines[sim.currentSet];
        if (!tl) return;
        const total = tl.length, current = sim.currentEvent + 1;
        document.getElementById('sim-progress').textContent = current + ' / ' + total;
        document.getElementById('sim-timeline-fill').style.width = (total > 0 ? (current/total)*100 : 0) + '%';
    }

    // ══════════════════════════════════════════════
    // ANIMATIONS
    // ══════════════════════════════════════════════
    function animatePoint(team) {
        const el = document.getElementById(team === 'A' ? 'sim-flash-a' : 'sim-flash-b');
        el.classList.remove('show');
        void el.offsetWidth;
        el.classList.add('show');
        setTimeout(() => el.classList.remove('show'), 600);
    }

    function animateTimeout(team) {
        const el = document.getElementById('sim-timeout-anim');
        const tn = team === 'A' ? short(MATCH.equipe_a.nom) : short(MATCH.equipe_b.nom);
        el.className = 'sim-timeout-overlay sim-timeout-' + (team === 'A' ? 'a' : 'b');
        el.querySelector('.sim-timeout-icon').textContent = '⏸️';
        el.querySelector('.sim-timeout-team').textContent = tn;
        void el.offsetWidth;
        el.classList.add('show');
        setTimeout(() => el.classList.remove('show'), 1400);
    }

    function animateSubstitution(team, entrant, sortant) {
        const el = document.getElementById('sim-sub-anim');
        el.className = 'sim-sub-overlay sim-sub-' + (team === 'A' ? 'a' : 'b');
        document.getElementById('sim-sub-out-num').textContent = strip(sortant || '?');
        document.getElementById('sim-sub-in-num').textContent = strip(entrant);
        void el.offsetWidth;
        el.classList.add('show');
        setTimeout(() => el.classList.remove('show'), 1200);
    }

    function animateSanction(type) {
        const el = document.getElementById('sim-sanction-anim');
        el.className = 'sim-sanction-card sim-sanction-' + type;
        const symbols = {A:'⚠',P:'🔴',E:'❌',D:'⛔'};
        el.textContent = symbols[type] || '⚠';
        el.classList.add('show');
        setTimeout(() => el.classList.remove('show'), 1200);
    }

    // ══════════════════════════════════════════════
    // NAVIGATION
    // ══════════════════════════════════════════════
    function applyEvent(evt, animate) {
        if (!evt) return;
        if (evt.scoreA !== undefined) sim.scoreA = evt.scoreA;
        if (evt.scoreB !== undefined) sim.scoreB = evt.scoreB;
        if (evt.server) sim.currentServer = evt.server;
        if (evt.posA) sim.positionsA = {1:evt.posA[1],2:evt.posA[2],3:evt.posA[3],4:evt.posA[4],5:evt.posA[5],6:evt.posA[6]};
        if (evt.posB) sim.positionsB = {1:evt.posB[1],2:evt.posB[2],3:evt.posB[3],4:evt.posB[4],5:evt.posB[5],6:evt.posB[6]};

        if (evt.type === 'set_start') {
            if (evt.formationA) for (let p=1;p<=6;p++) sim.positionsA[p] = evt.formationA['position_'+p];
            if (evt.formationB) for (let p=1;p<=6;p++) sim.positionsB[p] = evt.formationB['position_'+p];
        }

        let subInfo = null;
        if (evt.type === 'substitution') subInfo = {team:evt.team, entrant:evt.entrant, sortant:evt.sortant};

        updateScoreboard(sim.scoreA, sim.scoreB, animate);
        updateService(sim.currentServer);
        renderCourt(animate, subInfo);
        updateEvent(evt);
        updateSetInfo();
        updateProgress();

        if (animate) {
            if (evt.type === 'point') animatePoint(evt.team);
            if (evt.type === 'timeout') animateTimeout(evt.team);
            if (evt.type === 'substitution') animateSubstitution(evt.team, evt.entrant, evt.sortant);
            if (evt.type === 'sanction' && evt.sanctionType) animateSanction(evt.sanctionType);
        }
    }

    function goToEvent(idx) {
        const tl = sim.timelines[sim.currentSet];
        if (!tl || idx < 0 || idx >= tl.length) return;
        if (idx < sim.currentEvent) {
            document.getElementById('sim-players-group').innerHTML = '';
            sim.currentEvent = -1; sim.scoreA = 0; sim.scoreB = 0;
            for (let i = 0; i <= idx; i++) { sim.currentEvent = i; applyEvent(tl[i], false); }
        } else {
            for (let i = sim.currentEvent + 1; i <= idx; i++) { sim.currentEvent = i; applyEvent(tl[i], i === idx); }
        }
    }

    function nextEvent() {
        const tl = sim.timelines[sim.currentSet];
        if (!tl) return;
        if (sim.currentEvent < tl.length - 1) { sim.currentEvent++; applyEvent(tl[sim.currentEvent], true); }
        else if (sim.currentSet < MATCH.sets.length - 1) goToSet(sim.currentSet + 1);
        else stopPlaying();
    }

    function prevEvent() {
        if (sim.currentEvent > 0) goToEvent(sim.currentEvent - 1);
        else if (sim.currentSet > 0) {
            const prev = sim.currentSet - 1;
            goToSet(prev);
            goToEvent(sim.timelines[prev].length - 1);
        }
    }

    function goToSet(idx) {
        if (idx < 0 || idx >= MATCH.sets.length) return;
        document.getElementById('sim-players-group').innerHTML = '';
        sim.currentSet = idx; sim.currentEvent = -1; sim.scoreA = 0; sim.scoreB = 0;
        sim.setsA = 0; sim.setsB = 0;
        for (let i = 0; i < idx; i++) {
            if (MATCH.sets[i].score_a > MATCH.sets[i].score_b) sim.setsA++; else sim.setsB++;
        }
        const tl = sim.timelines[idx];
        if (tl && tl.length > 0) { sim.currentEvent = 0; applyEvent(tl[0], false); }
    }

    function goToStart() { stopPlaying(); goToSet(0); }
    function goToEnd() { stopPlaying(); const last = MATCH.sets.length-1; goToSet(last); goToEvent(sim.timelines[last].length-1); }

    // ── Lecture automatique ──
    function getDelay() {
        const speeds = [2000,1500,1200,1000,800,600,450,300,200,100];
        return speeds[sim.speed - 1] || 800;
    }
    function startPlaying() {
        if (sim.playing) return;
        sim.playing = true;
        document.getElementById('sim-btn-play').classList.add('sim-playing');
        document.getElementById('sim-btn-play').textContent = '⏸';
        scheduleNext();
    }
    function stopPlaying() {
        sim.playing = false;
        if (sim.playTimer) clearTimeout(sim.playTimer);
        sim.playTimer = null;
        document.getElementById('sim-btn-play').classList.remove('sim-playing');
        document.getElementById('sim-btn-play').textContent = '▶';
    }
    function scheduleNext() {
        if (!sim.playing) return;
        let delay = getDelay();
        const evt = sim.timelines[sim.currentSet]?.[sim.currentEvent];
        if (evt) {
            if (evt.type === 'set_start' || evt.type === 'set_end') delay *= 3;
            else if (evt.type === 'timeout') delay *= 2.5;
            else if (evt.type === 'substitution') delay *= 2;
            else if (evt.type === 'sanction') delay *= 2;
            else if (evt.sideout) delay *= 1.3;
        }
        sim.playTimer = setTimeout(() => { nextEvent(); if (sim.playing) scheduleNext(); }, delay);
    }
    function togglePlay() { if (sim.playing) stopPlaying(); else startPlaying(); }

    // ── Contrôles ──
    function initControls() {
        document.getElementById('sim-btn-play').addEventListener('click', togglePlay);
        document.getElementById('sim-btn-next').addEventListener('click', nextEvent);
        document.getElementById('sim-btn-prev').addEventListener('click', prevEvent);
        document.getElementById('sim-btn-start').addEventListener('click', goToStart);
        document.getElementById('sim-btn-end').addEventListener('click', goToEnd);

        const slider = document.getElementById('sim-speed');
        const labels = ['0.2×','0.4×','0.6×','0.8×','1.0×','1.5×','2.0×','3.0×','4.0×','5.0×'];
        slider.addEventListener('input', () => {
            sim.speed = parseInt(slider.value);
            document.getElementById('sim-speed-label').textContent = labels[sim.speed-1] || '1.0×';
        });

        document.getElementById('sim-timeline').addEventListener('click', e => {
            const rect = e.currentTarget.getBoundingClientRect();
            const pct = (e.clientX - rect.left) / rect.width;
            const tl = sim.timelines[sim.currentSet];
            if (tl) goToEvent(Math.round(pct * (tl.length - 1)));
        });

        document.querySelectorAll('.sim-set-btn').forEach(btn => {
            btn.addEventListener('click', () => { stopPlaying(); goToSet(parseInt(btn.dataset.set)); });
        });

        // Keyboard shortcuts
        document.addEventListener('keydown', e => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
            const simTab = document.querySelector('[x-show*="simulation"]');
            if (simTab && simTab.style.display === 'none') return;
            switch (e.key) {
                case ' ': case 'k': e.preventDefault(); togglePlay(); break;
                case 'ArrowRight': case 'l': e.preventDefault(); nextEvent(); break;
                case 'ArrowLeft': case 'j': e.preventDefault(); prevEvent(); break;
                case 'Home': e.preventDefault(); goToStart(); break;
                case 'End': e.preventDefault(); goToEnd(); break;
                case 'ArrowUp': e.preventDefault(); if (sim.speed<10){sim.speed++;slider.value=sim.speed;slider.dispatchEvent(new Event('input'));} break;
                case 'ArrowDown': e.preventDefault(); if (sim.speed>1){sim.speed--;slider.value=sim.speed;slider.dispatchEvent(new Event('input'));} break;
                default:
                    const num = parseInt(e.key);
                    if (num >= 1 && num <= MATCH.sets.length) { e.preventDefault(); stopPlaying(); goToSet(num-1); }
            }
        });
    }

    // ── Démarrage ──
    buildAllTimelines();
    initUI();
    initControls();
    goToSet(0);
})();
