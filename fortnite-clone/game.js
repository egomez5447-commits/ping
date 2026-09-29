import * as THREE from './lib/three.module.min.js';

/* =====================================================================
   BUILD ROYALE - a small third-person battle royale with building.
   ===================================================================== */

const $ = id => document.getElementById(id);
const rand = (a, b) => a + Math.random() * (b - a);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const TAU = Math.PI * 2;
const angDiff = (a, b) => { let d = (a - b) % TAU; if (d > Math.PI) d -= TAU; if (d < -Math.PI) d += TAU; return d; };

const CFG = {
  bots: 24, houses: 14, trees: 170, chests: 10,
  step: 0.7, gravity: 26, radius: 0.4, height: 1.85,
  cell: 4, level: 3, buildCost: 10, buildHp: 160,
};

/* ---------------------------------------------------------------- audio */
let ac = null;
function audio() { if (!ac) { try { ac = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { return null; } } return ac; }
function noise(dur, freq, vol) {
  const c = audio(); if (!c || vol < 0.01) return;
  const n = (c.sampleRate * dur) | 0, buf = c.createBuffer(1, n, c.sampleRate), d = buf.getChannelData(0);
  for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / n, 2);
  const s = c.createBufferSource(); s.buffer = buf;
  const f = c.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = freq;
  const g = c.createGain(); g.gain.value = vol;
  s.connect(f); f.connect(g); g.connect(c.destination); s.start();
}
function tone(freq, dur, vol, type = 'square', slide = 0) {
  const c = audio(); if (!c || vol < 0.01) return;
  const o = c.createOscillator(), g = c.createGain();
  o.type = type; o.frequency.setValueAtTime(freq, c.currentTime);
  if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(20, freq + slide), c.currentTime + dur);
  g.gain.setValueAtTime(vol, c.currentTime); g.gain.exponentialRampToValueAtTime(0.001, c.currentTime + dur);
  o.connect(g); g.connect(c.destination); o.start(); o.stop(c.currentTime + dur);
}
const sfx = {
  shot: (v = 1, big = false) => noise(big ? 0.28 : 0.13, big ? 900 : 2200, 0.35 * v),
  hit: () => tone(1400, 0.05, 0.12, 'square'),
  kill: () => { tone(500, 0.18, 0.18, 'square', 500); },
  build: () => { noise(0.1, 500, 0.35); tone(140, 0.1, 0.2, 'triangle', -60); },
  break: () => noise(0.25, 700, 0.3),
  chop: () => { noise(0.08, 900, 0.3); tone(220, 0.06, 0.15, 'triangle'); },
  swing: () => noise(0.09, 3000, 0.08),
  reload: () => { tone(300, 0.05, 0.12); setTimeout(() => tone(450, 0.06, 0.12), 350); },
  chest: () => { tone(660, 0.12, 0.2, 'triangle'); setTimeout(() => tone(990, 0.2, 0.2, 'triangle'), 110); },
  hurt: () => tone(160, 0.12, 0.25, 'sawtooth', -60),
  glide: () => noise(0.2, 1200, 0.15),
};

/* ------------------------------------------------------------- renderer */
const canvas = $('view');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x8fd0f5);
scene.fog = new THREE.Fog(0xa8dcf5, 90, 380);
const camera = new THREE.PerspectiveCamera(72, 1, 0.1, 800);
camera.rotation.order = 'YXZ';
scene.add(new THREE.HemisphereLight(0xdaf0ff, 0x5a7a3a, 1.05));
const sun = new THREE.DirectionalLight(0xfff2d0, 1.25);
sun.position.set(120, 220, 70);
scene.add(sun);
function resize() {
  renderer.setSize(window.innerWidth, window.innerHeight, false);
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize); resize();

/* -------------------------------------------------------------- terrain */
const ISLAND = 190;
function terrainH(x, z) {
  const r = Math.hypot(x, z) / ISLAND;
  const n = Math.sin(x * 0.021 + 1.3) * Math.cos(z * 0.017) * 3.2 + Math.sin(x * 0.05 + z * 0.043) * 1.2 +
            Math.sin(z * 0.09 - x * 0.03) * 0.6 + Math.cos(x * 0.011 - z * 0.013) * 3.5;
  const island = Math.max(0, 1 - Math.pow(Math.min(r, 1.3), 2.6));
  return (n + 5.5) * island - Math.max(0, r - 0.85) * 20;
}
{
  const geo = new THREE.PlaneGeometry(420, 420, 168, 168);
  geo.rotateX(-Math.PI / 2);
  const p = geo.attributes.position, col = new Float32Array(p.count * 3);
  for (let i = 0; i < p.count; i++) p.setY(i, terrainH(p.getX(i), p.getZ(i)));
  geo.computeVertexNormals();
  const nrm = geo.attributes.normal, c = new THREE.Color();
  for (let i = 0; i < p.count; i++) {
    const h = p.getY(i), slope = 1 - nrm.getY(i), v = (Math.sin(p.getX(i) * 0.7) * Math.cos(p.getZ(i) * 0.9)) * 0.04;
    if (h < 0.7) c.setRGB(0.86, 0.78, 0.52);
    else if (slope > 0.24 || h > 14) c.setRGB(0.52, 0.5, 0.45);
    else c.setRGB(0.33 + v, 0.6 + v * 2, 0.22 + v);
    col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b;
  }
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  scene.add(new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ vertexColors: true, flatShading: true })));
  const water = new THREE.Mesh(new THREE.PlaneGeometry(3000, 3000).rotateX(-Math.PI / 2),
    new THREE.MeshLambertMaterial({ color: 0x2a8fd6, transparent: true, opacity: 0.86 }));
  water.position.y = -0.1;
  scene.add(water);
}

/* --------------------------------------------------------- world state */
const world = { solids: [], ramps: [], trees: [], chests: [], houses: [], builds: new Map() };
const STEP = CFG.step;

function makeSolid(minx, maxx, miny, maxy, minz, maxz, lvl, build) {
  const s = { minx, maxx, miny, maxy, minz, maxz, lvl, build, box3: new THREE.Box3(new THREE.Vector3(minx, miny, minz), new THREE.Vector3(maxx, maxy, maxz)) };
  world.solids.push(s); return s;
}

function woodTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d');
  g.fillStyle = '#c99655'; g.fillRect(0, 0, 64, 64);
  for (let i = 0; i < 4; i++) { g.fillStyle = i % 2 ? '#bf8a4a' : '#d3a262'; g.fillRect(0, i * 16, 64, 15); g.fillStyle = '#7a4f24'; g.fillRect(0, i * 16 + 15, 64, 1); }
  g.strokeStyle = '#6b431c'; g.lineWidth = 3; g.strokeRect(0, 0, 64, 64);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
const woodMat = new THREE.MeshLambertMaterial({ map: woodTexture() });
const plankMat = new THREE.MeshLambertMaterial({ color: 0xd9c9a5 });
const roofMat = new THREE.MeshLambertMaterial({ color: 0xb04a3c });
const floorMat = new THREE.MeshLambertMaterial({ color: 0x8a6a45 });

/* ---- houses */
function addBox(cx, cy, cz, sx, sy, sz, mat, lvl) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(sx, sy, sz), mat);
  m.position.set(cx, cy, cz); scene.add(m);
  return makeSolid(cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2, cz - sz / 2, cz + sz / 2, lvl);
}
function addChest(x, y, z) {
  const g = new THREE.Group();
  const base = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.5, 0.6), new THREE.MeshLambertMaterial({ color: 0x8a5a1e, emissive: 0x3a2400 }));
  base.position.y = 0.25; g.add(base);
  const lid = new THREE.Group(); lid.position.set(0, 0.5, -0.3);
  const lm = new THREE.Mesh(new THREE.BoxGeometry(0.94, 0.2, 0.64), new THREE.MeshLambertMaterial({ color: 0xffc933, emissive: 0x7a5200 }));
  lm.position.set(0, 0.1, 0.3); lid.add(lm); g.add(lid);
  const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.35, 9, 8, 1, true),
    new THREE.MeshBasicMaterial({ color: 0xffd44a, transparent: true, opacity: 0.22, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
  beam.position.y = 4.5; g.add(beam);
  g.position.set(x, y, z); g.rotation.y = rand(0, TAU); scene.add(g);
  world.chests.push({ x, y, z, opened: false, lid, beam });
}
function addHouse(cx, cz) {
  const S = 8, T = 0.4, H = 3.2;
  let base = -99;
  for (let i = -1; i <= 1; i++) for (let j = -1; j <= 1; j++) base = Math.max(base, terrainH(cx + i * S / 2, cz + j * S / 2));
  base += 0.15;
  addBox(cx, base - 1.5, cz, S, 3, S, floorMat, base);
  const door = Math.floor(Math.random() * 4), wallCol = [0xe9dcc0, 0xcfd8e0, 0xd9b99b, 0xc9e0c4][Math.floor(Math.random() * 4)];
  const wm = new THREE.MeshLambertMaterial({ color: wallCol });
  const cy = base + H / 2;
  for (let side = 0; side < 4; side++) {
    const alongX = side < 2, sgn = side % 2 ? 1 : -1;
    const off = sgn * (S / 2 - T / 2);
    const seg = (a, b, y0, y1) => {
      const len = b - a, mid = (a + b) / 2, hh = y1 - y0, my = base + (y0 + y1) / 2;
      if (alongX) addBox(cx + mid, my, cz + off, len, hh, T, wm, base); else addBox(cx + off, my, cz + mid, T, hh, len, wm, base);
    };
    if (side === door) { seg(-S / 2, -1.1, 0, H); seg(1.1, S / 2, 0, H); seg(-1.1, 1.1, 2.4, H); }
    else seg(-S / 2, S / 2, 0, H);
  }
  addBox(cx, base + H + 0.2, cz, S + 1, 0.4, S + 1, roofMat, base + H + 0.4);
  const back = [[0, 2.6], [0, -2.6], [-2.6, 0], [2.6, 0]][door]; // opposite of the door side
  const dirs = [[0, -1], [0, 1], [-1, 0], [1, 0]];
  // side index -> wall along X for 0/1 (z = -/+), along Z for 2/3; door = side, so chest opposite
  const opp = [1, 0, 3, 2][door], o = dirs[opp];
  addChest(cx + o[0] * 2.4, base, cz + o[1] * 2.4);
  world.houses.push({ x: cx, z: cz });
}
{
  let tries = 0;
  while (world.houses.length < CFG.houses && tries++ < 2000) {
    const a = rand(0, TAU), r = Math.sqrt(Math.random()) * 140, x = Math.cos(a) * r, z = Math.sin(a) * r;
    const hc = terrainH(x, z); if (hc < 1.4) continue;
    let ok = true;
    for (let i = -1; i <= 1 && ok; i++) for (let j = -1; j <= 1; j++) if (Math.abs(terrainH(x + i * 4.5, z + j * 4.5) - hc) > 0.7) { ok = false; break; }
    if (!ok) continue;
    if (world.houses.some(h => Math.hypot(h.x - x, h.z - z) < 30)) continue;
    addHouse(x, z);
  }
  tries = 0;
  let outdoor = 0;
  while (outdoor < CFG.chests && tries++ < 2000) {
    const a = rand(0, TAU), r = Math.sqrt(Math.random()) * 150, x = Math.cos(a) * r, z = Math.sin(a) * r, h = terrainH(x, z);
    if (h < 1.2) continue;
    if (world.houses.some(hh => Math.hypot(hh.x - x, hh.z - z) < 8)) continue;
    addChest(x, h, z); outdoor++;
  }
}

/* ---- trees (instanced) */
{
  const n = CFG.trees;
  const trunkGeo = new THREE.CylinderGeometry(0.28, 0.42, 3, 6); trunkGeo.translate(0, 1.5, 0);
  const leafGeo = new THREE.ConeGeometry(2.2, 6, 7); leafGeo.translate(0, 5.6, 0);
  const trunks = new THREE.InstancedMesh(trunkGeo, new THREE.MeshLambertMaterial({ color: 0x6b4423, flatShading: true }), n);
  const leaves = new THREE.InstancedMesh(leafGeo, new THREE.MeshLambertMaterial({ color: 0xffffff, flatShading: true }), n);
  const m4 = new THREE.Matrix4(), col = new THREE.Color();
  let placed = 0, tries = 0;
  while (placed < n && tries++ < 8000) {
    const a = rand(0, TAU), r = Math.sqrt(Math.random()) * 165, x = Math.cos(a) * r, z = Math.sin(a) * r, y = terrainH(x, z);
    if (y < 1.1 || y > 10) continue;
    if (world.houses.some(h => Math.hypot(h.x - x, h.z - z) < 8)) continue;
    const s = rand(0.8, 1.4);
    m4.makeScale(s, s, s).setPosition(x, y - 0.1, z);
    trunks.setMatrixAt(placed, m4); leaves.setMatrixAt(placed, m4);
    col.setHSL(rand(0.27, 0.36), 0.55, rand(0.2, 0.32)); leaves.setColorAt(placed, col);
    world.trees.push({ x, y, z, s, hp: 6, idx: placed, r: 0.55 * s, box3: new THREE.Box3(new THREE.Vector3(x - 0.45 * s, y, z - 0.45 * s), new THREE.Vector3(x + 0.45 * s, y + 9 * s, z + 0.45 * s)) });
    placed++;
  }
  trunks.count = leaves.count = placed;
  trunks.frustumCulled = leaves.frustumCulled = false;
  scene.add(trunks, leaves);
  world.trunks = trunks; world.leaves = leaves;
}
const zeroM = new THREE.Matrix4().makeScale(0, 0, 0);
function removeTree(t) {
  t.hp = 0; world.trunks.setMatrixAt(t.idx, zeroM); world.leaves.setMatrixAt(t.idx, zeroM);
  world.trunks.instanceMatrix.needsUpdate = world.leaves.instanceMatrix.needsUpdate = true;
}

/* ------------------------------------------------- ground / collisions */
const _g = { y: 0, src: null };
function groundAt(x, z, feetY) {
  let best = terrainH(x, z), src = null;
  const lim = feetY + STEP, m = 0.2;
  for (const s of world.solids) {
    if (s.maxy > best && s.maxy <= lim && x >= s.minx - m && x <= s.maxx + m && z >= s.minz - m && z <= s.maxz + m) { best = s.maxy; src = s; }
  }
  for (const r of world.ramps) {
    if (Math.abs(x - r.cx) > 2 || Math.abs(z - r.cz) > 2) continue;
    const t = ((x - r.cx) * r.dx + (z - r.cz) * r.dz + 2) / 4, y = r.y0 + 3 * t;
    if (y > best && y <= lim) { best = y; src = r; }
  }
  _g.y = best; _g.src = src; return _g;
}

function resolveHoriz(a) {
  const R = CFG.radius, H = CFG.height;
  for (const s of world.solids) {
    if (a.x < s.minx - R || a.x > s.maxx + R || a.z < s.minz - R || a.z > s.maxz + R) continue;
    if (a.y >= s.maxy - STEP || a.y + H <= s.miny) continue;
    const cx = clamp(a.x, s.minx, s.maxx), cz = clamp(a.z, s.minz, s.maxz), dx = a.x - cx, dz = a.z - cz, d2 = dx * dx + dz * dz;
    if (d2 >= R * R) continue;
    if (d2 > 1e-8) { const d = Math.sqrt(d2), p = (R - d) / d; a.x += dx * p; a.z += dz * p; }
    else {
      const l = a.x - s.minx, r = s.maxx - a.x, u = a.z - s.minz, dn = s.maxz - a.z, m = Math.min(l, r, u, dn);
      if (m === l) a.x = s.minx - R; else if (m === r) a.x = s.maxx + R; else if (m === u) a.z = s.minz - R; else a.z = s.maxz + R;
    }
  }
  for (const t of world.trees) {
    if (t.hp <= 0 || a.y > t.y + 9) continue;
    const dx = a.x - t.x, dz = a.z - t.z;
    if (Math.abs(dx) > 1.5 || Math.abs(dz) > 1.5) continue;
    const d = Math.hypot(dx, dz), min = R + t.r;
    if (d < min && d > 1e-6) { a.x = t.x + dx / d * min; a.z = t.z + dz / d * min; }
  }
  const rr = Math.hypot(a.x, a.z);
  if (rr > 188) { a.x *= 188 / rr; a.z *= 188 / rr; }
}

function moveActor(a, dt) {
  const spd = Math.hypot(a.vx, a.vz), steps = Math.max(1, Math.ceil(spd * dt / 0.25));
  for (let i = 0; i < steps; i++) { a.x += a.vx * dt / steps; a.z += a.vz * dt / steps; resolveHoriz(a); }
  a.vy -= CFG.gravity * dt;
  let ny = a.y + a.vy * dt;
  if (a.vy > 0) {
    for (const s of world.solids) {
      if (a.x < s.minx - 0.3 || a.x > s.maxx + 0.3 || a.z < s.minz - 0.3 || a.z > s.maxz + 0.3) continue;
      if (a.y + CFG.height <= s.miny + 0.02 && ny + CFG.height > s.miny) { ny = s.miny - CFG.height; a.vy = 0; }
    }
  }
  const g = groundAt(a.x, a.z, a.y);
  if (ny <= g.y || (a.grounded && a.vy <= 0 && a.y - g.y < 0.55)) { a.y = g.y; a.vy = 0; a.grounded = true; a.src = g.src; }
  else { a.y = ny; a.grounded = false; }
}

/* --------------------------------------------------------------- rays */
const _ray = new THREE.Ray(), _b3 = new THREE.Box3(), _pt = new THREE.Vector3(), _o = new THREE.Vector3(), _d = new THREE.Vector3();
function castRay(o, d, maxD, opts = {}) {
  const minT = opts.minT || 0;
  const best = { t: maxD, kind: null, obj: null, head: false };
  for (let t = Math.max(minT, 0.5); t < best.t; t += 1) {
    const x = o.x + d.x * t, y = o.y + d.y * t, z = o.z + d.z * t;
    if (y < terrainH(x, z)) {
      let lo = t - 1, hi = t;
      for (let i = 0; i < 6; i++) { const mid = (lo + hi) / 2; if (o.y + d.y * mid < terrainH(o.x + d.x * mid, o.z + d.z * mid)) hi = mid; else lo = mid; }
      best.t = hi; best.kind = 'terrain'; break;
    }
  }
  _ray.origin.copy(o); _ray.direction.copy(d);
  const test = (box, kind, obj) => {
    if (_ray.intersectBox(box, _pt)) {
      const t = _pt.distanceTo(o);
      if (t < best.t && t >= minT) { best.t = t; best.kind = kind; best.obj = obj; best.head = false; return true; }
    }
    return false;
  };
  for (const s of world.solids) test(s.box3, 'solid', s);
  for (const r of world.ramps) for (const p of r.parts) test(p, 'ramp', r);
  if (!opts.noTrees) for (const t of world.trees) if (t.hp > 0) test(t.box3, 'tree', t);
  if (opts.actors) {
    for (const a of opts.actors) {
      if (a.dead || a === opts.ignore) continue;
      _b3.min.set(a.x - 0.42, a.y, a.z - 0.42); _b3.max.set(a.x + 0.42, a.y + 1.85, a.z + 0.42);
      if (test(_b3, 'actor', a)) best.head = (o.y + d.y * best.t) > a.y + 1.5;
    }
  }
  best.point = new THREE.Vector3(o.x + d.x * best.t, o.y + d.y * best.t, o.z + d.z * best.t);
  return best;
}

/* ------------------------------------------------- particles / tracers */
const particles = [], tracers = [];
{
  const pg = new THREE.BoxGeometry(0.12, 0.12, 0.12);
  for (let i = 0; i < 80; i++) {
    const m = new THREE.Mesh(pg, new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true })); m.visible = false; scene.add(m);
    particles.push({ m, life: 0, v: new THREE.Vector3() });
  }
  const tg = new THREE.BoxGeometry(0.035, 0.035, 1);
  for (let i = 0; i < 50; i++) {
    const m = new THREE.Mesh(tg, new THREE.MeshBasicMaterial({ color: 0xffe9a0, transparent: true, opacity: 0.85 })); m.visible = false; scene.add(m);
    tracers.push({ m, life: 0 });
  }
}
let pIdx = 0, tIdx = 0;
function burst(p, color, n = 6, speed = 4, life = 0.5) {
  for (let i = 0; i < n; i++) {
    const q = particles[pIdx++ % particles.length];
    q.m.visible = true; q.m.position.copy(p); q.m.material.color.setHex(color); q.m.material.opacity = 1;
    q.v.set(rand(-1, 1), rand(0.2, 1.4), rand(-1, 1)).multiplyScalar(speed); q.life = q.max = life;
  }
}
function tracer(from, to) {
  const t = tracers[tIdx++ % tracers.length];
  const len = from.distanceTo(to); if (len < 0.5) return;
  t.m.visible = true; t.life = 0.07;
  t.m.position.copy(from).lerp(to, 0.5); t.m.scale.set(1, 1, len); t.m.lookAt(to);
}
function updateFx(dt) {
  for (const q of particles) if (q.life > 0) {
    q.life -= dt; q.v.y -= 12 * dt; q.m.position.addScaledVector(q.v, dt); q.m.material.opacity = Math.max(0, q.life / q.max);
    if (q.life <= 0) q.m.visible = false;
  }
  for (const t of tracers) if (t.life > 0) { t.life -= dt; if (t.life <= 0) t.m.visible = false; }
}

/* ------------------------------------------------------------- actors */
function makeCharacter(shirt, pants, hat) {
  const group = new THREE.Group(), body = new THREE.Group(); group.add(body);
  const M = c => new THREE.MeshLambertMaterial({ color: c, flatShading: true });
  const box = (w, h, d, c, x, y, z, parent = body) => { const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), M(c)); m.position.set(x, y, z); parent.add(m); return m; };
  box(0.62, 0.75, 0.36, shirt, 0, 1.08, 0);
  box(0.4, 0.4, 0.4, 0xf1c27d, 0, 1.68, 0);
  box(0.44, 0.16, 0.44, hat, 0, 1.92, 0);
  box(0.08, 0.06, 0.02, 0x222222, -0.1, 1.7, -0.21); box(0.08, 0.06, 0.02, 0x222222, 0.1, 1.7, -0.21);
  const mk = (x, y, w, h, c) => { const p = new THREE.Group(); p.position.set(x, y, 0); body.add(p); box(w, h, w + 0.04, c, 0, -h / 2, 0, p); return p; };
  const legL = mk(-0.16, 0.72, 0.24, 0.72, pants), legR = mk(0.16, 0.72, 0.24, 0.72, pants);
  const armL = mk(-0.42, 1.42, 0.2, 0.65, shirt), armR = mk(0.42, 1.42, 0.2, 0.65, shirt);
  const gun = new THREE.Group(); gun.position.set(0.26, 1.15, -0.4); body.add(gun);
  const gm = box(0.1, 0.14, 0.8, 0x2b2b2b, 0, 0, 0, gun); gm.position.z = -0.2;
  const pick = new THREE.Group(); pick.position.set(0, -0.6, -0.1); armR.add(pick);
  box(0.06, 0.06, 0.9, 0x7a4a20, 0, 0, -0.35, pick); box(0.5, 0.09, 0.09, 0x9aa3ad, 0, 0, -0.8, pick);
  pick.visible = false;
  return { group, body, legL, legR, armL, armR, gun, gunMesh: gm, pick };
}
function animateChar(ch, moving, t, aim, weapon) {
  const sw = moving ? Math.sin(t * 10) * 0.8 : 0;
  ch.legL.rotation.x = sw; ch.legR.rotation.x = -sw;
  if (weapon === 'pickaxe') { ch.armL.rotation.x = -sw * 0.6; ch.armR.rotation.x = ch.swing > 0 ? 0.5 + Math.sin((1 - ch.swing / 0.35) * Math.PI) * 1.9 : 0.4 + sw * 0.6; }
  else { ch.armL.rotation.x = 1.25; ch.armR.rotation.x = 1.35; }
  ch.gun.visible = weapon !== 'pickaxe'; ch.pick.visible = weapon === 'pickaxe';
  ch.gun.rotation.x = aim;
}

/* -------------------------------------------------------------- state */
const WEAPONS = {
  ar: { name: 'Assault Rifle', dmg: 22, rate: 0.115, mag: 30, reload: 2.1, spread: 0.010, bloom: 0.0035, maxBloom: 0.035, pellets: 1, range: 260, auto: true, color: 0x2b2b2b },
  sg: { name: 'Pump Shotgun', dmg: 11, rate: 0.95, mag: 6, reload: 2.6, spread: 0.055, bloom: 0, maxBloom: 0, pellets: 9, range: 70, auto: false, color: 0x6b3d1e },
};
const BOT_NAMES = ['Blaze', 'Shadow', 'Viper', 'Nova', 'Rex', 'Ghost', 'Pixel', 'Turbo', 'Echo', 'Zed', 'Maverick', 'Storm', 'Falcon', 'Bolt', 'Ranger', 'Cobra', 'Frost', 'Titan', 'Ace', 'Rogue', 'Hunter', 'Jinx', 'Onyx', 'Dash', 'Kira', 'Nyx', 'Hawk'];
let mode = 'menu'; // menu | playing | paused | over
let time = 0;

const player = {
  isPlayer: true, name: 'You', x: 0, y: 0, z: 0, vx: 0, vy: 0, vz: 0, yaw: 0, pitch: -0.4,
  hp: 100, shield: 0, dead: false, grounded: false, src: null, lvl: 0,
  phase: 'skydive', glider: false, wood: 200, kills: 0,
  slot: 'ar', // pickaxe | ar | sg | wall | floor | ramp
  lastWeapon: 'ar', building: false,
  ammo: { ar: 90, sg: 0 }, mags: { ar: 30, sg: 0 }, owned: { ar: true, sg: false },
  reloading: 0, cool: 0, bloom: 0, swing: 0,
};
const pc = makeCharacter(0x3a7bd5, 0x2b3a67, 0xe23b3b);
pc.swing = 0; scene.add(pc.group);
const glider = new THREE.Mesh(new THREE.SphereGeometry(2.4, 14, 6, 0, TAU, 0, Math.PI / 2).scale(1.5, 0.7, 1.5),
  new THREE.MeshLambertMaterial({ color: 0xff5577, side: THREE.DoubleSide }));
glider.position.y = 3.2; glider.visible = false; pc.group.add(glider);
{
  const a = rand(0, TAU); player.x = Math.cos(a) * 90; player.z = Math.sin(a) * 90; player.y = 170;
  player.yaw = Math.atan2(-(0 - player.x), -(0 - player.z)); // face island centre
}

const bots = [];
function findSpawn() {
  for (let i = 0; i < 400; i++) {
    const a = rand(0, TAU), r = Math.sqrt(Math.random()) * 150, x = Math.cos(a) * r, z = Math.sin(a) * r;
    if (terrainH(x, z) < 1.3) continue;
    if (world.solids.some(s => x > s.minx - 1 && x < s.maxx + 1 && z > s.minz - 1 && z < s.maxz + 1)) continue;
    if (bots.some(b => Math.hypot(b.x - x, b.z - z) < 22)) continue;
    return { x, z };
  }
  return { x: 0, z: 0 };
}
for (let i = 0; i < CFG.bots; i++) {
  const sp = findSpawn();
  const ch = makeCharacter(new THREE.Color().setHSL(Math.random(), 0.6, 0.45).getHex(), 0x33384a, new THREE.Color().setHSL(Math.random(), 0.5, 0.3).getHex());
  ch.swing = 0; scene.add(ch.group);
  const b = {
    isBot: true, name: BOT_NAMES[i % BOT_NAMES.length] + (i >= BOT_NAMES.length ? i : ''), ch, x: sp.x, z: sp.z, y: terrainH(sp.x, sp.z), vx: 0, vy: 0, vz: 0, yaw: rand(0, TAU),
    hp: 100, shield: Math.random() < 0.4 ? 50 : 0, dead: false, deadT: 0, grounded: true, src: null,
    weapon: Math.random() < 0.35 ? 'sg' : 'ar', target: null, think: rand(0, 0.5), los: false, cool: rand(0.5, 1.5), burst: 0,
    strafeT: 0, strafeDir: 1, wp: null, wpT: 0, alert: 0, stuckT: 0, lx: sp.x, lz: sp.z, anim: rand(0, 10),
  };
  b.ch.gunMesh.material.color.setHex(WEAPONS[b.weapon].color);
  bots.push(b);
}
const allActors = [player, ...bots];

/* --------------------------------------------------------------- storm */
const PHASES = [
  { r: 150, wait: 45, shrink: 35, dps: 1 }, { r: 90, wait: 30, shrink: 30, dps: 2 }, { r: 50, wait: 25, shrink: 25, dps: 4 },
  { r: 22, wait: 20, shrink: 20, dps: 7 }, { r: 5, wait: 10, shrink: 15, dps: 10 },
];
const storm = { i: 0, t: 0, shrinking: false, cx: 0, cz: 0, r: 220, fromR: 220, toR: 150, fromX: 0, fromZ: 0, toX: 0, toZ: 0, dps: 0 };
function planStorm() {
  const p = PHASES[storm.i];
  storm.fromR = storm.r; storm.toR = p.r; storm.fromX = storm.cx; storm.fromZ = storm.cz;
  const a = rand(0, TAU), off = Math.max(0, (storm.fromR - storm.toR)) * rand(0.2, 0.7) * (storm.i === 0 ? 0.6 : 1);
  storm.toX = storm.cx + Math.cos(a) * off; storm.toZ = storm.cz + Math.sin(a) * off;
  storm.dps = p.dps; storm.t = 0; storm.shrinking = false;
}
planStorm();
const stormWall = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, 400, 64, 1, true),
  new THREE.MeshBasicMaterial({ color: 0x9a3cff, transparent: true, opacity: 0.28, side: THREE.DoubleSide, depthWrite: false }));
stormWall.position.y = 150; scene.add(stormWall);
function updateStorm(dt) {
  const p = PHASES[storm.i]; storm.t += dt;
  if (!storm.shrinking) { if (storm.t >= p.wait) { storm.shrinking = true; storm.t = 0; toast('The storm is closing!'); } }
  else {
    const k = clamp(storm.t / p.shrink, 0, 1);
    storm.r = storm.fromR + (storm.toR - storm.fromR) * k;
    storm.cx = storm.fromX + (storm.toX - storm.fromX) * k; storm.cz = storm.fromZ + (storm.toZ - storm.fromZ) * k;
    if (k >= 1 && storm.i < PHASES.length - 1) { storm.i++; storm.cx = storm.toX; storm.cz = storm.toZ; planStorm(); }
    else if (k >= 1) { storm.t = p.shrink; }
  }
  stormWall.position.x = storm.cx; stormWall.position.z = storm.cz; stormWall.scale.set(storm.r, 1, storm.r);
}
const outsideStorm = a => Math.hypot(a.x - storm.cx, a.z - storm.cz) > storm.r;

/* -------------------------------------------------------------- damage */
function feed(html) { const d = document.createElement('div'); d.innerHTML = html; $('feed').prepend(d); setTimeout(() => d.remove(), 5000); while ($('feed').children.length > 5) $('feed').lastChild.remove(); }
let toastT = 0;
function toast(msg) { const t = $('toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('show'), 2200); }
let hmT = 0;
function hitmarker(kind) { const c = $('crosshair'); c.className = 'hud ' + kind; clearTimeout(hmT); hmT = setTimeout(() => c.className = 'hud', 130); }

function aliveCount() { return allActors.filter(a => !a.dead).length; }
function damageActor(a, dmg, src, head) {
  if (a.dead || mode === 'over') return;
  if (head) dmg *= 1.5;
  let d = dmg;
  if (a.shield > 0) { const s = Math.min(a.shield, d); a.shield -= s; d -= s; }
  a.hp -= d;
  if (a.isPlayer) { const e = $('dmg'); e.classList.add('on'); setTimeout(() => e.classList.remove('on'), 60); sfx.hurt(); }
  else if (src && src.isPlayer) { hitmarker(a.hp <= 0 ? 'kill' : 'hit'); if (a.hp > 0) sfx.hit(); }
  if (a.isBot && src && src !== a && !src.dead) { a.target = src; a.alert = 6; }
  if (a.hp <= 0) killActor(a, src);
}
function killActor(a, src) {
  a.dead = true; a.hp = 0;
  const who = src ? (src.isPlayer ? 'You' : src.name) : 'The storm';
  feed(`<b>${who}</b> eliminated <b>${a.isPlayer ? 'You' : a.name}</b>`);
  burst(new THREE.Vector3(a.x, a.y + 1, a.z), 0xffffff, 12, 5, 0.7);
  if (src && src.isPlayer) { player.kills++; player.ammo.ar += 30; player.wood += 30; sfx.kill(); toast(`Eliminated ${a.name}! +30 ammo +30 wood`); }
  if (a.isPlayer) endGame(false);
  else if (!player.dead && bots.every(b => b.dead)) endGame(true);
}
function endGame(won) {
  if (mode === 'over') return;
  mode = 'over'; if (document.pointerLockElement) document.exitPointerLock();
  const place = won ? 1 : aliveCount() + 1;
  $('endtitle').textContent = won ? 'VICTORY ROYALE' : 'ELIMINATED';
  $('endsub').textContent = won ? 'You are the last one standing!' : `You placed #${place}`;
  $('endstats').textContent = `Eliminations: ${player.kills}`;
  $('end').classList.remove('hidden');
}

function damageBuild(b, dmg, at) {
  b.hp -= dmg; burst(at, 0xd9a55b, 4, 3, 0.4);
  if (b.hp <= 0) removeBuild(b);
}
function removeBuild(b) {
  scene.remove(b.mesh); world.builds.delete(b.key);
  if (b.solid) { const i = world.solids.indexOf(b.solid); if (i >= 0) world.solids.splice(i, 1); }
  if (b.ramp) { const i = world.ramps.indexOf(b.ramp); if (i >= 0) world.ramps.splice(i, 1); }
  burst(b.mesh.position, 0xd9a55b, 10, 5, 0.6); sfx.break();
}

/* ------------------------------------------------------------ building */
const ghostMat = new THREE.MeshBasicMaterial({ color: 0x66ff88, transparent: true, opacity: 0.4, depthWrite: false });
const wallGeo = new THREE.BoxGeometry(4, 3, 0.3), floorGeo = new THREE.BoxGeometry(4, 0.3, 4), rampGeo = new THREE.BoxGeometry(4, 0.3, Math.hypot(4, 3));
const RAMP_TILT = Math.atan2(3, 4);
function makeRampMesh(mat) {
  const g = new THREE.Group(), m = new THREE.Mesh(rampGeo, mat); m.rotation.x = -RAMP_TILT; m.position.y = 1.5 - 0.16; g.add(m); return g;
}
const ghosts = {
  wall: new THREE.Mesh(wallGeo, ghostMat), floor: new THREE.Mesh(floorGeo, ghostMat), ramp: makeRampMesh(ghostMat),
};
for (const k in ghosts) { ghosts[k].visible = false; scene.add(ghosts[k]); }

function computeBuild(type) {
  const fx = -Math.sin(player.yaw), fz = -Math.cos(player.yaw), ax = Math.abs(fx) >= Math.abs(fz);
  const Tx = player.x + fx * 3, Tz = player.z + fz * 3;
  const base = player.lvl + CFG.level * Math.round((player.y - player.lvl) / CFG.level);
  const b = { type, y0: base, hp: CFG.buildHp };
  if (type === 'wall') {
    if (ax) { b.axis = 'x'; b.cx = Math.round(Tx / 4) * 4; b.cz = Math.floor(Tz / 4) * 4 + 2; }
    else { b.axis = 'z'; b.cz = Math.round(Tz / 4) * 4; b.cx = Math.floor(Tx / 4) * 4 + 2; }
  } else {
    b.cx = Math.floor(Tx / 4) * 4 + 2; b.cz = Math.floor(Tz / 4) * 4 + 2;
    if (type === 'floor' && player.pitch > 0.4) b.y0 = base + CFG.level;
    if (type === 'ramp') { b.dx = ax ? Math.sign(fx) : 0; b.dz = ax ? 0 : Math.sign(fz); }
  }
  b.key = `${type}|${b.cx}|${b.cz}|${b.y0.toFixed(1)}|${b.axis || ''}${b.dx ?? ''}${b.dz ?? ''}`;
  return b;
}
function skirtFor(b) {
  let minT = 1e9;
  for (const [i, j] of [[-2, -2], [2, -2], [-2, 2], [2, 2], [0, 0]]) minT = Math.min(minT, terrainH(b.cx + i, b.cz + j));
  const d = b.y0 - minT;
  return d < CFG.level ? Math.max(0, d + 0.2) : 0;
}
function placeBuild(b) {
  if (world.builds.has(b.key)) return false;
  if (b.type === 'wall') {
    const sk = skirtFor(b), h = 3 + sk;
    const m = new THREE.Mesh(new THREE.BoxGeometry(4, h, 0.3), woodMat);
    m.position.set(b.cx, b.y0 + 1.5 - sk / 2, b.cz); if (b.axis === 'x') m.rotation.y = Math.PI / 2;
    b.mesh = m;
    b.solid = b.axis === 'x' ? makeSolid(b.cx - 0.15, b.cx + 0.15, b.y0 - sk, b.y0 + 3, b.cz - 2, b.cz + 2, b.y0, b)
                             : makeSolid(b.cx - 2, b.cx + 2, b.y0 - sk, b.y0 + 3, b.cz - 0.15, b.cz + 0.15, b.y0, b);
  } else if (b.type === 'floor') {
    const sk = skirtFor(b), h = 0.3 + sk;
    const m = new THREE.Mesh(new THREE.BoxGeometry(4, h, 4), woodMat);
    m.position.set(b.cx, b.y0 - h / 2, b.cz); b.mesh = m;
    b.solid = makeSolid(b.cx - 2, b.cx + 2, b.y0 - 0.3 - sk, b.y0, b.cz - 2, b.cz + 2, b.y0, b);
  } else {
    const g = makeRampMesh(woodMat); g.position.set(b.cx, b.y0, b.cz); g.rotation.y = Math.atan2(b.dx, b.dz); b.mesh = g;
    const parts = [];
    for (let i = 0; i < 4; i++) {
      const t0 = i / 4, t1 = (i + 1) / 4;
      const c0 = b.cx + b.dx * (-2 + 4 * t0), c1 = b.cx + b.dx * (-2 + 4 * t1), z0 = b.cz + b.dz * (-2 + 4 * t0), z1 = b.cz + b.dz * (-2 + 4 * t1);
      parts.push(new THREE.Box3(new THREE.Vector3(Math.min(c0, c1) - (b.dx ? 0 : 2), b.y0 + 3 * t0 - 0.2, Math.min(z0, z1) - (b.dz ? 0 : 2)),
                                new THREE.Vector3(Math.max(c0, c1) + (b.dx ? 0 : 2), b.y0 + 3 * t1 + 0.2, Math.max(z0, z1) + (b.dz ? 0 : 2))));
    }
    b.ramp = { cx: b.cx, cz: b.cz, y0: b.y0, lvl: b.y0, dx: b.dx, dz: b.dz, parts, build: b };
    world.ramps.push(b.ramp);
  }
  scene.add(b.mesh); world.builds.set(b.key, b); sfx.build();
  return true;
}
function updateGhost() {
  for (const k in ghosts) ghosts[k].visible = false;
  if (!player.building || player.phase !== 'ground' || player.dead) return;
  const b = computeBuild(player.slot), g = ghosts[player.slot];
  g.visible = true;
  if (b.type === 'wall') { g.position.set(b.cx, b.y0 + 1.5, b.cz); g.rotation.y = b.axis === 'x' ? Math.PI / 2 : 0; }
  else if (b.type === 'floor') g.position.set(b.cx, b.y0 - 0.15, b.cz);
  else { g.position.set(b.cx, b.y0, b.cz); g.rotation.y = Math.atan2(b.dx, b.dz); }
  ghostMat.color.setHex(world.builds.has(b.key) || player.wood < CFG.buildCost ? 0xff5555 : 0x66ff88);
}
function tryBuild() {
  if (player.wood < CFG.buildCost) { toast('Not enough wood!'); return; }
  const b = computeBuild(player.slot);
  if (placeBuild(b)) player.wood -= CFG.buildCost;
}

/* ---------------------------------------------------------- player ops */
const keys = {}, mouse = { l: false, r: false, lClick: false };
const eye = new THREE.Vector3(), camPos = new THREE.Vector3(), aimDir = new THREE.Vector3(), fwd3 = new THREE.Vector3();

function selectSlot(s) {
  if (player.phase !== 'ground') return;
  if (s === 'sg' && !player.owned.sg) { toast('Find a chest to get the shotgun'); return; }
  player.slot = s; player.building = ['wall', 'floor', 'ramp'].includes(s);
  if (!player.building) player.lastWeapon = s;
  player.reloading = 0; refreshHotbar();
}
function toggleBuild() { if (player.building) selectSlot(player.lastWeapon); else selectSlot('wall'); }
function startReload() {
  const w = WEAPONS[player.slot]; if (!w || player.reloading > 0) return;
  if (player.mags[player.slot] >= w.mag || player.ammo[player.slot] <= 0) return;
  player.reloading = w.reload; sfx.reload();
}
function updateAim() {
  const cp = Math.cos(player.pitch);
  fwd3.set(-Math.sin(player.yaw) * cp, Math.sin(player.pitch), -Math.cos(player.yaw) * cp);
  eye.set(player.x, player.y + 1.6, player.z);
}
function spreadDir(base, s) {
  const r = new THREE.Vector3().crossVectors(base, new THREE.Vector3(0, 1, 0)).normalize(), u = new THREE.Vector3().crossVectors(r, base).normalize();
  return base.clone().addScaledVector(r, (Math.random() + Math.random() - 1) * s).addScaledVector(u, (Math.random() + Math.random() - 1) * s).normalize();
}
function firePlayerGun() {
  const w = WEAPONS[player.slot], id = player.slot;
  if (player.reloading > 0 || player.cool > 0) return;
  if (player.mags[id] <= 0) { startReload(); return; }
  player.mags[id]--; player.cool = w.rate;
  // camera ray -> aim point -> shot from the eye (parallax fix)
  const camDist = camPos.distanceTo(eye);
  const cr = castRay(camPos, fwd3, 300, { minT: camDist + 0.3, noTrees: false });
  const target = cr.point;
  const baseDir = target.clone().sub(eye).normalize();
  const ads = mouse.r ? 0.55 : 1;
  const s = (w.spread + player.bloom) * ads;
  const muzzle = eye.clone().addScaledVector(fwd3, 0.9).add(new THREE.Vector3(Math.cos(player.yaw), 0, -Math.sin(player.yaw)).multiplyScalar(0.3)).add(new THREE.Vector3(0, -0.35, 0));
  for (let i = 0; i < w.pellets; i++) {
    const d = spreadDir(baseDir, s);
    const hit = castRay(eye, d, w.range, { actors: bots, ignore: player });
    tracer(muzzle, hit.point);
    if (hit.kind === 'actor') {
      let dmg = w.dmg; if (id === 'sg') dmg *= clamp(1.2 - hit.t / 55, 0.15, 1);
      damageActor(hit.obj, dmg, player, hit.head && id === 'ar');
      burst(hit.point, 0xff5050, 2, 3, 0.3);
    } else if (hit.kind === 'solid' || hit.kind === 'ramp') { if (hit.obj.build) damageBuild(hit.obj.build, w.dmg * 0.5, hit.point); else burst(hit.point, 0xffe0a0, 2, 3, 0.25); }
    else if (hit.kind) burst(hit.point, 0xcfc39a, 2, 3, 0.25);
  }
  sfx.shot(1, id === 'sg');
  player.bloom = Math.min(w.maxBloom, player.bloom + w.bloom);
  player.pitch += id === 'sg' ? 0.06 : rand(0.004, 0.012); player.yaw += rand(-0.004, 0.004);
  if (player.mags[id] <= 0 && player.ammo[id] > 0) startReload();
}
function swingPickaxe() {
  if (player.cool > 0) return;
  player.cool = 0.42; pc.swing = 0.35; sfx.swing();
  setTimeout(() => {
    if (player.dead) return;
    const hit = castRay(eye, fwd3, 3.8, { actors: bots, ignore: player });
    if (hit.kind === 'actor') { damageActor(hit.obj, 20, player, false); burst(hit.point, 0xff5050, 4, 3, 0.3); }
    else if (hit.kind === 'tree') {
      hit.obj.hp--; player.wood += 10; sfx.chop(); burst(hit.point, 0x9b6a3a, 5, 3, 0.4);
      if (hit.obj.hp <= 0) removeTree(hit.obj);
    } else if ((hit.kind === 'solid' || hit.kind === 'ramp') && hit.obj.build) {
      const b = hit.obj.build; player.wood += 4; sfx.chop(); damageBuild(b, 45, hit.point);
    } else if (hit.kind) { sfx.chop(); burst(hit.point, 0xcfc39a, 3, 2, 0.3); }
  }, 130);
}
function openChest(c) {
  c.opened = true; c.beam.visible = false; c.lid.rotation.x = -1.9; sfx.chest();
  const loot = [];
  if (!player.owned.sg && Math.random() < 0.7) { player.owned.sg = true; player.ammo.sg += 12; loot.push('Pump Shotgun'); }
  const a = 30 + Math.floor(Math.random() * 30); player.ammo.ar += a; loot.push(`${a} rifle ammo`);
  if (player.owned.sg && !loot.includes('Pump Shotgun')) { player.ammo.sg += 8; loot.push('8 shells'); }
  if (Math.random() < 0.6) { player.shield = Math.min(100, player.shield + 50); loot.push('Shield +50'); }
  else { player.hp = Math.min(100, player.hp + 40); loot.push('Medkit +40'); }
  player.wood += 30; loot.push('30 wood');
  toast(loot.join(' · ')); refreshHotbar();
}

/* --------------------------------------------------------- player update */
let gliderSfx = 0;
function updatePlayer(dt) {
  const fw = (keys.KeyW ? 1 : 0) - (keys.KeyS ? 1 : 0), st = (keys.KeyD ? 1 : 0) - (keys.KeyA ? 1 : 0);
  const fx = -Math.sin(player.yaw), fz = -Math.cos(player.yaw), rx = Math.cos(player.yaw), rz = -Math.sin(player.yaw);
  let mx = fx * fw + rx * st, mz = fz * fw + rz * st; const ml = Math.hypot(mx, mz); if (ml > 0) { mx /= ml; mz /= ml; }
  player.cool = Math.max(0, player.cool - dt); player.bloom = Math.max(0, player.bloom - dt * 0.05);
  pc.swing = Math.max(0, pc.swing - dt);

  if (player.phase === 'skydive') {
    const height = player.y - terrainH(player.x, player.z);
    if (!player.glider && height < 55) { player.glider = true; sfx.glide(); }
    const sp = player.glider ? 16 : 24, vyT = player.glider ? -7 : -42;
    player.vx += (mx * sp - player.vx) * Math.min(1, dt * 3); player.vz += (mz * sp - player.vz) * Math.min(1, dt * 3);
    player.vy += (vyT - player.vy) * Math.min(1, dt * 3);
    player.x += player.vx * dt; player.z += player.vz * dt; player.y += player.vy * dt;
    const rr = Math.hypot(player.x, player.z); if (rr > 260) { player.x *= 260 / rr; player.z *= 260 / rr; }
    const gy = groundAt(player.x, player.z, player.y + 2).y;
    if (player.y <= gy) {
      player.y = gy; player.vy = 0; player.vx = player.vz = 0; player.phase = 'ground'; player.glider = false; player.grounded = true;
      selectSlot('ar'); toast('Landed! Find loot and stay in the zone'); $('hint').textContent = '';
    }
    glider.visible = player.glider;
    pc.body.rotation.x = player.glider ? 0 : -1.3; pc.body.position.y = player.glider ? 0 : 0.9;
    return;
  }
  pc.body.rotation.x = 0; pc.body.position.y = 0; glider.visible = false;

  const ads = mouse.r && !player.building;
  const sprint = keys.ShiftLeft || keys.ShiftRight;
  const speed = ads ? 3.2 : sprint ? 9 : 6.2;
  const acc = player.grounded ? 14 : 4;
  player.vx += (mx * speed - player.vx) * Math.min(1, dt * acc); player.vz += (mz * speed - player.vz) * Math.min(1, dt * acc);
  if (keys.Space && player.grounded) { player.vy = 8.8; player.grounded = false; }
  moveActor(player, dt);
  if (player.grounded) player.lvl = player.src ? player.src.lvl : player.y;

  if (player.reloading > 0) {
    player.reloading -= dt;
    if (player.reloading <= 0) {
      const id = player.slot, w = WEAPONS[id], need = w.mag - player.mags[id], take = Math.min(need, player.ammo[id]);
      player.mags[id] += take; player.ammo[id] -= take; player.reloading = 0;
    }
  }
  // actions
  if (mouse.l || mouse.lClick) {
    if (player.building) { if (mouse.lClick || player.cool <= 0) { tryBuild(); player.cool = 0.12; } }
    else if (player.slot === 'pickaxe') swingPickaxe();
    else if (WEAPONS[player.slot].auto || mouse.lClick) firePlayerGun();
  }
  mouse.lClick = false;

  // chest prompt
  let near = null;
  for (const c of world.chests) if (!c.opened && Math.hypot(c.x - player.x, c.z - player.z) < 2.6 && Math.abs(c.y - player.y) < 2.5) { near = c; break; }
  const pr = $('prompt');
  if (near) { pr.style.display = 'block'; pr.textContent = '[E] Open chest'; if (keys.KeyE) { openChest(near); keys.KeyE = false; } }
  else pr.style.display = 'none';

  if (outsideStorm(player)) { player.stormT = (player.stormT || 0) + dt; if (player.stormT >= 1) { player.stormT = 0; damageActor(player, storm.dps, null); } }
}

function updateCamera(dt) {
  updateAim();
  const ads = mouse.r && !player.building && player.phase === 'ground';
  const dist = player.phase === 'skydive' ? 6 : ads ? 1.9 : 3.6, side = ads ? 0.75 : 0.95;
  const rvx = Math.cos(player.yaw), rvz = -Math.sin(player.yaw);
  const want = new THREE.Vector3(eye.x - fwd3.x * dist + rvx * side, eye.y - fwd3.y * dist + 0.25, eye.z - fwd3.z * dist + rvz * side);
  const dir = want.clone().sub(eye), len = dir.length(); dir.divideScalar(len);
  const hit = castRay(eye, dir, len, { noTrees: true });
  camPos.copy(eye).addScaledVector(dir, hit.kind ? Math.max(0.4, hit.t - 0.3) : len);
  camPos.y = Math.max(camPos.y, terrainH(camPos.x, camPos.z) + 0.25);
  camera.position.copy(camPos);
  camera.rotation.set(player.pitch, player.yaw, 0);
  const fov = ads ? 52 : (keys.ShiftLeft && player.grounded && (player.vx || player.vz) ? 78 : 72);
  camera.fov += (fov - camera.fov) * Math.min(1, dt * 10); camera.updateProjectionMatrix();
}

/* ------------------------------------------------------------------ bots */
const _e = new THREE.Vector3(), _t = new THREE.Vector3(), _dd = new THREE.Vector3();
function botFire(b, tg) {
  const w = WEAPONS[b.weapon];
  _e.set(b.x, b.y + 1.55, b.z); _t.set(tg.x, tg.y + 1.15, tg.z);
  const dist = _e.distanceTo(_t), base = _t.clone().sub(_e).normalize();
  const spread = (b.weapon === 'sg' ? 0.06 : 0.018 + dist * 0.0011);
  const pellets = b.weapon === 'sg' ? 7 : 1;
  const muzzle = _e.clone().addScaledVector(base, 0.9);
  for (let i = 0; i < pellets; i++) {
    const d = spreadDir(base, spread);
    const hit = castRay(_e, d, w.range, { actors: allActors, ignore: b });
    tracer(muzzle, hit.point);
    if (hit.kind === 'actor') damageActor(hit.obj, (b.weapon === 'sg' ? 7 * clamp(1.2 - hit.t / 40, 0.1, 1) : 9) * (hit.obj.isPlayer ? 1 : 0.4), b, false);
    else if ((hit.kind === 'solid' || hit.kind === 'ramp') && hit.obj.build) damageBuild(hit.obj.build, 8, hit.point);
  }
  const dp = Math.hypot(b.x - player.x, b.z - player.z);
  sfx.shot(clamp(1 - dp / 90, 0, 1) * 0.8, b.weapon === 'sg');
}
function pickWaypoint(b) {
  const a = rand(0, TAU), safe = Math.min(storm.r - 8, 120);
  if (outsideStorm(b) || storm.shrinking || Math.random() < 0.3) { b.wp = { x: storm.cx + Math.cos(a) * rand(0, Math.max(3, storm.r * 0.5)), z: storm.cz + Math.sin(a) * rand(0, Math.max(3, storm.r * 0.5)) }; }
  else if (Math.random() < 0.6 && world.houses.length) { const h = world.houses[Math.floor(Math.random() * world.houses.length)]; b.wp = { x: h.x + rand(-3, 3), z: h.z + rand(-3, 3) }; }
  else b.wp = { x: storm.cx + Math.cos(a) * rand(0, Math.max(3, safe)), z: storm.cz + Math.sin(a) * rand(0, Math.max(3, safe)) };
  b.wpT = rand(6, 12);
}
function updateBot(b, dt) {
  if (b.dead) {
    b.deadT += dt; b.ch.body.rotation.x = Math.min(1.5, b.deadT * 4); b.ch.body.position.y = Math.min(0.2, b.deadT);
    if (b.deadT > 4) b.ch.group.visible = false;
    return;
  }
  b.think -= dt; b.alert = Math.max(0, b.alert - dt); b.cool -= dt; b.anim += dt; b.wpT -= dt; b.strafeT -= dt;
  b.ch.swing = 0;
  if (b.think <= 0) {
    b.think = rand(0.3, 0.6);
    // choose / validate a target
    let best = null, bd = 1e9;
    for (const o of allActors) {
      if (o === b || o.dead) continue;
      if (o.isPlayer && player.phase !== 'ground') continue;
      const d = Math.hypot(o.x - b.x, o.z - b.z), lim = o.isPlayer ? 55 : 38;
      if (d < lim && d < bd) { _e.set(b.x, b.y + 1.55, b.z); _t.set(o.x, o.y + 1.2, o.z); _dd.copy(_t).sub(_e); const L = _dd.length(); _dd.divideScalar(L);
        if (castRay(_e, _dd, L, {}).kind === null) { best = o; bd = d; } }
    }
    if (best) { b.target = best; b.los = true; }
    else if (b.target && (b.target.dead || b.alert <= 0)) { b.target = null; b.los = false; }
    else b.los = false;
  }
  let mx = 0, mz = 0, speed = 4.6;
  const tg = b.target;
  if (tg && !tg.dead) {
    const dx = tg.x - b.x, dz = tg.z - b.z, dist = Math.hypot(dx, dz);
    const want = Math.atan2(-dx, -dz), diff = angDiff(want, b.yaw);
    b.yaw += clamp(diff, -3.2 * dt, 3.2 * dt);
    const pref = b.weapon === 'sg' ? 7 : 18, toward = dist > pref + 4 ? 1 : dist < pref - 4 ? -1 : 0;
    if (b.strafeT <= 0) { b.strafeDir = Math.random() < 0.5 ? -1 : 1; b.strafeT = rand(0.8, 2); }
    const fx = -Math.sin(b.yaw), fz = -Math.cos(b.yaw), rx = Math.cos(b.yaw), rz = -Math.sin(b.yaw);
    mx = fx * toward + rx * b.strafeDir * 0.8; mz = fz * toward + rz * b.strafeDir * 0.8;
    if (b.los && Math.abs(diff) < 0.14 && b.cool <= 0 && dist < WEAPONS[b.weapon].range * 0.5) {
      botFire(b, tg);
      if (b.weapon === 'sg') b.cool = rand(1.1, 1.6);
      else { b.burst = (b.burst || 0) + 1; if (b.burst >= 4) { b.burst = 0; b.cool = rand(0.7, 1.4); } else b.cool = 0.16; }
    }
  } else {
    if (!b.wp || b.wpT <= 0 || Math.hypot(b.wp.x - b.x, b.wp.z - b.z) < 3) pickWaypoint(b);
    if (outsideStorm(b) && b.wpT < 4) pickWaypoint(b);
    const dx = b.wp.x - b.x, dz = b.wp.z - b.z, want = Math.atan2(-dx, -dz);
    b.yaw += clamp(angDiff(want, b.yaw), -4 * dt, 4 * dt);
    mx = -Math.sin(b.yaw); mz = -Math.cos(b.yaw); speed = outsideStorm(b) ? 7 : 5;
  }
  b.vx += (mx * speed - b.vx) * Math.min(1, dt * 10); b.vz += (mz * speed - b.vz) * Math.min(1, dt * 10);
  moveActor(b, dt);
  // unstick: jump / repick
  b.stuckT += dt;
  if (b.stuckT > 0.6) {
    const moved = Math.hypot(b.x - b.lx, b.z - b.lz); b.lx = b.x; b.lz = b.z; b.stuckT = 0;
    if ((mx || mz) && moved < 0.5 && b.grounded) { b.vy = 8.8; b.grounded = false; if (Math.random() < 0.4) b.wpT = 0; }
  }
  if (outsideStorm(b)) { b.stormT = (b.stormT || 0) + dt; if (b.stormT >= 1) { b.stormT = 0; damageActor(b, storm.dps, null); } }
  b.ch.group.position.set(b.x, b.y, b.z); b.ch.group.rotation.y = b.yaw;
  animateChar(b.ch, Math.hypot(b.vx, b.vz) > 0.5, b.anim, 0, 'gun');
}

/* ------------------------------------------------------------------- HUD */
const hotbarDefs = [
  { id: 'pickaxe', k: '1', n: 'Pickaxe' }, { id: 'ar', k: '2', n: 'Assault Rifle' }, { id: 'sg', k: '3', n: 'Pump Shotgun' },
  { id: 'wall', k: 'Z', n: 'Wall', sep: true }, { id: 'floor', k: 'X', n: 'Floor' }, { id: 'ramp', k: 'C', n: 'Ramp' },
];
const hotbar = $('hotbar');
for (const d of hotbarDefs) {
  const s = document.createElement('div'); s.className = 'slot' + (d.sep ? ' sep' : ''); s.id = 'slot-' + d.id;
  s.innerHTML = `<span class="k">${d.k}</span><span class="n">${d.n}</span>`; hotbar.appendChild(s);
}
function refreshHotbar() {
  for (const d of hotbarDefs) {
    const el = $('slot-' + d.id); el.classList.toggle('sel', player.slot === d.id);
    el.classList.toggle('off', d.id === 'sg' && !player.owned.sg);
  }
}
refreshHotbar();
const mm = $('minimap'), mctx = mm.getContext('2d'), mmTerrain = document.createElement('canvas');
mmTerrain.width = mmTerrain.height = 176;
{
  const c = mmTerrain.getContext('2d'), img = c.createImageData(176, 176);
  for (let py = 0; py < 176; py++) for (let px = 0; px < 176; px++) {
    const x = (px / 176) * 400 - 200, z = (py / 176) * 400 - 200, h = terrainH(x, z), i = (py * 176 + px) * 4;
    let r, g, b; if (h < 0) { r = 36; g = 110; b = 170; } else if (h < 0.8) { r = 214; g = 196; b = 130; } else { const k = clamp(h / 12, 0, 1); r = 80 - k * 20; g = 150 - k * 40; b = 60 + k * 20; }
    img.data[i] = r; img.data[i + 1] = g; img.data[i + 2] = b; img.data[i + 3] = 255;
  }
  c.putImageData(img, 0, 0);
}
const toMM = v => (v + 200) / 400 * 176;
function drawMinimap() {
  mctx.drawImage(mmTerrain, 0, 0);
  mctx.save(); mctx.beginPath(); mctx.rect(0, 0, 176, 176);
  mctx.arc(toMM(storm.cx), toMM(storm.cz), storm.r / 400 * 176, 0, TAU, true); mctx.clip();
  mctx.fillStyle = 'rgba(140,50,230,.45)'; mctx.fillRect(0, 0, 176, 176); mctx.restore();
  mctx.strokeStyle = '#fff'; mctx.lineWidth = 1.5; mctx.beginPath(); mctx.arc(toMM(storm.cx), toMM(storm.cz), storm.r / 400 * 176, 0, TAU); mctx.stroke();
  if (!storm.shrinking || true) { mctx.strokeStyle = 'rgba(255,255,255,.6)'; mctx.setLineDash([3, 3]); mctx.beginPath(); mctx.arc(toMM(storm.toX), toMM(storm.toZ), storm.toR / 400 * 176, 0, TAU); mctx.stroke(); mctx.setLineDash([]); }
  mctx.fillStyle = '#c33'; for (const h of world.houses) mctx.fillRect(toMM(h.x) - 1.5, toMM(h.z) - 1.5, 3, 3);
  mctx.save(); mctx.translate(toMM(player.x), toMM(player.z)); mctx.rotate(-player.yaw + Math.PI);
  mctx.fillStyle = '#ffe14a'; mctx.strokeStyle = '#000'; mctx.beginPath(); mctx.moveTo(0, 5); mctx.lineTo(4, -4); mctx.lineTo(-4, -4); mctx.closePath(); mctx.fill(); mctx.stroke(); mctx.restore();
}
function updateHud() {
  $('alive').textContent = `Players left: ${aliveCount()}`;
  $('kills').textContent = `Eliminations: ${player.kills}`;
  $('shieldbar').firstChild.style.width = player.shield + '%'; $('shieldbar').lastChild.textContent = Math.ceil(player.shield);
  $('hpbar').firstChild.style.width = Math.max(0, player.hp) + '%'; $('hpbar').lastChild.textContent = Math.ceil(Math.max(0, player.hp));
  $('wood').textContent = `Wood ${player.wood}`;
  const w = WEAPONS[player.slot];
  $('ammo').innerHTML = w ? (player.reloading > 0 ? 'Reloading…' : `${player.mags[player.slot]} <small>/ ${player.ammo[player.slot]}</small>`) : '';
  const p = PHASES[storm.i], left = Math.max(0, Math.ceil((storm.shrinking ? p.shrink : p.wait) - storm.t));
  $('storm').textContent = `${storm.shrinking ? 'STORM CLOSING' : 'STORM SHRINKS IN'} ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
  $('stormfx').classList.toggle('on', outsideStorm(player));
  const cross = $('crosshair'); const sz = 14 + (player.bloom + (w ? w.spread : 0.02)) * 500 * (mouse.r ? 0.55 : 1);
  cross.style.width = cross.style.height = sz + 'px'; cross.style.margin = `${-sz / 2}px 0 0 ${-sz / 2}px`;
  cross.classList.toggle('hidden', player.phase !== 'ground' || player.building || player.slot === 'pickaxe');
  if (player.phase === 'skydive') $('hint').textContent = player.glider ? 'Glider open — steer with WASD' : 'Freefall — WASD to steer, Space to open glider';
  drawMinimap();
}

/* ----------------------------------------------------------------- input */
document.addEventListener('keydown', e => {
  if (e.repeat && e.code !== 'KeyW') { keys[e.code] = true; return; }
  keys[e.code] = true;
  if (mode !== 'playing') return;
  if (e.code === 'Space' && player.phase === 'skydive' && !player.glider) { player.glider = true; sfx.glide(); }
  if (e.code === 'Digit1' || e.code === 'Digit2' || e.code === 'Digit3') {
    const idx = Number(e.code.slice(5)) - 1;
    if (player.building) selectSlot(['wall', 'floor', 'ramp'][idx]); else selectSlot(['pickaxe', 'ar', 'sg'][idx]);
  }
  if (e.code === 'KeyZ') selectSlot('wall');
  if (e.code === 'KeyX') selectSlot('floor');
  if (e.code === 'KeyC') selectSlot('ramp');
  if (e.code === 'KeyQ') toggleBuild();
  if (e.code === 'KeyR') startReload();
  if (['Space', 'ArrowUp', 'ArrowDown'].includes(e.code)) e.preventDefault();
});
document.addEventListener('keyup', e => { keys[e.code] = false; });
document.addEventListener('mousemove', e => {
  if (mode !== 'playing' || !document.pointerLockElement) return;
  const sens = mouse.r ? 0.0014 : 0.0022;
  player.yaw -= e.movementX * sens; player.pitch = clamp(player.pitch - e.movementY * sens, -1.3, 1.3);
});
canvas.addEventListener('mousedown', e => {
  if (mode !== 'playing') return;
  if (!document.pointerLockElement) { canvas.requestPointerLock?.(); return; }
  if (e.button === 0) { mouse.l = true; mouse.lClick = true; } else if (e.button === 2) mouse.r = true;
});
document.addEventListener('mouseup', e => { if (e.button === 0) mouse.l = false; else if (e.button === 2) mouse.r = false; });
document.addEventListener('contextmenu', e => e.preventDefault());
window.addEventListener('blur', () => { for (const k in keys) keys[k] = false; mouse.l = mouse.r = false; });
document.addEventListener('pointerlockchange', () => {
  if (!document.pointerLockElement && mode === 'playing') { mode = 'paused'; $('pause').classList.remove('hidden'); }
});
$('pause').addEventListener('click', () => { $('pause').classList.add('hidden'); mode = 'playing'; canvas.requestPointerLock?.(); });
$('start').addEventListener('click', () => {
  $('menu').classList.add('hidden'); mode = 'playing'; audio()?.resume?.();
  try { const p = canvas.requestPointerLock?.(); p?.catch?.(() => {}); } catch (e) { /* ignore */ }
});
$('again').addEventListener('click', () => location.reload());

/* ------------------------------------------------------------- main loop */
let last = performance.now(), mmTick = 0;
function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min(0.05, (now - last) / 1000); last = now;
  if (mode === 'playing') {
    time += dt;
    updateStorm(dt);
    updatePlayer(dt);
    for (const b of bots) updateBot(b, dt);
    pc.group.position.set(player.x, player.y, player.z); pc.group.rotation.y = player.yaw;
    animateChar(pc, player.grounded && Math.hypot(player.vx, player.vz) > 0.6, time, player.pitch, player.slot === 'pickaxe' || player.building ? 'pickaxe' : 'gun');
    if (player.building) pc.pick.visible = false;
    if (WEAPONS[player.slot]) pc.gunMesh.material.color.setHex(WEAPONS[player.slot].color);
    updateGhost(); updateFx(dt); updateCamera(dt); updateHud();
    if (player.dead === false && player.hp <= 0) killActor(player, null);
  } else if (mode === 'over' || mode === 'paused') { updateFx(dt); }
  else {
    // menu: slow orbit over the island
    time += dt; const a = time * 0.08;
    camera.position.set(Math.cos(a) * 130, 45, Math.sin(a) * 130); camera.rotation.set(-0.25, -a + Math.PI / 2, 0);
  }
  renderer.render(scene, camera);
}
requestAnimationFrame(frame);
window.__game = { player, bots, world, storm, get mode() { return mode; } };
