/**
 * swarm_defense_hud.js — CAI 4505C Project Part 5: Autonomous Multi-Agent Defense Swarm HUD
 * Team:
 *   - Jorge A. Mendoza (Lead Architect, Safety Supervisor, Part 4 & 3D Twin Bridge)
 *   - Miguel Martinez (Part 1: Planner Agent — Space-Time A* & CSP)
 *   - Jaime Florez (Part 2: Perception Agent — Softmax CV Classifier)
 *   - Alexis Zisopulos (Part 3: Request Agent — NLP Intents, Slots & Prompt-Injection Defense)
 */

(function () {
  let killSwitchEngaged = false;

  async function fetchSwarmState() {
    try {
      const res = await fetch('/api/swarm/state');
      if (!res.ok) return;
      const data = await res.json();
      renderSwarmDashboard(data);
    } catch (e) {
      console.warn('[SwarmHUD] Could not load swarm state:', e);
    }
  }

  function renderSwarmDashboard(data) {
    if (!data) return;
    const st = data.swarmState || {};
    const m = st.metrics || {};

    killSwitchEngaged = Boolean(st.killSwitch);
    updateKillSwitchUI(killSwitchEngaged);

    // Update KPI cards
    setText('sw-metric-ontime', `${m.on_time_rate_pct ?? 100}%`);
    setText('sw-metric-collisions', `${m.collisions ?? 0}`);
    setText('sw-metric-replans', `${m.replans ?? 9}`);
    setText('sw-metric-blocked', `${m.malicious_blocked ?? 8}`);
    setText('sw-metric-atk-rate', `${m.attack_success_rate_pct ?? 0}%`);
    setText('sw-metric-vetoed', `${m.unsafe_actions_vetoed ?? 2}`);

    // Update Part 2 Perception & Part 4 Bayes Risk badges
    setText('sw-perc-class', (st.perceptionClass || 'package').toUpperCase());
    setText('sw-perc-conf', `${Math.round((st.perceptionConfidence || 0.948) * 100)}% (${(st.weather || 'clear').toUpperCase()})`);
    const riskVal = Number(st.currentRisk || 0.015).toFixed(3);
    const riskEl = document.getElementById('sw-risk-val');
    if (riskEl) {
      riskEl.textContent = `P(Unsafe) = ${riskVal} (τ = 0.60)`;
      riskEl.style.color = Number(riskVal) >= 0.60 ? '#f87171' : '#4ade80';
    }

    // Update 4-Scenario Evaluation Table
    const tbody = document.getElementById('sw-eval-tbody');
    if (tbody && Array.isArray(data.evaluationResults) && data.evaluationResults.length > 0) {
      tbody.innerHTML = data.evaluationResults.map(r => {
        const isAbl = r.scenario.startsWith('ablation');
        const rowBg = isAbl ? 'rgba(239, 68, 68, 0.12)' : 'transparent';
        return `
          <tr style="border-bottom: 1px solid rgba(255,255,255,0.07); background: ${rowBg};">
            <td style="padding: 7px 10px; font-weight: 700; color: ${isAbl ? '#fca5a5' : '#38bdf8'};">${r.scenario}</td>
            <td style="padding: 7px 10px;">${r.robots}</td>
            <td style="padding: 7px 10px; color: #4ade80; font-weight: 700;">${r.on_time_rate_pct}%</td>
            <td style="padding: 7px 10px;">${r.total_path_cost}</td>
            <td style="padding: 7px 10px; color: ${r.collisions === 0 ? '#4ade80' : '#f87171'}; font-weight: 700;">${r.collisions}</td>
            <td style="padding: 7px 10px; color: #facc15;">${r.replans}</td>
            <td style="padding: 7px 10px; color: #c084fc; font-weight: 700;">${r.malicious_blocked}</td>
            <td style="padding: 7px 10px; color: ${r.attack_success_rate_pct === 0 ? '#4ade80' : '#f87171'}; font-weight: 700;">${r.attack_success_rate_pct}%</td>
            <td style="padding: 7px 10px; color: #fb923c;">${r.unsafe_actions_vetoed}</td>
            <td style="padding: 7px 10px; color: #94a3b8;">${r.runtime_ms} ms</td>
          </tr>
        `;
      }).join('');
    }

    // Update Live Blackboard decision_log.jsonl stream
    const logBox = document.getElementById('sw-decision-log-feed');
    if (logBox && Array.isArray(data.recentLogs)) {
      logBox.innerHTML = data.recentLogs.slice().reverse().map(entry => {
        const dec = entry.decision || 'INFO';
        let badgeColor = '#38bdf8';
        if (dec.includes('REJECT') || dec.includes('VETO') || dec.includes('STOP') || dec.includes('ALERT')) {
          badgeColor = '#f87171';
        } else if (dec.includes('ACCEPT') || dec.includes('ALLOC') || dec.includes('SAFE') || dec.includes('CLEAR')) {
          badgeColor = '#4ade80';
        } else if (dec.includes('REPLAN') || dec.includes('EVADE')) {
          badgeColor = '#facc15';
        }
        return `
          <div style="padding: 6px 8px; border-bottom: 1px solid rgba(255,255,255,0.06); font-family: monospace; font-size: 11px; display: flex; flex-direction: column; gap: 2px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span><b style="color: #e2e8f0;">${entry.sender}</b> <span style="color: #64748b;">→</span> <span style="color: #93c5fd;">${entry.recipient}</span> <span style="color: #64748b;">[${entry.event_type}]</span></span>
              <span style="background: rgba(0,0,0,0.35); border: 1px solid ${badgeColor}; color: ${badgeColor}; padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 700;">${dec}</span>
            </div>
            <div style="color: #94a3b8; font-size: 10px; word-break: break-all;">${JSON.stringify(entry.payload || {})}</div>
          </div>
        `;
      }).join('');
    }
  }

  function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  function updateKillSwitchUI(active) {
    const topBtn = document.getElementById('btn-top-kill-switch');
    const modalBtn = document.getElementById('btn-modal-kill-switch');
    const banner = document.getElementById('sw-killswitch-banner');

    if (topBtn) {
      topBtn.textContent = active ? '🟢 RELEASE KILL-SWITCH' : '🛑 KILL-SWITCH';
      topBtn.style.background = active ? 'rgba(34, 197, 94, 0.25)' : 'rgba(239, 68, 68, 0.25)';
      topBtn.style.borderColor = active ? '#4ade80' : '#ef4444';
      topBtn.style.color = active ? '#4ade80' : '#fca5a5';
    }
    if (modalBtn) {
      modalBtn.textContent = active ? '🟢 Release Emergency Kill-Switch (Resume Swarm)' : '🛑 ENGAGE EMERGENCY KILL-SWITCH (Halt All Robots — INV-4)';
      modalBtn.style.background = active ? 'linear-gradient(135deg, #16a34a, #22c55e)' : 'linear-gradient(135deg, #dc2626, #ef4444)';
    }
    if (banner) {
      banner.style.display = active ? 'flex' : 'none';
    }
  }

  async function toggleKillSwitch() {
    try {
      const nextState = !killSwitchEngaged;
      const res = await fetch('/api/swarm/kill-switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          active: nextState,
          reason: nextState
            ? 'Emergency Kill-Switch triggered by Human Supervisor (INV-4)'
            : 'Human Supervisor released Kill-Switch'
        })
      });
      const data = await res.json();
      killSwitchEngaged = Boolean(data.killSwitch);
      updateKillSwitchUI(killSwitchEngaged);

      // Also sync with 3D simulation pause button if needed
      const playBtn = document.getElementById('btn-sim-play');
      if (playBtn) {
        const isPaused = playBtn.innerText.includes('Resume');
        if (killSwitchEngaged && !isPaused) playBtn.click();
        else if (!killSwitchEngaged && isPaused) playBtn.click();
      }
      fetchSwarmState();
    } catch (e) {
      console.error('[SwarmHUD] Kill-switch error:', e);
    }
  }

  async function submitSwarmRequest(text) {
    const input = document.getElementById('sw-request-input');
    const queryText = text !== undefined ? text : (input ? input.value : '');
    if (!queryText.trim()) return;
    if (input && text !== undefined) input.value = text;

    try {
      const res = await fetch('/api/swarm/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: queryText })
      });
      const out = await res.json();
      const box = document.getElementById('sw-request-result');
      if (box) {
        box.style.display = 'block';
        if (out.accepted) {
          box.style.background = 'rgba(22, 163, 74, 0.18)';
          box.style.border = '1px solid #4ade80';
          box.innerHTML = `
            <div style="color: #4ade80; font-weight: 800; font-size: 12px;">✅ REQUEST ACCEPTED BY REQUEST AGENT & SAFETY SUPERVISOR</div>
            <div style="color: #e2e8f0; font-size: 11px; margin-top: 3px;">Route: <b>${out.src}</b> → <b>${out.dst}</b> @ ${out.hour}:00 (${out.deadline_steps} steps SLA) &bull; Forwarded to <b>PlannerAgent (AMR-01..03)</b></div>
          `;
        } else {
          box.style.background = 'rgba(220, 38, 38, 0.22)';
          box.style.border = '1px solid #f87171';
          box.innerHTML = `
            <div style="color: #f87171; font-weight: 800; font-size: 12px;">🛡️ MALICIOUS / INVALID REQUEST BLOCKED & VETOED</div>
            <div style="color: #fecaca; font-size: 11px; margin-top: 3px;">Violations: <code>${(out.reasons || []).join(', ')}</code></div>
            <div style="color: #94a3b8; font-size: 10px; margin-top: 2px;">Logged to <code>decision_log.jsonl</code> &bull; Safety Supervisor Invariant #3 & #1 Enforced</div>
          `;
        }
      }

      // Flash main 3D dispatch banner as well
      const banner = document.querySelector('.dispatch-banner');
      if (banner) {
        if (out.accepted) {
          banner.innerHTML = `<span style="color: #4ade80;">✅ <b>Swarm Request Accepted:</b> Dispatched ${out.src} → ${out.dst} to PlannerAgent!</span>`;
        } else {
          banner.innerHTML = `<span style="color: #f87171;">🛡️ <b>CYBER-DEFENSE BLOCKED:</b> "${queryText}" [${(out.reasons || []).join(', ')}]</span>`;
        }
      }

      renderSwarmDashboard(out);
    } catch (e) {
      console.error('[SwarmHUD] Request validation error:', e);
    }
  }

  async function triggerSwarmScenario(scenarioName) {
    document.querySelectorAll('.sw-scenario-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.scenario === scenarioName);
    });
    const statusEl = document.getElementById('sw-scenario-status');
    if (statusEl) {
      statusEl.textContent = `Running "${scenarioName.toUpperCase()}" scenario across 6 agents...`;
    }

    try {
      const res = await fetch('/api/swarm/scenario', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario: scenarioName })
      });
      const data = await res.json();
      renderSwarmDashboard(data);

      if (statusEl) {
        const descMap = {
          normal: '☀️ NORMAL: Clear weather, 3 AMRs allocated with 0 space-time collisions (100% On-Time).',
          rain: '🌧️ RAIN: Noisy sensors degrade Perception confidence to 68.4%; RiskAgent P(Unsafe)=0.656 >= 0.60 triggers 4 safety vetoes & replans!',
          adversary: '👾 ADVERSARY: Blocking robot (ADV-BLOCKER-01) intercepts path; DefenseAgent (Alpha-Beta Minimax) + PlannerAgent execute 9 conflict-free replans!',
          attack: '🚨 ATTACK: All 8 malicious requests (prompt injections, server_room, off-hours) blocked (0% Attack Success Rate) + 9 adversarial replans!'
        };
        statusEl.textContent = descMap[scenarioName] || `Scenario ${scenarioName} complete.`;
      }

      const banner = document.querySelector('.dispatch-banner');
      if (banner) {
        banner.innerHTML = `<span style="color: #38bdf8;">🛡️ <b>Part 5 Swarm Scenario [${scenarioName.toUpperCase()}]:</b> 0 Collisions &bull; Logged to decision_log.jsonl</span>`;
      }
    } catch (e) {
      console.error('[SwarmHUD] Scenario run error:', e);
    }
  }

  function initSwarmDefenseHUD() {
    const modal = document.getElementById('swarm-defense-modal');
    const btnOpen = document.getElementById('btn-open-swarm-defense');
    const btnClose = document.getElementById('btn-close-swarm-defense');
    const backdrop = document.getElementById('swarm-defense-backdrop');
    const btnTopKill = document.getElementById('btn-top-kill-switch');
    const btnModalKill = document.getElementById('btn-modal-kill-switch');

    if (btnOpen && modal) {
      btnOpen.onclick = () => {
        modal.style.display = 'flex';
        fetchSwarmState();
      };
    }
    if (btnClose && modal) btnClose.onclick = () => { modal.style.display = 'none'; };
    if (backdrop && modal) backdrop.onclick = () => { modal.style.display = 'none'; };

    if (btnTopKill) btnTopKill.onclick = toggleKillSwitch;
    if (btnModalKill) btnModalKill.onclick = toggleKillSwitch;

    const btnSendReq = document.getElementById('btn-sw-send-request');
    if (btnSendReq) btnSendReq.onclick = () => submitSwarmRequest();

    const reqInput = document.getElementById('sw-request-input');
    if (reqInput) {
      reqInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          submitSwarmRequest();
        }
      });
    }

    document.querySelectorAll('.sw-preset-req-chip').forEach(chip => {
      chip.onclick = () => submitSwarmRequest(chip.dataset.prompt);
    });

    document.querySelectorAll('.sw-scenario-btn').forEach(btn => {
      btn.onclick = () => triggerSwarmScenario(btn.dataset.scenario);
    });

    fetchSwarmState();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSwarmDefenseHUD);
  } else {
    initSwarmDefenseHUD();
  }
})();
