/*
 * Procedural SO-ARM101-style desktop arm on a tabletop, rendered with three.js.
 *
 * Everything is generated at runtime (geometry, textures, environment); nothing is
 * downloaded. Units: 1 unit = 10 cm. The pick-and-place loop is driven by real planar
 * inverse kinematics with constant link lengths, so the arm never stretches.
 *
 * This module is loaded lazily (dynamic import) by RobotStage after first paint.
 */
import {
  AdditiveBlending,
  CanvasTexture,
  CatmullRomCurve3,
  CylinderGeometry,
  DirectionalLight,
  Euler,
  ExtrudeGeometry,
  Fog,
  Group,
  HemisphereLight,
  LatheGeometry,
  Mesh,
  MeshBasicMaterial,
  MeshPhysicalMaterial,
  MeshStandardMaterial,
  NeutralToneMapping,
  Object3D,
  PCFShadowMap,
  PerspectiveCamera,
  PlaneGeometry,
  PMREMGenerator,
  PointLight,
  RepeatWrapping,
  Scene,
  Shape,
  SpotLight,
  SRGBColorSpace,
  TorusGeometry,
  TubeGeometry,
  Vector2,
  Vector3,
  WebGLRenderer,
  type BufferGeometry,
  type Material,
  type Texture,
} from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";

export type ScreenPoint = { x: number; y: number };

export interface RobotSceneOptions {
  canvas: HTMLCanvasElement;
  /** Element that follows the picked block (translated in CSS px of the canvas box). */
  label?: HTMLElement | null;
  /** Where the glowing signal trace enters the tabletop, in CSS px of the canvas box. */
  onEntry?: (point: ScreenPoint) => void;
  onReady?: () => void;
  onContextLost?: () => void;
  compact?: boolean;
  /** Seconds of the pick loop to pre-roll before the first frame (used for the poster). */
  initialTime?: number;
}

export interface RobotSceneHandle {
  resize(width: number, height: number): void;
  setRunning(running: boolean): void;
  setPointer(x: number, y: number): void;
  /** Report the first trace point at or right of this x (CSS px of the canvas box). */
  setEntryMinX(x: number): void;
  dispose(): void;
}

/* ---------- arm dimensions (SO-101 proportions, 1 unit = 10 cm) ---------- */
const BASE = new Vector3(2.45, 0, -0.2);
const H0 = 1.12; // shoulder axis height above the table
const L1 = 1.16; // shoulder -> elbow
const L2 = 1.3; // elbow -> wrist
const ROLL_AT = 0.22; // wrist pivot -> wrist-roll frame
const GRASP = 0.58; // roll frame -> grasp centre between the fingertips
const LG = ROLL_AT + GRASP;
const BLOCK = 0.42;
const BLOCK_Y = BLOCK / 2 + 0.004;
const ABOVE = 0.98;
const HOME = new Vector3(1.2, 1.62, 0.3);
const HOME_PHI = -0.62;
const ZONE_A = new Vector3(0.55, BLOCK_Y, -0.55);
const ZONE_B = new Vector3(0.95, BLOCK_Y, 0.85);
const ENTRY = new Vector3(-2.3, 0.012, 1.36);

const PALETTE = {
  cream: 0xe9e0cf,
  servo: 0x121214,
  coral: 0xf07864,
  amber: 0xffb246,
  ink: 0x150a0d,
};

/* ---------- small helpers ---------- */
function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const ease = (t: number) => t * t * t * (t * (t * 6 - 15) + 10);
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

function roundedRect(w: number, h: number, r: number, cx = 0, cy = 0) {
  const s = new Shape();
  const x = cx - w / 2;
  const y = cy - h / 2;
  s.moveTo(x + r, y);
  s.lineTo(x + w - r, y);
  s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r);
  s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h);
  s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r);
  s.quadraticCurveTo(x, y, x + r, y);
  return s;
}

function canvas2d(w: number, h: number) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const ctx = c.getContext("2d");
  if (!ctx) throw new Error("2d canvas unavailable");
  return { c, ctx };
}

/* ---------- procedural textures ---------- */
function woodTexture() {
  const { c, ctx } = canvas2d(1024, 512);
  const rand = mulberry32(7);
  ctx.fillStyle = "#3a2420";
  ctx.fillRect(0, 0, 1024, 512);
  for (let i = 0; i < 260; i++) {
    const y = rand() * 512;
    const amp = 2 + rand() * 6;
    const freq = 0.004 + rand() * 0.01;
    const light = rand() > 0.5;
    ctx.strokeStyle = light ? `rgba(120,78,62,${0.08 + rand() * 0.14})` : `rgba(20,10,10,${0.1 + rand() * 0.2})`;
    ctx.lineWidth = 0.6 + rand() * 2.4;
    ctx.beginPath();
    for (let x = 0; x <= 1024; x += 16) {
      const yy = y + Math.sin(x * freq + i) * amp;
      if (x === 0) ctx.moveTo(x, yy);
      else ctx.lineTo(x, yy);
    }
    ctx.stroke();
  }
  const t = new CanvasTexture(c);
  t.colorSpace = SRGBColorSpace;
  t.wrapS = t.wrapT = RepeatWrapping;
  return t;
}

const MAT = { x0: -2.2, z0: -1.42, w: 3.95, d: 3.04, ppu: 300 };

function matTexture() {
  const W = MAT.w * MAT.ppu;
  const H = MAT.d * MAT.ppu;
  const { c, ctx } = canvas2d(W, H);
  const px = (wx: number) => (wx - MAT.x0) * MAT.ppu;
  const pz = (wz: number) => (wz - MAT.z0) * MAT.ppu;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = "#211719";
  ctx.beginPath();
  ctx.roundRect(0, 0, W, H, 36);
  ctx.fill();
  // fine and major grid (cutting-mat style)
  for (let i = 0; i * 0.25 <= MAT.w; i++) {
    const x = i * 0.25 * MAT.ppu;
    ctx.strokeStyle = i % 4 === 0 ? "rgba(239,232,220,.16)" : "rgba(239,232,220,.06)";
    ctx.lineWidth = i % 4 === 0 ? 2 : 1.4;
    ctx.beginPath();
    ctx.moveTo(x, 40);
    ctx.lineTo(x, H - 40);
    ctx.stroke();
  }
  for (let j = 0; j * 0.25 <= MAT.d; j++) {
    const y = j * 0.25 * MAT.ppu;
    ctx.strokeStyle = j % 4 === 0 ? "rgba(239,232,220,.16)" : "rgba(239,232,220,.06)";
    ctx.lineWidth = j % 4 === 0 ? 2 : 1.4;
    ctx.beginPath();
    ctx.moveTo(40, y);
    ctx.lineTo(W - 40, y);
    ctx.stroke();
  }
  // ruler ticks
  ctx.fillStyle = "rgba(239,232,220,.32)";
  for (let i = 0; i <= MAT.w * 10; i++) {
    const x = (i / 10) * MAT.ppu;
    const len = i % 10 === 0 ? 26 : i % 5 === 0 ? 16 : 9;
    ctx.fillRect(x - 1, 8, 2, len);
  }
  // zones
  const zone = (z: Vector3, color: string, label: string) => {
    const s = 0.62 * MAT.ppu;
    const x = px(z.x) - s / 2;
    const y = pz(z.z) - s / 2;
    ctx.strokeStyle = color;
    ctx.lineWidth = 5;
    ctx.setLineDash([22, 14]);
    ctx.strokeRect(x, y, s, s);
    ctx.setLineDash([]);
    ctx.lineWidth = 9;
    const k = 36;
    for (const [cx, cy, dx, dy] of [
      [x, y, 1, 1],
      [x + s, y, -1, 1],
      [x, y + s, 1, -1],
      [x + s, y + s, -1, -1],
    ]) {
      ctx.beginPath();
      ctx.moveTo(cx, cy + dy * k);
      ctx.lineTo(cx, cy);
      ctx.lineTo(cx + dx * k, cy);
      ctx.stroke();
    }
    ctx.fillStyle = color;
    ctx.font = "600 44px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.fillText(label, x + 4, y + s + 52);
  };
  zone(ZONE_A, "rgba(239,232,220,.55)", "A");
  zone(ZONE_B, "rgba(255,178,70,.85)", "B");
  ctx.fillStyle = "rgba(239,232,220,.28)";
  ctx.font = "500 34px ui-monospace, SFMono-Regular, Menlo, monospace";
  ctx.fillText("H2M · WORKCELL 01", 70, H - 64);
  ctx.fillStyle = "rgba(240,120,100,.75)";
  ctx.fillRect(W - 170, H - 78, 100, 8);
  const t = new CanvasTexture(c);
  t.colorSpace = SRGBColorSpace;
  return t;
}

function layerLinesTexture() {
  const { c, ctx } = canvas2d(8, 64);
  for (let y = 0; y < 64; y++) {
    const v = 128 + Math.sin((y / 64) * Math.PI * 16) * 70;
    ctx.fillStyle = `rgb(${v},${v},${v})`;
    ctx.fillRect(0, y, 8, 1);
  }
  const t = new CanvasTexture(c);
  t.wrapS = t.wrapT = RepeatWrapping;
  t.repeat.set(1, 5);
  return t;
}

function blobTexture() {
  const { c, ctx } = canvas2d(128, 128);
  const g = ctx.createRadialGradient(64, 64, 4, 64, 64, 64);
  g.addColorStop(0, "rgba(0,0,0,.62)");
  g.addColorStop(0.55, "rgba(0,0,0,.22)");
  g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  return new CanvasTexture(c);
}

function pulseTexture() {
  const { c, ctx } = canvas2d(512, 4);
  const g = ctx.createLinearGradient(0, 0, 512, 0);
  g.addColorStop(0, "rgba(255,255,255,.22)");
  g.addColorStop(0.62, "rgba(255,255,255,.22)");
  g.addColorStop(0.86, "rgba(255,255,255,1)");
  g.addColorStop(0.9, "rgba(255,255,255,.35)");
  g.addColorStop(1, "rgba(255,255,255,.22)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 512, 4);
  const t = new CanvasTexture(c);
  t.wrapS = RepeatWrapping;
  t.repeat.set(2, 1);
  return t;
}

/* ---------- scene ---------- */
export function createRobotScene(options: RobotSceneOptions): RobotSceneHandle {
  const { canvas, label, onEntry, onReady, onContextLost, compact = false, initialTime = 0 } = options;

  const renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setClearColor(0x000000, 0);
  renderer.toneMapping = NeutralToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = PCFShadowMap;

  const scene = new Scene();
  const pmrem = new PMREMGenerator(renderer);
  const room = new RoomEnvironment();
  const envTarget = pmrem.fromScene(room, 0.04);
  scene.environment = envTarget.texture;
  scene.environmentIntensity = 0.55;
  room.traverse((o) => {
    const m = o as Mesh;
    if (m.isMesh) {
      m.geometry.dispose();
      (m.material as Material).dispose();
    }
  });
  scene.fog = new Fog(PALETTE.ink, 14, 34);

  const camera = new PerspectiveCamera(28, 1, 0.1, 100);

  const textures: Texture[] = [];
  const track = <T extends Texture>(t: T) => {
    textures.push(t);
    return t;
  };
  const maxAniso = renderer.capabilities.getMaxAnisotropy();

  /* materials */
  const layer = track(layerLinesTexture());
  const cream = new MeshPhysicalMaterial({ color: PALETTE.cream, roughness: 0.6, clearcoat: 0.12, clearcoatRoughness: 0.55, bumpMap: layer, bumpScale: 0.6 });
  const servoMat = new MeshPhysicalMaterial({ color: PALETTE.servo, roughness: 0.36, clearcoat: 0.45, clearcoatRoughness: 0.3 });
  const hornMat = new MeshStandardMaterial({ color: 0x2b2d31, metalness: 0.85, roughness: 0.3 });
  const steel = new MeshStandardMaterial({ color: 0xc9ccd2, metalness: 1, roughness: 0.24 });
  const gunmetal = new MeshStandardMaterial({ color: 0x45484e, metalness: 0.82, roughness: 0.34 });
  const cableMat = new MeshStandardMaterial({ color: 0x1b1b1e, roughness: 0.5 });
  const rubber = new MeshStandardMaterial({ color: 0x0c0c0d, roughness: 0.9 });
  const coralGlow = new MeshStandardMaterial({ color: 0x3a1010, emissive: PALETTE.coral, emissiveIntensity: 2.4, roughness: 0.4 });
  const amberGlow = new MeshStandardMaterial({ color: 0x3a2008, emissive: PALETTE.amber, emissiveIntensity: 2.2, roughness: 0.4 });
  const labelMat = new MeshStandardMaterial({ color: 0x8c8f96, roughness: 0.45, metalness: 0.2 });
  const wood = track(woodTexture());
  wood.repeat.set(0.16, 0.32);
  wood.anisotropy = maxAniso;
  const tableMat = new MeshStandardMaterial({ map: wood, roughness: 0.52, color: 0xffffff });
  const matTex = track(matTexture());
  matTex.anisotropy = maxAniso;
  const matMat = new MeshStandardMaterial({ map: matTex, transparent: true, roughness: 0.82 });
  const blob = track(blobTexture());
  const blobMat = new MeshBasicMaterial({ map: blob, transparent: true, depthWrite: false, toneMapped: false });

  const shadowed = (m: Mesh, receive = false) => {
    m.castShadow = true;
    m.receiveShadow = receive;
    return m;
  };

  /* table + mat */
  const table = new Group();
  scene.add(table);
  const TW = 5.62;
  const TD = 3.84;
  const TX = 0.44;
  const slabGeo = new ExtrudeGeometry(roundedRect(TW - 0.06, TD - 0.06, 0.16), { depth: 0.3, bevelEnabled: true, bevelThickness: 0.03, bevelSize: 0.03, bevelSegments: 4, curveSegments: 10 });
  slabGeo.rotateX(-Math.PI / 2);
  slabGeo.translate(TX, -0.33, 0);
  const slab = new Mesh(slabGeo, tableMat);
  slab.receiveShadow = true;
  table.add(slab);
  // Soft shadow on an implied floor below the table, so the slab sits in space.
  const floorGeo = new PlaneGeometry(1, 1);
  floorGeo.rotateX(-Math.PI / 2);
  const floorShadow = new Mesh(floorGeo, blobMat.clone());
  (floorShadow.material as MeshBasicMaterial).opacity = 0.9;
  floorShadow.scale.set(TW * 1.5, 1, TD * 1.7);
  floorShadow.position.set(TX, -1.25, 0.15);
  table.add(floorShadow);

  const matGeo = new PlaneGeometry(MAT.w, MAT.d);
  matGeo.rotateX(-Math.PI / 2);
  const mat = new Mesh(matGeo, matMat);
  mat.position.set(MAT.x0 + MAT.w / 2, 0.004, MAT.z0 + MAT.d / 2);
  mat.receiveShadow = true;
  table.add(mat);

  const blobAt = (x: number, z: number, sx: number, sz = sx, opacity = 1) => {
    const g = new PlaneGeometry(1, 1);
    g.rotateX(-Math.PI / 2);
    const m = new Mesh(g, opacity === 1 ? blobMat : blobMat.clone());
    if (opacity !== 1) (m.material as MeshBasicMaterial).opacity = opacity;
    m.scale.set(sx, 1, sz);
    m.position.set(x, 0.008, z);
    m.renderOrder = 1;
    table.add(m);
    return m;
  };

  /* blocks */
  const blockGeo = new RoundedBoxGeometry(BLOCK, BLOCK, BLOCK, 4, 0.035);
  const makeBlock = (color: number, x: number, z: number, yaw: number) => {
    const m = shadowed(new Mesh(blockGeo, new MeshPhysicalMaterial({ color, roughness: 0.32, clearcoat: 0.6, clearcoatRoughness: 0.25 })), true);
    m.position.set(x, BLOCK_Y, z);
    m.rotation.y = yaw;
    scene.add(m);
    return m;
  };
  const target = makeBlock(PALETTE.amber, ZONE_A.x, ZONE_A.z, 0.14);
  const targetBlob = blobAt(ZONE_A.x, ZONE_A.z, 0.85);
  makeBlock(PALETTE.coral, -0.55, 0.42, -0.35);
  blobAt(-0.55, 0.42, 0.85);
  makeBlock(0xe6ddcc, -1.12, -0.66, 0.22);
  blobAt(-1.12, -0.66, 0.85);
  makeBlock(0x6b1a2a, -0.35, -1.0, 0.6);
  blobAt(-0.35, -1.0, 0.85);
  const cyl = shadowed(new Mesh(new CylinderGeometry(0.2, 0.2, 0.5, 40), new MeshPhysicalMaterial({ color: 0x7f9488, roughness: 0.35, clearcoat: 0.5 })), true);
  cyl.position.set(-1.6, 0.254, 0.5);
  scene.add(cyl);
  blobAt(-1.6, 0.5, 0.75);

  /* signal trace on the mat + receiver ring */
  const pulse = track(pulseTexture());
  const traceCurve = new CatmullRomCurve3([
    ENTRY,
    new Vector3(-1.3, 0.012, 1.42),
    new Vector3(0.15, 0.012, 1.4),
    new Vector3(1.75, 0.012, 1.24),
    new Vector3(2.28, 0.012, 0.72),
    new Vector3(2.42, 0.012, 0.36),
  ]);
  const traceMat = new MeshBasicMaterial({ color: PALETTE.amber, map: pulse, transparent: true, blending: AdditiveBlending, depthWrite: false, toneMapped: false });
  const trace = new Mesh(new TubeGeometry(traceCurve, 220, 0.016, 6), traceMat);
  scene.add(trace);
  const traceSamples = traceCurve.getSpacedPoints(90);
  const traceGlowMat = new MeshBasicMaterial({ color: PALETTE.coral, map: pulse, transparent: true, opacity: 0.32, blending: AdditiveBlending, depthWrite: false, toneMapped: false });
  const traceGlow = new Mesh(new TubeGeometry(traceCurve, 220, 0.06, 6), traceGlowMat);
  traceGlow.scale.y = 0.2;
  traceGlow.position.y = 0.006;
  scene.add(traceGlow);
  const ringMat = new MeshBasicMaterial({ color: PALETTE.amber, transparent: true, opacity: 0.6, blending: AdditiveBlending, depthWrite: false, toneMapped: false });
  const ring = new Mesh(new TorusGeometry(0.7, 0.012, 8, 96), ringMat);
  ring.rotation.x = -Math.PI / 2;
  ring.position.set(BASE.x, 0.014, BASE.z);
  scene.add(ring);
  const receiverLight = new PointLight(PALETTE.amber, 1.4, 3.2, 2);
  receiverLight.position.set(BASE.x - 0.3, 0.35, BASE.z + 0.6);
  scene.add(receiverLight);

  /* ---------- arm ---------- */
  const arm = new Group();
  arm.position.copy(BASE);
  scene.add(arm);
  blobAt(BASE.x, BASE.z, 1.7, 1.55);

  // Stadium plate with pivot holes and a lightening slot, lying in XY, extruded in Z.
  const plateGeoCache = new Map<string, BufferGeometry>();
  const plateGeo = (len: number, width: number, thick: number) => {
    const key = `${len}:${width}:${thick}`;
    const hit = plateGeoCache.get(key);
    if (hit) return hit;
    const r = width / 2;
    const s = new Shape();
    s.absarc(0, 0, r, Math.PI / 2, (3 * Math.PI) / 2, false);
    s.lineTo(len, -r);
    s.absarc(len, 0, r, -Math.PI / 2, Math.PI / 2, false);
    s.lineTo(0, r);
    const hole = (x: number, rr: number) => {
      const h = new Shape();
      h.absarc(x, 0, rr, 0, Math.PI * 2, true);
      s.holes.push(h);
    };
    hole(0, 0.05);
    hole(len, 0.05);
    if (len > 0.7) {
      const slot = new Shape();
      const a = 0.32;
      const b = len - 0.32;
      const sr = width * 0.18;
      slot.absarc(a, 0, sr, Math.PI / 2, (3 * Math.PI) / 2, false);
      slot.lineTo(b, -sr);
      slot.absarc(b, 0, sr, -Math.PI / 2, Math.PI / 2, false);
      slot.lineTo(a, sr);
      s.holes.push(slot);
    }
    const g = new ExtrudeGeometry(s, { depth: thick, bevelEnabled: true, bevelThickness: 0.008, bevelSize: 0.008, bevelSegments: 2, curveSegments: 20 });
    g.translate(0, 0, -thick / 2);
    plateGeoCache.set(key, g);
    return g;
  };

  const twinPlates = (parent: Object3D, len: number, z: number, width = 0.3) => {
    for (const side of [-1, 1]) {
      const m = shadowed(new Mesh(plateGeo(len, width, 0.04), cream), true);
      m.position.z = side * z;
      parent.add(m);
    }
  };

  const servoBody = new RoundedBoxGeometry(0.45, 0.25, 0.3, 3, 0.028);
  const servoEar = new RoundedBoxGeometry(0.08, 0.25, 0.32, 2, 0.012);
  const hornGeo = new CylinderGeometry(0.1, 0.1, 0.035, 40);
  hornGeo.rotateX(Math.PI / 2);
  const capGeo = new CylinderGeometry(0.066, 0.066, 0.016, 32);
  capGeo.rotateX(Math.PI / 2);
  const screwGeo = new CylinderGeometry(0.018, 0.018, 0.012, 12);
  screwGeo.rotateX(Math.PI / 2);
  const accentGeo = new TorusGeometry(0.105, 0.011, 10, 64);
  const stickerGeo = new PlaneGeometry(0.2, 0.11);

  /** Servo whose output axis is local Z at the origin; body extends toward -X. */
  const servo = (parent: Object3D, accent: Material, plateZ: number) => {
    const g = new Group();
    const body = shadowed(new Mesh(servoBody, servoMat), true);
    body.position.x = -0.13;
    g.add(body);
    for (const ex of [-0.38, 0.12]) {
      const ear = shadowed(new Mesh(servoEar, servoMat));
      ear.position.x = ex;
      ear.scale.set(0.5, 0.82, 1);
      g.add(ear);
    }
    const sticker = new Mesh(stickerGeo, labelMat);
    sticker.position.set(-0.17, 0.1255, 0);
    sticker.rotation.x = -Math.PI / 2;
    g.add(sticker);
    for (const side of [-1, 1]) {
      const horn = new Mesh(hornGeo, hornMat);
      horn.position.z = side * 0.167;
      g.add(horn);
      const cap = new Mesh(capGeo, hornMat);
      cap.position.z = side * (plateZ + 0.028);
      g.add(cap);
      const screw = new Mesh(screwGeo, steel);
      screw.position.z = side * (plateZ + 0.038);
      g.add(screw);
      const ring = new Mesh(accentGeo, accent);
      ring.position.z = side * (plateZ + 0.024);
      g.add(ring);
    }
    parent.add(g);
    return g;
  };

  const cable = (parent: Object3D, pts: [number, number, number][], radius = 0.019) => {
    const curve = new CatmullRomCurve3(pts.map(([x, y, z]) => new Vector3(x, y, z)));
    const m = shadowed(new Mesh(new TubeGeometry(curve, 48, radius, 7), cableMat));
    parent.add(m);
    return m;
  };

  // Base: printed housing, clamp tab, bearing.
  const plate = shadowed(new Mesh(new RoundedBoxGeometry(0.95, 0.08, 0.85, 3, 0.03), cream), true);
  plate.position.y = 0.04;
  arm.add(plate);
  const tab = shadowed(new Mesh(new RoundedBoxGeometry(0.9, 0.06, 0.46, 3, 0.02), cream), true);
  tab.position.set(0.45, 0.03, 0);
  arm.add(tab);
  const housing = shadowed(
    new Mesh(
      new LatheGeometry(
        [new Vector2(0, 0.08), new Vector2(0.41, 0.08), new Vector2(0.42, 0.1), new Vector2(0.4, 0.14), new Vector2(0.36, 0.46), new Vector2(0.34, 0.5), new Vector2(0, 0.5)],
        64,
      ),
      cream,
    ),
    true,
  );
  arm.add(housing);
  const bearing = shadowed(new Mesh(new CylinderGeometry(0.335, 0.335, 0.04, 64), gunmetal));
  bearing.position.y = 0.52;
  arm.add(bearing);

  const pan = new Group();
  arm.add(pan);
  const turntable = shadowed(new Mesh(new CylinderGeometry(0.32, 0.34, 0.07, 64), cream), true);
  turntable.position.y = 0.575;
  pan.add(turntable);
  const panRing = new Mesh(new TorusGeometry(0.33, 0.01, 8, 96), coralGlow);
  panRing.rotation.x = Math.PI / 2;
  panRing.position.y = 0.545;
  pan.add(panRing);
  // shoulder bracket ("tombstone" uprights)
  const tomb = new Shape();
  tomb.moveTo(-0.2, 0.6);
  tomb.lineTo(0.2, 0.6);
  tomb.lineTo(0.2, H0);
  tomb.absarc(0, H0, 0.2, 0, Math.PI, false);
  tomb.lineTo(-0.2, 0.6);
  const holeS = new Shape();
  holeS.absarc(0, H0, 0.05, 0, Math.PI * 2, true);
  tomb.holes.push(holeS);
  const tombGeo = new ExtrudeGeometry(tomb, { depth: 0.04, bevelEnabled: true, bevelThickness: 0.008, bevelSize: 0.008, bevelSegments: 2, curveSegments: 20 });
  tombGeo.translate(0, 0, -0.02);
  for (const side of [-1, 1]) {
    const m = shadowed(new Mesh(tombGeo, cream), true);
    m.position.z = side * 0.205;
    pan.add(m);
  }
  const shoulderServo = servo(pan, coralGlow, 0.245);
  shoulderServo.position.y = H0;
  shoulderServo.rotation.z = Math.PI / 2; // body hangs down inside the bracket
  cable(pan, [
    [0.05, 0.6, 0.0],
    [0.24, 0.72, 0.02],
    [0.2, 0.92, 0.04],
    [0.08, H0 - 0.38, 0.03],
  ]);

  // Upper arm
  const shoulder = new Group();
  shoulder.position.y = H0;
  pan.add(shoulder);
  twinPlates(shoulder, L1, 0.245);
  const spacer1 = shadowed(new Mesh(new RoundedBoxGeometry(0.12, 0.2, 0.45, 2, 0.02), cream));
  spacer1.position.x = 0.32;
  shoulder.add(spacer1);
  const elbowServo = servo(shoulder, amberGlow, 0.245);
  elbowServo.position.x = L1;
  cable(shoulder, [
    [0.12, 0.12, 0.06],
    [0.3, 0.2, 0.06],
    [L1 * 0.55, 0.215, 0.05],
    [L1 - 0.4, 0.19, 0.06],
    [L1 - 0.3, 0.11, 0.06],
  ]);

  // Forearm
  const elbow = new Group();
  elbow.position.x = L1;
  shoulder.add(elbow);
  twinPlates(elbow, L2, 0.205);
  const spacer2 = shadowed(new Mesh(new RoundedBoxGeometry(0.12, 0.2, 0.37, 2, 0.02), cream));
  spacer2.position.x = 0.36;
  elbow.add(spacer2);
  const wristServo = servo(elbow, coralGlow, 0.245);
  wristServo.position.x = L2;
  cable(elbow, [
    [0.1, -0.12, 0.05],
    [0.32, -0.19, 0.05],
    [L2 * 0.55, -0.205, 0.04],
    [L2 - 0.4, -0.18, 0.05],
    [L2 - 0.3, -0.1, 0.05],
  ]);

  // Wrist bracket + roll + gripper
  const wrist = new Group();
  wrist.position.x = L2;
  elbow.add(wrist);
  twinPlates(wrist, 0.18, 0.245, 0.28);
  const cross = shadowed(new Mesh(new RoundedBoxGeometry(0.06, 0.28, 0.53, 2, 0.02), cream));
  cross.position.x = 0.2;
  wrist.add(cross);

  const roll = new Group();
  roll.position.x = ROLL_AT;
  wrist.add(roll);
  const rollServo = shadowed(new Mesh(new RoundedBoxGeometry(0.2, 0.24, 0.3, 3, 0.025), servoMat));
  rollServo.position.x = 0.1;
  roll.add(rollServo);
  const rollRing = new Mesh(new TorusGeometry(0.11, 0.01, 8, 64), amberGlow);
  rollRing.rotation.y = Math.PI / 2;
  rollRing.position.x = 0.005;
  roll.add(rollRing);
  const palm = shadowed(new Mesh(new RoundedBoxGeometry(0.12, 0.26, 0.6, 3, 0.03), cream), true);
  palm.position.x = 0.26;
  roll.add(palm);
  const gripServo = shadowed(new Mesh(new RoundedBoxGeometry(0.3, 0.14, 0.2, 3, 0.022), servoMat));
  gripServo.position.set(0.17, 0.2, 0.16);
  roll.add(gripServo);
  const gripRing = new Mesh(new TorusGeometry(0.06, 0.008, 8, 48), coralGlow);
  gripRing.position.set(0.28, 0.2, 0.262);
  roll.add(gripRing);
  cable(roll, [
    [0.02, 0.13, 0.12],
    [0.08, 0.2, 0.06],
    [0.1, 0.26, 0.12],
  ], 0.014);

  const finger = new Shape();
  finger.moveTo(0, -0.085);
  finger.lineTo(0.3, -0.07);
  finger.quadraticCurveTo(0.44, -0.05, 0.44, -0.035);
  finger.lineTo(0.44, 0.035);
  finger.quadraticCurveTo(0.44, 0.05, 0.3, 0.07);
  finger.lineTo(0, 0.085);
  finger.lineTo(0, -0.085);
  const fingerGeo = new ExtrudeGeometry(finger, { depth: 0.055, bevelEnabled: true, bevelThickness: 0.008, bevelSize: 0.008, bevelSegments: 2, curveSegments: 8 });
  const padGeo = new RoundedBoxGeometry(0.2, 0.1, 0.014, 2, 0.005);

  const fixedJaw = shadowed(new Mesh(fingerGeo, cream), true);
  fixedJaw.position.set(0.28, 0, -0.283);
  roll.add(fixedJaw);
  const fixedPad = new Mesh(padGeo, rubber);
  fixedPad.position.set(0.6, 0, -0.221);
  roll.add(fixedPad);

  const jaw = new Group();
  jaw.position.set(0.3, 0, 0.21);
  roll.add(jaw);
  const movingJaw = shadowed(new Mesh(fingerGeo, cream), true);
  movingJaw.position.set(-0.02, 0, 0.018);
  jaw.add(movingJaw);
  const movingPad = new Mesh(padGeo, rubber);
  movingPad.position.set(0.3, 0, 0.011);
  jaw.add(movingPad);
  const jawPivot = new Mesh(new CylinderGeometry(0.035, 0.035, 0.2, 20), steel);
  jawPivot.position.set(0, 0, 0.03);
  jaw.add(jawPivot);

  // Clamp on the right table edge (table edge at x = TX + TW/2).
  const edge = TX + TW / 2;
  const clamp3 = new Group();
  clamp3.position.z = BASE.z;
  scene.add(clamp3);
  const cBox = (w: number, h: number, d: number, x: number, y: number, matl: Material = gunmetal) => {
    const m = shadowed(new Mesh(new RoundedBoxGeometry(w, h, d, 2, Math.min(w, h, d) * 0.25), matl));
    m.position.set(x, y, 0);
    clamp3.add(m);
    return m;
  };
  cBox(0.42, 0.08, 0.22, edge - 0.04, 0.14);
  cBox(0.12, 1.06, 0.22, edge + 0.13, -0.33);
  cBox(0.42, 0.08, 0.22, edge - 0.04, -0.82);
  cBox(0.2, 0.05, 0.2, edge - 0.12, 0.085, rubber);
  const screw = shadowed(new Mesh(new CylinderGeometry(0.028, 0.028, 0.62, 16), steel));
  screw.position.set(edge - 0.15, -0.68, 0);
  clamp3.add(screw);
  const footPad = shadowed(new Mesh(new CylinderGeometry(0.09, 0.09, 0.03, 24), gunmetal));
  footPad.position.set(edge - 0.15, -0.375, 0);
  clamp3.add(footPad);
  const handle = shadowed(new Mesh(new CylinderGeometry(0.024, 0.024, 0.5, 12), steel));
  handle.rotation.x = Math.PI / 2;
  handle.position.set(edge - 0.15, -0.98, 0);
  clamp3.add(handle);

  // Controller board + cables off the back edge.
  const board = shadowed(new Mesh(new RoundedBoxGeometry(0.62, 0.05, 0.42, 2, 0.01), new MeshStandardMaterial({ color: 0x1c2430, roughness: 0.5 })), true);
  board.position.set(1.85, 0.03, -1.35);
  board.rotation.y = 0.22;
  scene.add(board);
  const led = new Mesh(new CylinderGeometry(0.02, 0.02, 0.02, 12), amberGlow);
  led.position.set(1.65, 0.065, -1.3);
  scene.add(led);
  const cap = shadowed(new Mesh(new CylinderGeometry(0.06, 0.06, 0.14, 20), servoMat));
  cap.position.set(2.0, 0.12, -1.42);
  scene.add(cap);
  blobAt(1.85, -1.35, 0.95, 0.75, 0.6);
  cable(scene, [
    [BASE.x - 0.1, 0.12, BASE.z - 0.42],
    [2.25, 0.03, -0.95],
    [2.05, 0.025, -1.2],
    [2.0, 0.06, -1.32],
  ]);
  cable(scene, [
    [1.6, 0.04, -1.5],
    [1.45, 0.025, -1.7],
    [1.5, 0.02, -1.88],
    [1.55, -0.2, -1.96],
    [1.6, -0.9, -1.98],
  ], 0.022);

  /* ---------- lights ---------- */
  const hemi = new HemisphereLight(0xffe2cf, 0x2a0c14, 0.45);
  scene.add(hemi);
  const key = new DirectionalLight(0xfff0e0, 2.6);
  key.position.set(-2.4, 7.5, 5.2);
  key.target.position.set(0.4, 0, 0);
  key.castShadow = true;
  key.shadow.mapSize.set(compact ? 1024 : 2048, compact ? 1024 : 2048);
  key.shadow.camera.left = -4.4;
  key.shadow.camera.right = 4.4;
  key.shadow.camera.top = 3.6;
  key.shadow.camera.bottom = -3.6;
  key.shadow.camera.near = 1;
  key.shadow.camera.far = 20;
  key.shadow.bias = -0.0004;
  key.shadow.normalBias = 0.02;
  key.shadow.radius = 5;
  scene.add(key, key.target);
  const rim = new SpotLight(PALETTE.coral, 70, 16, 0.55, 0.7, 1.6);
  rim.position.set(-3.8, 4.2, -4.6);
  rim.target.position.set(1.6, 1.0, 0);
  scene.add(rim, rim.target);
  const back = new SpotLight(0xffc9a0, 30, 14, 0.5, 0.8, 1.6);
  back.position.set(5.5, 3.6, -3.4);
  back.target.position.set(1.8, 1.0, 0);
  scene.add(back, back.target);

  /* ---------- kinematics ---------- */
  const panAngle = (p: Vector3) => Math.atan2(-(p.z - BASE.z), p.x - BASE.x);
  const wrapQuarter = (a: number) => {
    const q = Math.PI / 2;
    let v = ((a % q) + q) % q;
    if (v > q / 2) v -= q;
    return v;
  };

  function solve(p: Vector3, phi: number) {
    const vx = p.x - BASE.x;
    const vz = p.z - BASE.z;
    const r = Math.hypot(vx, vz);
    const h = p.y - H0;
    const wr = r - LG * Math.cos(phi);
    const wh = h - LG * Math.sin(phi);
    const d = clamp(Math.hypot(wr, wh), Math.abs(L1 - L2) + 0.01, L1 + L2 - 0.001);
    const a = Math.atan2(wh, wr) + Math.acos(clamp((L1 * L1 + d * d - L2 * L2) / (2 * L1 * d), -1, 1));
    const ex = L1 * Math.cos(a);
    const eh = L1 * Math.sin(a);
    const b = Math.atan2(wh - eh, wr - ex);
    pan.rotation.y = Math.atan2(-vz, vx);
    shoulder.rotation.z = a;
    elbow.rotation.z = b - a;
    wrist.rotation.z = phi - b;
  }

  type Key = { dur: number; pos: Vector3; phi: number; grip: number; roll: number; arc?: boolean; event?: "grab" | "release" };
  type Pose = { pos: Vector3; phi: number; grip: number; roll: number };
  const yawOf = (o: Object3D) => new Euler().setFromQuaternion(o.quaternion, "YXZ").y;

  function plan(from: Vector3, fromYaw: number, to: Vector3): Key[] {
    const rho = wrapQuarter(panAngle(from) - fromYaw);
    const up = (v: Vector3) => new Vector3(v.x, ABOVE, v.z);
    const down = -Math.PI / 2;
    return [
      { dur: 1.5, pos: up(from), phi: down, grip: 1, roll: rho },
      { dur: 0.95, pos: from.clone(), phi: down, grip: 1, roll: rho },
      { dur: 0.5, pos: from.clone(), phi: down, grip: 0, roll: rho, event: "grab" },
      { dur: 0.9, pos: up(from), phi: down, grip: 0, roll: rho },
      { dur: 1.7, pos: up(to), phi: down, grip: 0, roll: rho, arc: true },
      { dur: 0.95, pos: to.clone(), phi: down, grip: 0, roll: rho, event: "release" },
      { dur: 0.5, pos: to.clone(), phi: down, grip: 1, roll: rho },
      { dur: 0.9, pos: up(to), phi: down, grip: 1, roll: rho },
      { dur: 1.5, pos: HOME.clone(), phi: HOME_PHI, grip: 0.4, roll: 0 },
      { dur: 1.1, pos: HOME.clone(), phi: HOME_PHI, grip: 0.4, roll: 0 },
    ];
  }

  let pose: Pose = { pos: HOME.clone(), phi: HOME_PHI, grip: 0.4, roll: 0 };
  let start: Pose = { ...pose, pos: pose.pos.clone() };
  let keys: Key[] = plan(target.position.clone(), yawOf(target), ZONE_B);
  let seg = 0;
  let segT = 0;
  let atA = true;
  const tmp = new Vector3();

  function apply(p: Pose) {
    solve(p.pos, p.phi);
    roll.rotation.x = p.roll;
    jaw.rotation.y = -0.46 * p.grip;
  }

  function step(dt: number) {
    let remaining = dt;
    while (remaining > 0) {
      const k = keys[seg];
      const left = k.dur - segT;
      const used = Math.min(left, remaining);
      segT += used;
      remaining -= used;
      const t = ease(clamp(segT / k.dur, 0, 1));
      tmp.lerpVectors(start.pos, k.pos, t);
      if (k.arc) tmp.y += Math.sin(Math.PI * t) * 0.32;
      pose = {
        pos: tmp.clone(),
        phi: start.phi + (k.phi - start.phi) * t,
        grip: start.grip + (k.grip - start.grip) * t,
        roll: start.roll + (k.roll - start.roll) * t,
      };
      if (segT >= k.dur - 1e-6) {
        apply(pose);
        if (k.event === "grab") {
          roll.attach(target);
          targetBlob.visible = false;
        } else if (k.event === "release") {
          scene.attach(target);
          target.position.y = BLOCK_Y;
          target.rotation.set(0, yawOf(target), 0);
          targetBlob.position.set(target.position.x, 0.008, target.position.z);
          targetBlob.visible = true;
        }
        start = { pos: k.pos.clone(), phi: k.phi, grip: k.grip, roll: k.roll };
        seg += 1;
        segT = 0;
        if (seg >= keys.length) {
          atA = !atA;
          keys = plan(target.position.clone(), yawOf(target), atA ? ZONE_B : ZONE_A);
          seg = 0;
        }
      }
    }
    apply(pose);
  }

  /* ---------- camera framing ---------- */
  const look = new Vector3(0.1, 0.55, 0.1);
  let BASE_AZ = -0.24;
  let BASE_EL = 0.38;
  let dist = 14;
  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  let viewW = 1;
  let viewH = 1;
  const corners: Vector3[] = [];
  const setCorners = (xMin: number) => {
    corners.length = 0;
    for (const x of [xMin, 3.62]) for (const y of [-0.7, 2.3]) for (const z of [-1.95, 1.95]) corners.push(new Vector3(x, y, z));
  };

  function placeCamera(az: number, el: number) {
    camera.position.set(look.x + dist * Math.sin(az) * Math.cos(el), look.y + dist * Math.sin(el), look.z + dist * Math.cos(az) * Math.cos(el));
    camera.lookAt(look);
    camera.updateMatrixWorld();
  }

  function frame() {
    // Fit the diorama into a focus band of the canvas. In the tall desktop column the
    // left of the canvas sits under the glass compiler panel, so the scene is pushed right.
    const tall = viewW / viewH < 1;
    BASE_AZ = tall ? -0.58 : -0.24;
    BASE_EL = tall ? 0.44 : 0.38;
    const fl = tall ? 0.0 : 0.02;
    setCorners(tall ? -1.25 : -2.4);
    const focusW = viewW * (0.99 - fl);
    camera.aspect = focusW / viewH;
    camera.clearViewOffset();
    camera.updateProjectionMatrix();
    const p = new Vector3();
    const bounds = () => {
      let x0 = Infinity;
      let x1 = -Infinity;
      let y0 = Infinity;
      let y1 = -Infinity;
      for (const c of corners) {
        p.copy(c).project(camera);
        x0 = Math.min(x0, p.x);
        x1 = Math.max(x1, p.x);
        y0 = Math.min(y0, p.y);
        y1 = Math.max(y1, p.y);
      }
      return { x0, x1, y0, y1 };
    };
    let lo = 3;
    let hi = 60;
    for (let i = 0; i < 26; i++) {
      dist = (lo + hi) / 2;
      placeCamera(BASE_AZ, BASE_EL);
      const b = bounds();
      if (b.x1 - b.x0 <= 1.94 && b.y1 - b.y0 <= 1.88) hi = dist;
      else lo = dist;
    }
    dist = hi;
    placeCamera(BASE_AZ, BASE_EL);
    const b = bounds();
    const contentCx = ((b.x0 + b.x1) / 2) * (focusW / 2) + viewW / 2;
    const dx = fl * viewW + focusW / 2 - contentCx;
    const bottomPx = (0.5 - b.y0 * 0.5) * viewH;
    const dy = viewH * 0.975 - bottomPx;
    camera.aspect = viewW / viewH;
    camera.setViewOffset(viewW, viewH, -dx, -dy, viewW, viewH);
    camera.updateProjectionMatrix();
    scene.fog = new Fog(PALETTE.ink, dist * 0.95, dist * 2.4);
  }


  /* ---------- loop ---------- */
  let running = false;
  let wantRun = false;
  let compiled = false;
  let disposed = false;
  let last = 0;
  let readySent = false;
  let lastEntry: ScreenPoint = { x: -1, y: -1 };
  const proj = new Vector3();
  let clock = 0;
  let entryMinX = -Infinity;

  function project(v: Vector3): ScreenPoint {
    proj.copy(v).project(camera);
    return { x: (proj.x * 0.5 + 0.5) * viewW, y: (-proj.y * 0.5 + 0.5) * viewH };
  }

  function render(now: number) {
    const dt = last ? Math.min(0.05, (now - last) / 1000) : 0.016;
    last = now;
    clock += dt;
    step(dt);
    pointer.x += (pointer.tx - pointer.x) * 0.05;
    pointer.y += (pointer.ty - pointer.y) * 0.05;
    placeCamera(BASE_AZ + pointer.x * 0.07, BASE_EL + pointer.y * 0.035);
    pulse.offset.x -= dt * 0.32;
    const breathe = 0.5 + Math.sin(clock * 2.2) * 0.5;
    ringMat.opacity = 0.35 + breathe * 0.4;
    receiverLight.intensity = 1 + breathe * 0.9;
    renderer.render(scene, camera);

    let entry = project(ENTRY);
    if (entryMinX > -Infinity) {
      for (const sample of traceSamples) {
        const s = project(sample);
        if (s.x >= entryMinX + 16 && s.y > 0 && s.y < viewH) {
          entry = s;
          break;
        }
      }
    }
    if (onEntry && (Math.abs(entry.x - lastEntry.x) > 0.5 || Math.abs(entry.y - lastEntry.y) > 0.5)) {
      lastEntry = entry;
      onEntry(entry);
    }
    if (label) {
      target.getWorldPosition(tmp);
      tmp.y += 0.38;
      const s = project(tmp);
      label.style.transform = `translate3d(${s.x.toFixed(1)}px, ${s.y.toFixed(1)}px, 0)`;
    }
    if (!readySent) {
      readySent = true;
      onReady?.();
    }
  }

  const loop = (now: number) => render(now);

  function setRunning(next: boolean) {
    wantRun = next;
    if (!compiled || disposed || next === running) return;
    running = next;
    last = 0;
    renderer.setAnimationLoop(next ? loop : null);
  }

  function resize(width: number, height: number) {
    viewW = Math.max(1, Math.round(width));
    viewH = Math.max(1, Math.round(height));
    const dpr = Math.min(window.devicePixelRatio || 1, compact ? 1.5 : 2);
    renderer.setPixelRatio(dpr);
    renderer.setSize(viewW, viewH, false);
    frame();
    lastEntry = { x: -1, y: -1 };
    if (!running && compiled) render(performance.now());
  }

  const lost = (event: Event) => {
    event.preventDefault();
    setRunning(false);
    onContextLost?.();
  };
  canvas.addEventListener("webglcontextlost", lost);

  apply(pose);
  if (initialTime > 0) step(initialTime);

  // Compile shaders off the main thread where KHR_parallel_shader_compile is available,
  // then draw the first frame (which fires onReady and fades the poster out).
  const finishCompile = () => {
    if (disposed) return;
    compiled = true;
    frame();
    if (wantRun) setRunning(true);
    else render(performance.now());
  };
  frame();
  renderer.compileAsync(scene, camera).then(finishCompile, finishCompile);

  return {
    resize,
    setRunning,
    setEntryMinX(x: number) {
      if (Math.abs(x - entryMinX) < 1 || (!Number.isFinite(x) && !Number.isFinite(entryMinX))) return;
      entryMinX = x;
      lastEntry = { x: -1, y: -1 };
      if (!running && compiled) render(performance.now());
    },
    setPointer(x: number, y: number) {
      pointer.tx = clamp(x, -1, 1);
      pointer.ty = clamp(y, -1, 1);
    },
    dispose() {
      setRunning(false);
      disposed = true;
      canvas.removeEventListener("webglcontextlost", lost);
      const geos = new Set<BufferGeometry>();
      const mats = new Set<Material>();
      scene.traverse((o) => {
        const m = o as Mesh;
        if (!m.isMesh) return;
        geos.add(m.geometry);
        (Array.isArray(m.material) ? m.material : [m.material]).forEach((x) => mats.add(x));
      });
      geos.forEach((g) => g.dispose());
      mats.forEach((m) => m.dispose());
      textures.forEach((t) => t.dispose());
      envTarget.dispose();
      pmrem.dispose();
      renderer.dispose();
    },
  };
}
