const express = require('express');
const http = require('http');
const path = require('path');
const WebSocket = require('ws');

const app = express();
const server = http.createServer(app);
const wss = new WebSocket.Server({ server, path: '/ws' });

const { AStarPlanner } = require('./shared/astar.js');
const { LAB_BOUNDS } = require('./shared/lab_map.js');
const { planningObstacles } = require('./shared/zones.js');
const { clampClearance } = require('./shared/robots.js');
const { TransitPredictor } = require('./ai/transit_predictor.js');
const { CSPScheduler, DEFAULT_SAMPLE_JOBS } = require('./ai/csp_scheduler.js');
const { WorldModel } = require('./world_model.js');
const { createEnvelopeFactory, createAck, needsAck, createSeenIds } = require('./shared/protocol.js');
const { createOutbox } = require('./shared/outbox.js');
const { StateAggregator } = require('./ai/state_aggregator.js');

const astarPlanner = new AStarPlanner({ bounds: LAB_BOUNDS });
const cspScheduler = new CSPScheduler();
const world = new WorldModel();
const envelope = createEnvelopeFactory('s');
const outboxes = new Map(); // WebSocket -> its outbox
// Reliable and critical client message ids already handled, across reconnects.
const seenClientIds = createSeenIds();
// WORLD_STATE to every client at 5 Hz (deltas plus periodic snapshots, section 5.3).
const aggregator = new StateAggregator(world);
setInterval(() => aggregator.tick(), aggregator.intervalMs);

app.use(express.json({ limit: '2mb' }));
app.use(express.urlencoded({ extended: true, limit: '2mb' }));
app.use((req, res, next) => {
  res.set('Cache-Control', 'no-store, no-cache, must-revalidate, private');
  next();
});
app.use(express.static(path.join(__dirname, 'public'), { etag: false, maxAge: 0 }));
app.use('/three', express.static(path.join(__dirname, 'node_modules', 'three')));
app.use('/ai', express.static(path.join(__dirname, 'ai')));
app.use('/shared', express.static(path.join(__dirname, 'shared')));

// Broadcast helper: one message, queued in every client's outbox
function broadcast(type, data) {
  const msg = envelope(type, data);
  outboxes.forEach(outbox => outbox.send(msg));
}

// REST API for AnyLogic or external integration
app.get('/api/robots', (req, res) => {
  res.json({ robots: world.getRobots() });
});

app.get('/api/stations', (req, res) => {
  res.json({ stations: world.getStations(req.query.scan), scan: req.query.scan || world.getActiveScan() });
});

// AnyLogic can POST agent coordinates here directly
app.post('/api/anylogic/update', (req, res) => {
  const { robots, source } = req.body;
  if (Array.isArray(robots)) {
    world.mergeRobots(robots);
    broadcast('ROBOT_UPDATE', { robots: world.getRobots(), source: source || 'AnyLogic' });
    aggregator.tick();
  }
  res.json({ success: true, count: world.getRobots().length });
});

// Sample jobs from benchmark dataset (JOB-101 to JOB-105)
app.get('/api/schedule/sample', (req, res) => {
  res.json({ jobs: DEFAULT_SAMPLE_JOBS });
});

// Each request is planned on its own: within the request's bounds (or the classroom's), around
// the furniture of the request's scan (the request's own edited list when it sends one, otherwise
// the scan's defaults; the classroom when it names none) plus any keep-out boxes the request adds
// (the user's zones on that scan). See shared/zones.js. Routes keep the request's clearance from boxes and
// walls (room for its robots at that scan's size, shared/robots.js), or the minimum when it sends none.

// A* grid path planning endpoint
app.post('/api/plan/astar', (req, res) => {
  const { start, goal, dynamicObstacles, bounds, scan, furniture, clearance } = req.body || {};
  if (!start || !goal) {
    return res.status(400).json({ error: 'Start and goal coordinates required.' });
  }
  astarPlanner.setBounds(bounds || LAB_BOUNDS);
  astarPlanner.safetyMargin = clampClearance(clearance);
  const result = astarPlanner.findPath(start, goal, planningObstacles(scan, dynamicObstacles, furniture));
  res.json(result);
});

// Supervised ML transit latency prediction endpoint
app.post('/api/ml/predict-transit', (req, res) => {
  const params = req.body || {};
  const prediction = TransitPredictor.predict(params);
  res.json(prediction);
});

// CSP Fleet Scheduling with dynamic ML transit buffers
app.post('/api/schedule/jobs', (req, res) => {
  const { jobs, weather_condition, pedestrian_traffic_index, dynamicObstacles, bounds, scan, furniture, clearance } = req.body || {};
  const missionJobs = (Array.isArray(jobs) && jobs.length > 0) ? jobs : DEFAULT_SAMPLE_JOBS;
  const weather = weather_condition || 'Clear';
  const traffic = (pedestrian_traffic_index !== undefined) ? pedestrian_traffic_index : 0.48;

  astarPlanner.setBounds(bounds || LAB_BOUNDS);
  astarPlanner.safetyMargin = clampClearance(clearance);
  const obstacles = planningObstacles(scan, dynamicObstacles, furniture);

  // Calculate A* path and ML predictions for each job
  const mlPredictions = {};
  const jobRoutes = {};

  missionJobs.forEach(job => {
    const startCoord = world.getStation(job.start_station) || { x: -2.0, z: -1.0 };
    const goalCoord = world.getStation(job.goal_station) || { x: 2.0, z: 1.0 };
    
    const route = astarPlanner.findPath(startCoord, goalCoord, obstacles);
    jobRoutes[job.id] = route;
    // No route: no ETA. The predictor would treat it as a zero-length trip.
    if (!route.success) return;

    const pred = TransitPredictor.predict({
      astar_path_len: route.astar_path_len,
      num_turns: route.num_turns,
      manhattan_dist: route.manhattan_dist,
      detour_ratio: route.detour_ratio,
      payload_weight_kg: job.payload_weight_kg || 4.5,
      pedestrian_traffic_index: traffic,
      weather_condition: weather,
      robot_model: job.robot_id
    });

    mlPredictions[job.id] = pred;
  });

  const scheduleResult = cspScheduler.scheduleFleet(missionJobs, mlPredictions);
  (scheduleResult.masterSchedule || []).forEach(item => {
    item.route_status = jobRoutes[item.job_id] && jobRoutes[item.job_id].success ? 'ok' : 'no_route';
  });
  res.json({
    ...scheduleResult,
    jobRoutes,
    weather,
    pedestrian_traffic_index: traffic
  });
});

// ============================================================================
// CAI 4505C PART 5: AUTONOMOUS MULTI-AGENT DEFENSE SWARM ENDPOINTS
// ============================================================================
const fs = require('fs');
const { execFile } = require('child_process');

const ROOT_DIR = path.resolve(__dirname, '..');
const DECISION_LOG_PATH = path.join(ROOT_DIR, 'decision_log.jsonl');
const EVAL_RESULTS_PATH = path.join(ROOT_DIR, 'docs', 'evaluation_results.json');

const swarmState = {
  activeScenario: 'attack',
  weather: 'clear',
  killSwitch: false,
  adversaryActive: false,
  riskThreshold: 0.60,
  currentRisk: 0.015,
  perceptionClass: 'package',
  perceptionConfidence: 0.948,
  metrics: {
    total_requests: 22,
    valid_jobs: 14,
    malicious_blocked: 8,
    attack_success_rate_pct: 0.0,
    unsafe_actions_vetoed: 2,
    replans: 9,
    collisions: 0,
    on_time_rate_pct: 100.0
  }
};

function appendDecisionLog(sender, recipient, event_type, decision, payload) {
  const entry = {
    timestamp: Number((Date.now() / 1000).toFixed(4)),
    timestep: Math.floor(performance.now() / 1000),
    sender,
    recipient,
    event_type,
    decision,
    payload
  };
  try {
    fs.appendFileSync(DECISION_LOG_PATH, JSON.stringify(entry) + '\n', 'utf8');
  } catch (e) {}
  return entry;
}

function readRecentDecisionLogs(limit = 25) {
  try {
    if (!fs.existsSync(DECISION_LOG_PATH)) return [];
    const lines = fs.readFileSync(DECISION_LOG_PATH, 'utf8').trim().split('\n').filter(Boolean);
    return lines.slice(-limit).map(line => {
      try { return JSON.parse(line); } catch (e) { return null; }
    }).filter(Boolean);
  } catch (e) {
    return [];
  }
}

function readEvaluationResults() {
  try {
    if (!fs.existsSync(EVAL_RESULTS_PATH)) return [];
    return JSON.parse(fs.readFileSync(EVAL_RESULTS_PATH, 'utf8'));
  } catch (e) {
    return [];
  }
}

app.get('/api/swarm/state', (req, res) => {
  res.json({
    swarmState,
    evaluationResults: readEvaluationResults(),
    recentLogs: readRecentDecisionLogs(25)
  });
});

app.post('/api/swarm/kill-switch', (req, res) => {
  const { active, reason } = req.body || {};
  swarmState.killSwitch = (active !== undefined) ? Boolean(active) : !swarmState.killSwitch;
  const rsn = reason || (swarmState.killSwitch ? 'Operator engaged Safety Supervisor Kill-Switch (INV-4)' : 'Operator released Kill-Switch');

  if (swarmState.killSwitch) {
    swarmState.metrics.unsafe_actions_vetoed += 1;
    broadcast('E_STOP', { source: 'SafetySupervisor (INV-4)', reason: rsn });
    appendDecisionLog('SafetySupervisor', 'ALL_ROBOTS', 'KILL_SWITCH_ENGAGED', 'EMERGENCY_STOP', {
      invariant: 'INV_4_KILL_SWITCH_AND_RISK',
      kill_switch: true,
      reason: rsn
    });
  } else {
    appendDecisionLog('SafetySupervisor', 'ALL_ROBOTS', 'KILL_SWITCH_RELEASED', 'RESUMED', {
      invariant: 'INV_4_KILL_SWITCH_AND_RISK',
      kill_switch: false,
      reason: rsn
    });
  }

  res.json({
    success: true,
    killSwitch: swarmState.killSwitch,
    reason: rsn,
    swarmState,
    recentLogs: readRecentDecisionLogs(25)
  });
});

app.post('/api/swarm/request', (req, res) => {
  const { text, src, dst, hour, deadline_steps } = req.body || {};
  const rawText = String(text || '').trim();
  const low = rawText.toLowerCase();

  const injectionPatterns = [
    /ignore\s+(all\s+|the\s+|previous\s+)?rules/i,
    /bypass\s+(safety|security|supervisor|check)/i,
    /override\s+(protocol|restriction|safety|auth)/i,
    /sudo\s+/i,
    /system\s*prompt/i,
    /act\s+as\s+admin/i,
    /disable\s+kill[\s_-]?switch/i
  ];
  const restrictedList = ['server_room', 'server room', 'restricted_vault', 'restricted vault', 'hazmat_storage', 'hazmat'];

  const reasons = [];
  if (injectionPatterns.some(rx => rx.test(rawText))) {
    reasons.push('R0_PROMPT_INJECTION_DETECTED');
  }
  const targetDst = String(dst || (low.includes('server') ? 'server_room' : (low.includes('vault') ? 'restricted_vault' : 'library'))).toLowerCase();
  const sourceSrc = String(src || 'robotics_lab').toLowerCase();

  if (restrictedList.some(r => targetDst.includes(r) || low.includes(r))) {
    reasons.push('R1_RESTRICTED_BUILDING_ACCESS');
    reasons.push('INV_1_NO_RESTRICTED_ZONE');
  }

  let parsedHour = (hour !== undefined && hour !== null) ? Number(hour) : 12;
  const timeMatch = low.match(/\b(\d{1,2})(?::\d{2})?\s*(am|pm)\b/i) || low.match(/\bat\s+(\d{1,2}):(\d{2})\b/i);
  if (timeMatch && hour === undefined) {
    let h = parseInt(timeMatch[1], 10);
    const mer = (timeMatch[2] || '').toLowerCase();
    if (mer === 'pm' && h !== 12) h += 12;
    if (mer === 'am' && h === 12) h = 0;
    parsedHour = h;
  }

  if (parsedHour < 7 || parsedHour > 21) {
    reasons.push('R2_OUTSIDE_BUILDING_HOURS');
  }
  if (sourceSrc === targetDst) {
    reasons.push('R3_INVALID_OR_CONFLICTING_DESTINATION');
  }
  const steps = (deadline_steps !== undefined) ? Number(deadline_steps) : (low.includes('2 steps') || low.includes('1 step') ? 2 : 40);
  if (steps < 5) {
    reasons.push('R4_IMPOSSIBLE_DEADLINE');
  }
  if (swarmState.killSwitch) {
    reasons.push('INV_4_KILL_SWITCH_ACTIVE');
  }

  const accepted = reasons.length === 0;
  swarmState.metrics.total_requests += 1;
  if (accepted) {
    swarmState.metrics.valid_jobs += 1;
  } else {
    swarmState.metrics.malicious_blocked += 1;
    swarmState.metrics.unsafe_actions_vetoed += 1;
  }

  appendDecisionLog(
    'RequestAgent',
    accepted ? 'PlannerAgent' : 'SafetySupervisor',
    'LIVE_REQUEST_VALIDATION',
    accepted ? 'ACCEPTED' : 'REJECTED',
    { text: rawText, src: sourceSrc, dst: targetDst, hour: parsedHour, deadline_steps: steps, accepted, reasons }
  );

  res.json({
    accepted,
    text: rawText,
    src: sourceSrc,
    dst: targetDst,
    hour: parsedHour,
    deadline_steps: steps,
    reasons,
    swarmState,
    recentLogs: readRecentDecisionLogs(25)
  });
});

app.post('/api/swarm/scenario', (req, res) => {
  const { scenario } = req.body || {};
  const sc = String(scenario || 'attack').toLowerCase();
  swarmState.activeScenario = sc;
  swarmState.weather = (sc === 'rain') ? 'rain' : 'clear';
  swarmState.adversaryActive = (sc === 'adversary' || sc === 'attack');
  swarmState.currentRisk = (sc === 'rain') ? 0.656 : (swarmState.adversaryActive ? 0.420 : 0.015);
  swarmState.perceptionClass = (sc === 'rain' || swarmState.adversaryActive) ? 'obstacle' : 'package';
  swarmState.perceptionConfidence = (sc === 'rain') ? 0.684 : 0.948;

  appendDecisionLog('PlannerAgent', 'Blackboard', 'SCENARIO_ACTIVATED', 'EXEC_SCENARIO', {
    scenario: sc,
    weather: swarmState.weather,
    adversary_active: swarmState.adversaryActive,
    bayes_risk: swarmState.currentRisk
  });

  // Execute Python run_part5.py in background if available to refresh evaluation_results.json
  const pyScript = path.join(ROOT_DIR, 'run_part5.py');
  if (fs.existsSync(pyScript)) {
    execFile('python', [pyScript, '--scenario', 'all'], { cwd: ROOT_DIR, timeout: 6000 }, () => {
      const evals = readEvaluationResults();
      const matched = evals.find(e => e.scenario === sc);
      if (matched) {
        swarmState.metrics = {
          ...swarmState.metrics,
          on_time_rate_pct: matched.on_time_rate_pct,
          total_path_cost: matched.total_path_cost,
          collisions: matched.collisions,
          replans: matched.replans,
          malicious_blocked: matched.malicious_blocked,
          attack_success_rate_pct: matched.attack_success_rate_pct,
          unsafe_actions_vetoed: matched.unsafe_actions_vetoed
        };
      }
      res.json({
        success: true,
        scenario: sc,
        swarmState,
        evaluationResults: evals,
        recentLogs: readRecentDecisionLogs(25)
      });
    });
  } else {
    res.json({
      success: true,
      scenario: sc,
      swarmState,
      evaluationResults: readEvaluationResults(),
      recentLogs: readRecentDecisionLogs(25)
    });
  }
});

// Shadow mode: the browser runs the simulation and reports it; the world model mirrors one tab.
// The first tab to send telemetry owns it until it disconnects; other tabs are ignored, so two
// open tabs (two separate simulations) can't overwrite each other.
let telemetryOwner = null;

function handleTelemetry(ws, data) {
  if (!telemetryOwner) {
    telemetryOwner = ws;
    console.log('[Telemetry] A browser tab is now the simulation source for the world model');
  }
  // Never broadcast: browsers apply ROBOT_UPDATE to their robots, which would echo back.
  if (telemetryOwner === ws) world.applyTelemetry(data, Date.now());
}

function handleClientMessage(ws, parsed) {
  if (parsed.type === 'ROBOT_TELEMETRY') {
    handleTelemetry(ws, parsed.data);
  } else if (parsed.type === 'E_STOP') {
    console.log('[E_STOP] Relaying emergency stop:', JSON.stringify(parsed.data || {}));
    broadcast('E_STOP', parsed.data || {});
  } else if (parsed.type === 'DISPATCH_TARGET') {
    broadcast('DISPATCH_TARGET', parsed.data);
  } else if (parsed.type === 'EXECUTE_SCHEDULE') {
    broadcast('EXECUTE_SCHEDULE', parsed.data);
  } else if (parsed.type === 'UPDATE_STATIONS') {
    world.updateStations((parsed.data && parsed.data.stations) || {}, (parsed.data && parsed.data.scan));
    broadcast('STATIONS_UPDATE', { stations: world.getStations(), scan: world.getActiveScan() });
    aggregator.tick();
  } else if (parsed.type === 'UPDATE_ROBOT') {
    if (world.updateRobot(parsed.data)) {
      broadcast('ROBOT_UPDATE', { robots: world.getRobots(), source: 'App' });
      aggregator.tick();
    }
  }
}

// WebSocket connection handling
wss.on('connection', (ws) => {
  console.log('[WebSocket] New client connected');
  const outbox = createOutbox({
    isOpen: () => ws.readyState === WebSocket.OPEN,
    write: text => ws.send(text),
    bufferedAmount: () => ws.bufferedAmount
  }, {
    // A queued WORLD_STATE replaced by a newer one: re-send what only the old one carried.
    onReplace: (oldMsg, newMsg) => {
      if (oldMsg.type === 'WORLD_STATE') aggregator.replaced(ws, oldMsg.data, newMsg.data);
    }
  });
  outboxes.set(ws, outbox);
  outbox.send(envelope('INIT_FLEET', { robots: world.getRobots() }));
  aggregator.addClient(ws, data => outbox.send(envelope('WORLD_STATE', data)));

  ws.on('message', (message) => {
    const receivedAt = performance.now();
    try {
      const parsed = JSON.parse(message);
      if (parsed.type === 'ACK') {
        outbox.ack(parsed.data && parsed.data.id);
        return;
      }
      const ackNeeded = needsAck(parsed);
      // A reliable or critical message re-sent after a reconnect is ACKed again but handled once.
      if (!ackNeeded || !seenClientIds.has(parsed.id)) {
        if (ackNeeded) seenClientIds.add(parsed.id);
        handleClientMessage(ws, parsed);
      }
      if (ackNeeded) {
        outbox.send(createAck(envelope, parsed, receivedAt));
      }
    } catch (err) {
      console.error('[WebSocket] Message parse error:', err);
    }
  });

  ws.on('close', () => {
    outbox.close();
    outboxes.delete(ws);
    aggregator.removeClient(ws);
    if (telemetryOwner === ws) {
      telemetryOwner = null;
      console.log('[Telemetry] Simulation source disconnected; the next tab that reports takes over');
    }
    console.log('[WebSocket] Client disconnected');
  });
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
  console.log(`\n======================================================`);
  console.log(`  Robotics Lab Digital Twin Server running at:`);
  console.log(`  -> http://localhost:${PORT}`);
  console.log(`======================================================\n`);
});
