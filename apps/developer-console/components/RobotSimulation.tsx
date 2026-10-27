"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";

import type { MachineState, VisionObject } from "@/lib/types";

type Vec3 = { x: number; y: number; z: number };
type Point2 = { x: number; y: number; depth: number; scale: number };
type Camera = { yaw: number; pitch: number; distance: number };
type RenderObject = { depth: number; draw: (ctx: CanvasRenderingContext2D) => void };

export type SimulationFrame = {
  state: string;
  stage: string;
  progress: number;
  targetId: string;
  heldObjectId: string | null;
  robotXY?: number[];
};

type RobotSimulationProps = {
  frame: SimulationFrame;
  objects: VisionObject[];
  selectedObjectId: string;
  cameraPreset: "orbit" | "top" | "side";
  paused: boolean;
  onSelectObject: (objectId: string) => void;
  onCameraChange?: () => void;
};

const COLORS = {
  floor: "#14171b",
  floorLine: "rgba(171, 191, 185, .12)",
  tableTop: "#d7d2c8",
  tableSide: "#6f6a62",
  tableEdge: "#989187",
  arm: "#eef0ed",
  armSide: "#9ca6a3",
  joint: "#23312e",
  accent: "#d87855",
  safe: "#8fc5a8",
  warning: "#e3b45e",
  danger: "#dd6868",
};

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function mix(a: number, b: number, t: number): number {
  return a + (b - a) * clamp(t, 0, 1);
}

function mixVec(a: Vec3, b: Vec3, t: number): Vec3 {
  return { x: mix(a.x, b.x, t), y: mix(a.y, b.y, t), z: mix(a.z, b.z, t) };
}

function normalizedObjectPosition(object: VisionObject, index: number): [number, number] {
  const [rawX, rawY] = object.table_position_xy ?? [];
  if (Number.isFinite(rawX) && Number.isFinite(rawY)) {
    const divisor = Math.abs(rawX) > 1.2 || Math.abs(rawY) > 1.2 ? 640 : 1;
    return [clamp(rawX / divisor, 0, 1), clamp(rawY / divisor, 0, 1)];
  }
  return [[0.35, 0.57, 0.71][index % 3], [0.38, 0.66, 0.42][index % 3]];
}

function worldPosition(object: VisionObject, index: number): Vec3 {
  const [x, z] = normalizedObjectPosition(object, index);
  return { x: mix(-1.65, 1.55, x), y: 0.92, z: mix(-1.05, 1.05, z) };
}

function cameraFor(preset: RobotSimulationProps["cameraPreset"], orbit: Camera): Camera {
  if (preset === "top") return { yaw: -0.02, pitch: 1.29, distance: 8.6 };
  if (preset === "side") return { yaw: 1.48, pitch: 0.18, distance: 7.4 };
  return orbit;
}

function project(point: Vec3, camera: Camera, width: number, height: number): Point2 | null {
  const target = { x: 0, y: 0.9, z: 0 };
  const cp = Math.cos(camera.pitch);
  const position = {
    x: target.x + Math.sin(camera.yaw) * cp * camera.distance,
    y: target.y + Math.sin(camera.pitch) * camera.distance,
    z: target.z + Math.cos(camera.yaw) * cp * camera.distance,
  };
  const forwardRaw = { x: target.x - position.x, y: target.y - position.y, z: target.z - position.z };
  const forwardLength = Math.hypot(forwardRaw.x, forwardRaw.y, forwardRaw.z) || 1;
  const forward = {
    x: forwardRaw.x / forwardLength,
    y: forwardRaw.y / forwardLength,
    z: forwardRaw.z / forwardLength,
  };
  const rightRaw = { x: forward.z, y: 0, z: -forward.x };
  const rightLength = Math.hypot(rightRaw.x, rightRaw.z) || 1;
  const right = { x: rightRaw.x / rightLength, y: 0, z: rightRaw.z / rightLength };
  const up = {
    x: right.z * forward.y,
    y: right.x * forward.z - right.z * forward.x,
    z: -right.x * forward.y,
  };
  const relative = { x: point.x - position.x, y: point.y - position.y, z: point.z - position.z };
  const depth = relative.x * forward.x + relative.y * forward.y + relative.z * forward.z;
  if (depth < 0.1) return null;
  const screenScale = Math.min(width, height) * 1.03 / depth;
  return {
    x: width / 2 + (relative.x * right.x + relative.y * right.y + relative.z * right.z) * screenScale,
    y: height / 2 - (relative.x * up.x + relative.y * up.y + relative.z * up.z) * screenScale,
    depth,
    scale: screenScale,
  };
}

function face(
  points: Vec3[],
  fill: string,
  camera: Camera,
  width: number,
  height: number,
  stroke = "rgba(255,255,255,.11)",
): RenderObject | null {
  const projected = points.map((point) => project(point, camera, width, height));
  if (projected.some((point) => point == null)) return null;
  const safe = projected as Point2[];
  return {
    depth: safe.reduce((sum, point) => sum + point.depth, 0) / safe.length,
    draw(ctx) {
      ctx.beginPath();
      safe.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 1;
      ctx.stroke();
    },
  };
}

function box(
  center: Vec3,
  size: Vec3,
  colors: [string, string, string],
  camera: Camera,
  width: number,
  height: number,
): RenderObject[] {
  const x0 = center.x - size.x / 2;
  const x1 = center.x + size.x / 2;
  const y0 = center.y - size.y / 2;
  const y1 = center.y + size.y / 2;
  const z0 = center.z - size.z / 2;
  const z1 = center.z + size.z / 2;
  const vertices = [
    { x: x0, y: y0, z: z0 }, { x: x1, y: y0, z: z0 },
    { x: x1, y: y1, z: z0 }, { x: x0, y: y1, z: z0 },
    { x: x0, y: y0, z: z1 }, { x: x1, y: y0, z: z1 },
    { x: x1, y: y1, z: z1 }, { x: x0, y: y1, z: z1 },
  ];
  const definitions: [number[], string][] = [
    [[3, 2, 6, 7], colors[0]], [[0, 1, 2, 3], colors[1]], [[1, 5, 6, 2], colors[1]],
    [[5, 4, 7, 6], colors[2]], [[4, 0, 3, 7], colors[2]], [[4, 5, 1, 0], colors[2]],
  ];
  return definitions
    .map(([indices, color]) => face(indices.map((index) => vertices[index]), color, camera, width, height))
    .filter((item): item is RenderObject => item != null);
}

function line3d(
  start: Vec3,
  end: Vec3,
  color: string,
  widthWorld: number,
  camera: Camera,
  width: number,
  height: number,
): RenderObject | null {
  const a = project(start, camera, width, height);
  const b = project(end, camera, width, height);
  if (!a || !b) return null;
  return {
    depth: (a.depth + b.depth) / 2,
    draw(ctx) {
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = color;
      ctx.lineWidth = Math.max(2, ((a.scale + b.scale) / 2) * widthWorld);
      ctx.lineCap = "round";
      ctx.stroke();
    },
  };
}

function disc3d(
  center: Vec3,
  radius: number,
  color: string,
  camera: Camera,
  width: number,
  height: number,
  glow = false,
): RenderObject | null {
  const point = project(center, camera, width, height);
  if (!point) return null;
  return {
    depth: point.depth - 0.02,
    draw(ctx) {
      ctx.save();
      if (glow) {
        ctx.shadowColor = color;
        ctx.shadowBlur = 18;
      }
      ctx.beginPath();
      ctx.arc(point.x, point.y, Math.max(2, point.scale * radius), 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.restore();
    },
  };
}

function roundedLabel(
  ctx: CanvasRenderingContext2D,
  point: Point2,
  title: string,
  active: boolean,
): void {
  ctx.save();
  ctx.font = "600 10px Inter, system-ui, sans-serif";
  const labelWidth = ctx.measureText(title).width + 18;
  const x = point.x - labelWidth / 2;
  const y = point.y - 35;
  ctx.fillStyle = active ? "rgba(225, 120, 82, .94)" : "rgba(17, 21, 24, .8)";
  ctx.beginPath();
  ctx.roundRect(x, y, labelWidth, 23, 11);
  ctx.fill();
  ctx.fillStyle = "#fff";
  ctx.textAlign = "center";
  ctx.fillText(title, point.x, y + 15);
  ctx.restore();
}

/* ───────────── SO-101-style arm: kinematics and detailed parts ───────────── */

const vAdd = (a: Vec3, b: Vec3): Vec3 => ({ x: a.x + b.x, y: a.y + b.y, z: a.z + b.z });
const vSub = (a: Vec3, b: Vec3): Vec3 => ({ x: a.x - b.x, y: a.y - b.y, z: a.z - b.z });
const vScale = (a: Vec3, k: number): Vec3 => ({ x: a.x * k, y: a.y * k, z: a.z * k });
const vDot = (a: Vec3, b: Vec3): number => a.x * b.x + a.y * b.y + a.z * b.z;
const vCross = (a: Vec3, b: Vec3): Vec3 => ({ x: a.y * b.z - a.z * b.y, y: a.z * b.x - a.x * b.z, z: a.x * b.y - a.y * b.x });
const vNorm = (a: Vec3): Vec3 => vScale(a, 1 / (Math.hypot(a.x, a.y, a.z) || 1));
const vMid = (a: Vec3, b: Vec3): Vec3 => vScale(vAdd(a, b), 0.5);
const UP: Vec3 = { x: 0, y: 1, z: 0 };
const LIGHT = vNorm({ x: -0.35, y: 0.9, z: 0.3 });

const ARM_BASE: Vec3 = { x: -0.2, y: 0.73, z: -1.1 };
const SHOULDER_HEIGHT = 0.62;
const UPPER_ARM = 1.55;
const FOREARM = 1.6;
const WRIST_ROLL_LEN = 0.22;
const JAW_LEN = 0.4;
const PLATE_SIDE = 0.27;

const ARM_COLORS = {
  plate: "#e8e3d6",
  servo: "#1c1f24",
  metal: "#3b4046",
  baseplate: "#2a2e33",
  accent: "#d87855",
  cable: "#121417",
};

export type ArmPose = {
  shoulder: Vec3;
  elbow: Vec3;
  wrist: Vec3;
  tip: Vec3;
  u: Vec3;
  s: Vec3;
  g: Vec3;
  aperture: number;
  reachable: boolean;
  /** Joint angles in degrees (gripper in percent open), named like the SO-101 joints. */
  joints: Record<string, number>;
};

type Trajectory = {
  effector: Vec3;
  handoff: Vec3;
  moving: boolean;
  carrying: boolean;
  p: number;
  state: string;
  stage: string;
  aperture: number;
  pitch: number;
  selectedPosition: Vec3;
  objectPositions: Vec3[];
};

function hexToRgb(hex: string): [number, number, number] {
  const value = hex.replace("#", "");
  return [parseInt(value.slice(0, 2), 16), parseInt(value.slice(2, 4), 16), parseInt(value.slice(4, 6), 16)];
}

function shadeHex(hex: string, k: number): string {
  const [r, g, b] = hexToRgb(hex);
  const f = (channel: number) => Math.round(clamp(channel * k, 0, 255));
  return `rgb(${f(r)},${f(g)},${f(b)})`;
}

function cameraPosition(camera: Camera): Vec3 {
  const cp = Math.cos(camera.pitch);
  return {
    x: Math.sin(camera.yaw) * cp * camera.distance,
    y: 0.9 + Math.sin(camera.pitch) * camera.distance,
    z: Math.cos(camera.yaw) * cp * camera.distance,
  };
}

function shadedFace(points: Vec3[], normal: Vec3, color: string, camera: Camera, width: number, height: number): RenderObject | null {
  const center = vScale(points.reduce((sum, point) => vAdd(sum, point), { x: 0, y: 0, z: 0 }), 1 / points.length);
  if (vDot(normal, vSub(cameraPosition(camera), center)) <= 0) return null;
  const brightness = 0.56 + 0.52 * Math.max(0, vDot(normal, LIGHT));
  return face(points, shadeHex(color, brightness), camera, width, height, "rgba(0,0,0,.3)");
}

function orientedBox(
  center: Vec3, ax: Vec3, ay: Vec3, az: Vec3, half: [number, number, number],
  color: string, camera: Camera, width: number, height: number,
): RenderObject[] {
  const corner = (sx: number, sy: number, sz: number): Vec3 =>
    vAdd(center, vAdd(vScale(ax, sx * half[0]), vAdd(vScale(ay, sy * half[1]), vScale(az, sz * half[2]))));
  const faces: [Vec3[], Vec3][] = [
    [[corner(1, -1, -1), corner(1, 1, -1), corner(1, 1, 1), corner(1, -1, 1)], ax],
    [[corner(-1, -1, 1), corner(-1, 1, 1), corner(-1, 1, -1), corner(-1, -1, -1)], vScale(ax, -1)],
    [[corner(-1, 1, -1), corner(-1, 1, 1), corner(1, 1, 1), corner(1, 1, -1)], ay],
    [[corner(-1, -1, 1), corner(-1, -1, -1), corner(1, -1, -1), corner(1, -1, 1)], vScale(ay, -1)],
    [[corner(-1, -1, 1), corner(1, -1, 1), corner(1, 1, 1), corner(-1, 1, 1)], az],
    [[corner(1, -1, -1), corner(-1, -1, -1), corner(-1, 1, -1), corner(1, 1, -1)], vScale(az, -1)],
  ];
  return faces
    .map(([points, normal]) => shadedFace(points, normal, color, camera, width, height))
    .filter((item): item is RenderObject => item != null);
}

function cylinder(
  center: Vec3, axis: Vec3, radius: number, halfLength: number, color: string,
  camera: Camera, width: number, height: number, sides = 18,
): RenderObject[] {
  const helper = Math.abs(axis.y) < 0.9 ? UP : { x: 1, y: 0, z: 0 };
  const p = vNorm(vCross(axis, helper));
  const q = vCross(axis, p);
  const ring = (angle: number, offset: number): Vec3 =>
    vAdd(center, vAdd(vScale(axis, offset), vAdd(vScale(p, Math.cos(angle) * radius), vScale(q, Math.sin(angle) * radius))));
  const out: RenderObject[] = [];
  for (let index = 0; index < sides; index += 1) {
    const a0 = (index / sides) * Math.PI * 2;
    const a1 = ((index + 1) / sides) * Math.PI * 2;
    const mid = (a0 + a1) / 2;
    const normal = vAdd(vScale(p, Math.cos(mid)), vScale(q, Math.sin(mid)));
    const side = shadedFace([ring(a0, -halfLength), ring(a1, -halfLength), ring(a1, halfLength), ring(a0, halfLength)], normal, color, camera, width, height);
    if (side) out.push(side);
  }
  const capPoints = (offset: number) => Array.from({ length: sides }, (_, index) => ring((index / sides) * Math.PI * 2, offset));
  const top = shadedFace(capPoints(halfLength), axis, color, camera, width, height);
  const bottom = shadedFace(capPoints(-halfLength), vScale(axis, -1), color, camera, width, height);
  if (top) out.push(top);
  if (bottom) out.push(bottom);
  return out;
}

/** Two-link planar IK in the vertical plane that contains the shoulder and the target. */
function solveArm(target: Vec3, pitchDeg: number, aperture: number): ArmPose {
  const dx = target.x - ARM_BASE.x;
  const dz = target.z - ARM_BASE.z;
  const pan = Math.atan2(dx, dz);
  const u: Vec3 = { x: Math.sin(pan), y: 0, z: Math.cos(pan) };
  const s: Vec3 = { x: Math.cos(pan), y: 0, z: -Math.sin(pan) };
  const phi = (pitchDeg * Math.PI) / 180;
  const gripLocal = { r: Math.cos(phi), y: -Math.sin(phi) };
  const gripLength = WRIST_ROLL_LEN + JAW_LEN;
  const shoulder: Vec3 = { x: ARM_BASE.x, y: ARM_BASE.y + SHOULDER_HEIGHT, z: ARM_BASE.z };

  let wristR = Math.hypot(dx, dz) - gripLocal.r * gripLength;
  let wristY = target.y - gripLocal.y * gripLength - shoulder.y;
  let distance = Math.hypot(wristR, wristY);
  const maxDistance = UPPER_ARM + FOREARM - 0.002;
  const minDistance = Math.abs(UPPER_ARM - FOREARM) + 0.15;
  const reachable = distance <= maxDistance && distance >= minDistance;
  if (distance > maxDistance) { wristR *= maxDistance / distance; wristY *= maxDistance / distance; distance = maxDistance; }
  if (distance < minDistance) {
    const k = minDistance / Math.max(distance, 1e-3);
    wristR *= k; wristY *= k; distance = minDistance;
  }
  const toTarget = Math.atan2(wristY, wristR);
  const cosInterior = clamp((UPPER_ARM * UPPER_ARM + distance * distance - FOREARM * FOREARM) / (2 * UPPER_ARM * distance), -1, 1);
  const shoulderAngle = toTarget + Math.acos(cosInterior);
  const elbowR = Math.cos(shoulderAngle) * UPPER_ARM;
  const elbowY = Math.sin(shoulderAngle) * UPPER_ARM;
  const place = (r: number, y: number): Vec3 => ({ x: ARM_BASE.x + u.x * r, y: shoulder.y + y, z: ARM_BASE.z + u.z * r });
  const elbow = place(elbowR, elbowY);
  const wrist = place(wristR, wristY);
  const g: Vec3 = { x: u.x * gripLocal.r, y: gripLocal.y, z: u.z * gripLocal.r };
  const tip = vAdd(wrist, vScale(g, gripLength));
  const forearmAngle = Math.atan2(wristY - elbowY, wristR - elbowR);
  const deg = (radians: number) => (radians * 180) / Math.PI;
  return {
    shoulder, elbow, wrist, tip, u, s, g, aperture, reachable,
    joints: {
      shoulder_pan: deg(pan),
      shoulder_lift: deg(shoulderAngle),
      elbow_flex: deg(shoulderAngle - forearmAngle),
      wrist_flex: deg(-phi - forearmAngle),
      wrist_roll: 0,
      gripper: aperture,
    },
  };
}

function trajectoryFor(frame: SimulationFrame, objects: VisionObject[], selectedObjectId: string): Trajectory {
  const objectPositions = objects.map(worldPosition);
  const selectedIndex = Math.max(0, objects.findIndex((object) => object.object_id === selectedObjectId));
  const selectedPosition = objectPositions[selectedIndex] ?? { x: 0.2, y: 0.92, z: 0 };
  const state = frame.state.toUpperCase();
  const stage = frame.stage.toUpperCase();
  const moving = state === "EXECUTING" || state === "HOLDING";
  const p = clamp(frame.progress, 0, 1);
  const ready = { x: -0.2, y: 1.62, z: 0.95 };
  const grasp = { x: selectedPosition.x, y: 1.12, z: selectedPosition.z };
  const handoff = { x: 1.93, y: 1.72, z: -0.72 };
  let effector = ready;
  if (moving || state === "COMPLETED") {
    if (p < 0.38) effector = mixVec(ready, grasp, p / 0.38);
    else if (p < 0.51) effector = { ...grasp, y: grasp.y + Math.sin(((p - 0.38) / 0.13) * Math.PI) * 0.06 };
    else if (p < 0.9) effector = mixVec(grasp, handoff, (p - 0.51) / 0.39);
    else effector = handoff;
  }
  if (state === "ESTOPPED" || state === "FAULT") {
    effector = p > 0 ? (p < 0.51 ? grasp : mixVec(grasp, handoff, clamp((p - 0.51) / 0.39, 0, 1))) : ready;
  }
  const carrying = frame.heldObjectId != null || (moving && p >= 0.45 && p < 0.96);
  let aperture = 42;
  let pitch = 72;
  if (moving || state === "COMPLETED") {
    if (p < 0.38) { aperture = 78; pitch = mix(72, 88, p / 0.38); }
    else if (p < 0.51) { aperture = mix(78, 24, (p - 0.4) / 0.11); pitch = 88; }
    else if (p < 0.9) { aperture = 24; pitch = mix(88, 48, (p - 0.51) / 0.39); }
    else { aperture = mix(24, 78, (p - 0.9) / 0.1); pitch = 48; }
  }
  return { effector, handoff, moving, carrying, p, state, stage, aperture, pitch, selectedPosition, objectPositions };
}

/** Simulated arm pose for a machine frame; also drives the joint readout on the Robot page. */
export function simulatedArmPose(frame: SimulationFrame, objects: VisionObject[], selectedObjectId: string): ArmPose {
  const path = trajectoryFor(frame, objects, selectedObjectId);
  return solveArm(path.effector, path.pitch, path.aperture);
}

function armParts(pose: ArmPose, toolColor: string, camera: Camera, width: number, height: number): { parts: RenderObject[]; shadows: RenderObject[] } {
  const parts: RenderObject[] = [];
  const shadows: RenderObject[] = [];
  const world = { x: { x: 1, y: 0, z: 0 }, z: { x: 0, y: 0, z: 1 } };
  const { shoulder, elbow, wrist, tip, u, s, g } = pose;
  const box = (center: Vec3, ax: Vec3, ay: Vec3, az: Vec3, half: [number, number, number], color: string) =>
    parts.push(...orientedBox(center, ax, ay, az, half, color, camera, width, height));
  const ring = (center: Vec3, axis: Vec3, radius: number, thickness: number, color: string) =>
    parts.push(...cylinder(center, axis, radius, thickness, color, camera, width, height));
  const plateLink = (a: Vec3, b: Vec3, halfHeight: number) => {
    const direction = vNorm(vSub(b, a));
    const perpendicular = vNorm(vCross(s, direction));
    const half: [number, number, number] = [vNorm(vSub(b, a)) && Math.hypot(b.x - a.x, b.y - a.y, b.z - a.z) / 2 + 0.06, halfHeight, 0.035];
    ([1, -1] as const).forEach((side) => box(vAdd(vMid(a, b), vScale(s, side * PLATE_SIDE)), direction, perpendicular, s, half, ARM_COLORS.plate));
    box(vAdd(vMid(a, b), vScale(direction, 0.25)), direction, perpendicular, s, [0.04, halfHeight - 0.02, PLATE_SIDE], ARM_COLORS.metal);
    box(vSub(vMid(a, b), vScale(direction, 0.25)), direction, perpendicular, s, [0.04, halfHeight - 0.02, PLATE_SIDE], ARM_COLORS.metal);
  };

  // Table-clamped base and pan servo.
  box(vAdd(ARM_BASE, { x: 0, y: 0.05, z: 0 }), world.x, UP, world.z, [0.55, 0.05, 0.45], ARM_COLORS.baseplate);
  ([-1, 1] as const).forEach((side) => box(vAdd(ARM_BASE, { x: side * 0.36, y: 0.12, z: 0 }), world.x, UP, world.z, [0.07, 0.07, 0.3], ARM_COLORS.metal));
  box(vAdd(ARM_BASE, { x: 0, y: 0.3, z: 0 }), u, UP, s, [0.26, 0.18, 0.22], ARM_COLORS.servo);
  ring(vAdd(ARM_BASE, { x: 0, y: 0.49, z: 0 }), UP, 0.31, 0.04, ARM_COLORS.accent);
  box(vAdd(ARM_BASE, { x: 0, y: 0.56, z: 0 }), u, UP, s, [0.3, 0.05, 0.3], ARM_COLORS.plate);

  // Shoulder bracket and servo.
  ([1, -1] as const).forEach((side) => box(vAdd(vSub(shoulder, { x: 0, y: 0.05, z: 0 }), vScale(s, side * PLATE_SIDE)), u, UP, s, [0.2, 0.28, 0.035], ARM_COLORS.plate));
  box(shoulder, u, UP, s, [0.24, 0.22, 0.17], ARM_COLORS.servo);
  ring(vAdd(shoulder, vScale(s, PLATE_SIDE + 0.07)), s, 0.15, 0.03, ARM_COLORS.accent);

  // Upper arm, elbow servo, forearm.
  plateLink(shoulder, elbow, 0.17);
  const upperDir = vNorm(vSub(elbow, shoulder));
  const upperPerp = vNorm(vCross(s, upperDir));
  box(elbow, upperDir, upperPerp, s, [0.22, 0.2, 0.17], ARM_COLORS.servo);
  ring(vAdd(elbow, vScale(s, PLATE_SIDE + 0.07)), s, 0.14, 0.03, ARM_COLORS.accent);
  plateLink(elbow, wrist, 0.15);

  // Wrist flex servo, roll joint, gripper.
  const foreDir = vNorm(vSub(wrist, elbow));
  const forePerp = vNorm(vCross(s, foreDir));
  box(wrist, foreDir, forePerp, s, [0.17, 0.15, 0.15], ARM_COLORS.servo);
  ring(vAdd(wrist, vScale(s, 0.2)), s, 0.1, 0.025, ARM_COLORS.accent);
  const gripPerp = vNorm(vCross(s, g));
  ring(vAdd(wrist, vScale(g, 0.13)), g, 0.12, 0.1, ARM_COLORS.plate);
  const gripBase = vAdd(wrist, vScale(g, WRIST_ROLL_LEN));
  box(vAdd(gripBase, vScale(g, 0.1)), g, gripPerp, s, [0.12, 0.13, 0.17], ARM_COLORS.servo);
  const jawOffset = 0.12;
  const fixedStart = vAdd(gripBase, vScale(s, jawOffset));
  box(vAdd(fixedStart, vScale(g, JAW_LEN / 2)), g, gripPerp, s, [JAW_LEN / 2, 0.07, 0.025], ARM_COLORS.plate);
  box(vAdd(fixedStart, vScale(g, JAW_LEN - 0.03)), g, gripPerp, s, [0.05, 0.075, 0.035], toolColor);
  const angle = (pose.aperture / 100) * 0.55;
  const jawDir = vNorm(vAdd(vScale(g, Math.cos(angle)), vScale(s, -Math.sin(angle))));
  const jawSide = vNorm(vCross(jawDir, gripPerp));
  const movingStart = vSub(gripBase, vScale(s, jawOffset));
  box(vAdd(movingStart, vScale(jawDir, JAW_LEN / 2)), jawDir, gripPerp, jawSide, [JAW_LEN / 2, 0.07, 0.025], ARM_COLORS.plate);
  box(vAdd(movingStart, vScale(jawDir, JAW_LEN - 0.03)), jawDir, gripPerp, jawSide, [0.05, 0.075, 0.035], toolColor);

  // Servo cable running along the links.
  const cable = [
    vAdd(ARM_BASE, vAdd(vScale(s, 0.38), { x: 0, y: 0.2, z: 0 })),
    vAdd(shoulder, vAdd(vScale(s, PLATE_SIDE + 0.1), { x: 0, y: -0.2, z: 0 })),
    vAdd(vMid(shoulder, elbow), vAdd(vScale(s, PLATE_SIDE + 0.08), vScale(upperPerp, 0.12))),
    vAdd(elbow, vAdd(vScale(s, PLATE_SIDE + 0.1), vScale(upperPerp, 0.1))),
    vAdd(vMid(elbow, wrist), vAdd(vScale(s, PLATE_SIDE + 0.08), vScale(forePerp, 0.1))),
    vAdd(wrist, vScale(s, 0.22)),
  ];
  for (let index = 0; index < cable.length - 1; index += 1) {
    const segment = line3d(cable[index], cable[index + 1], ARM_COLORS.cable, 0.035, camera, width, height);
    if (segment) parts.push(segment);
  }

  // Soft contact shadows on the table.
  const onTable = (point: Vec3): Vec3 => ({ x: point.x + (point.y - 0.74) * 0.34, y: 0.745, z: point.z + (point.y - 0.74) * 0.22 });
  const shadowColor = "rgba(0,0,0,.16)";
  const chain: [Vec3, Vec3, number][] = [[shoulder, elbow, 0.14], [elbow, wrist, 0.12], [wrist, tip, 0.1]];
  chain.forEach(([a, b, widthWorld]) => {
    const segment = line3d(onTable(a), onTable(b), shadowColor, widthWorld, camera, width, height);
    if (segment) shadows.push(segment);
  });
  const baseShadow = disc3d(vAdd(onTable(vAdd(ARM_BASE, { x: 0, y: 0.3, z: 0 })), { x: 0.06, y: 0, z: 0.04 }), 0.5, shadowColor, camera, width, height, true);
  if (baseShadow) shadows.push(baseShadow);
  return { parts, shadows };
}

function drawScene(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  camera: Camera,
  frame: SimulationFrame,
  objects: VisionObject[],
  selectedObjectId: string,
  time: number,
): void {
  ctx.clearRect(0, 0, width, height);
  const gradient = ctx.createRadialGradient(width * 0.52, height * 0.3, 10, width * 0.52, height * 0.5, width * 0.8);
  gradient.addColorStop(0, "#29312f");
  gradient.addColorStop(0.58, "#171b1d");
  gradient.addColorStop(1, "#0e1114");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  const renderObjects: RenderObject[] = [];
  const floorY = 0;
  for (let index = -6; index <= 6; index += 1) {
    const xLine = line3d({ x: index, y: floorY, z: -5 }, { x: index, y: floorY, z: 5 }, COLORS.floorLine, 0.007, camera, width, height);
    const zLine = line3d({ x: -6, y: floorY, z: index }, { x: 6, y: floorY, z: index }, COLORS.floorLine, 0.007, camera, width, height);
    if (xLine) renderObjects.push(xLine);
    if (zLine) renderObjects.push(zLine);
  }

  renderObjects.push(...box({ x: 0, y: 0.64, z: 0 }, { x: 4.9, y: 0.18, z: 3.25 }, [COLORS.tableTop, COLORS.tableEdge, COLORS.tableSide], camera, width, height));
  [[-2.1, -1.28], [2.1, -1.28], [-2.1, 1.28], [2.1, 1.28]].forEach(([x, z]) => {
    renderObjects.push(...box({ x, y: 0.31, z }, { x: 0.18, y: 0.62, z: 0.18 }, ["#77736c", "#4a4844", "#353532"], camera, width, height));
  });

  const boundary = [
    { x: -2.25, y: 0.75, z: -1.38 }, { x: 2.25, y: 0.75, z: -1.38 },
    { x: 2.25, y: 0.75, z: 1.38 }, { x: -2.25, y: 0.75, z: 1.38 },
  ];
  for (let index = 0; index < boundary.length; index += 1) {
    const segment = line3d(boundary[index], boundary[(index + 1) % boundary.length], "rgba(143,197,168,.6)", 0.012, camera, width, height);
    if (segment) renderObjects.push(segment);
  }

  const groundCount = renderObjects.length;
  const path = trajectoryFor(frame, objects, selectedObjectId);
  const { effector, handoff, moving, carrying, state, stage, objectPositions } = path;
  const faulted = state === "FAULT" || state === "ESTOPPED";
  const toolColor = faulted ? COLORS.danger : moving ? COLORS.accent : "#5f706b";
  const pose = solveArm(effector, path.pitch, path.aperture);
  const arm = armParts(pose, toolColor, camera, width, height);
  renderObjects.push(...arm.parts);
  const shadows: RenderObject[] = [...arm.shadows];

  objects.forEach((object, index) => {
    const selected = object.object_id === selectedObjectId;
    if (carrying && selected) return;
    const position = objectPositions[index];
    const palette: [string, string, string] = index % 3 === 0
      ? ["#e18a65", "#b9563d", "#71382e"]
      : index % 3 === 1
        ? ["#8bb8a0", "#557f6b", "#334f43"]
        : ["#e0bc65", "#a98537", "#675526"];
    renderObjects.push(...box(position, { x: 0.34, y: 0.34, z: 0.34 }, palette, camera, width, height));
    const shade = disc3d({ x: position.x + 0.07, y: 0.745, z: position.z + 0.05 }, 0.2, "rgba(0,0,0,.28)", camera, width, height, true);
    if (shade) shadows.push(shade);
    if (selected) {
      const pulse = 0.24 + Math.sin(time / 320) * 0.025;
      const marker = disc3d({ ...position, y: 0.765 }, pulse, "rgba(225,120,82,.32)", camera, width, height, true);
      if (marker) renderObjects.push(marker);
    }
  });
  if (carrying) {
    const carried = vAdd(pose.tip, vScale(pose.g, -0.1));
    renderObjects.push(...box({ ...carried, y: carried.y - 0.06 }, { x: 0.3, y: 0.3, z: 0.3 }, ["#e18a65", "#b9563d", "#71382e"], camera, width, height));
  }

  const handoffMarker = disc3d({ x: handoff.x, y: 0.77, z: handoff.z }, 0.35, "rgba(143,197,168,.22)", camera, width, height, stage.includes("HANDOFF"));
  if (handoffMarker) shadows.push(handoffMarker);
  const byDepth = (a: RenderObject, b: RenderObject) => b.depth - a.depth;
  renderObjects.slice(0, groundCount).sort(byDepth).forEach((item) => item.draw(ctx));
  shadows.sort(byDepth).forEach((item) => item.draw(ctx));
  renderObjects.slice(groundCount).sort(byDepth).forEach((item) => item.draw(ctx));

  const placedLabels: { x: number; y: number }[] = [];
  objects.forEach((object, index) => {
    const position = carrying && object.object_id === selectedObjectId
      ? { ...pose.tip, y: pose.tip.y - 0.1 }
      : objectPositions[index];
    const point = project({ ...position, y: position.y + 0.32 }, camera, width, height);
    if (!point) return;
    let lift = 0;
    while (placedLabels.some((other) => Math.abs(other.x - point.x) < 96 && Math.abs(other.y - (point.y - lift)) < 25) && lift < 120) lift += 26;
    const shifted = { ...point, y: point.y - lift };
    placedLabels.push({ x: shifted.x, y: shifted.y });
    roundedLabel(ctx, shifted, object.class_name.replaceAll("_", " "), object.object_id === selectedObjectId);
  });

  const handoffPoint = project({ ...handoff, y: 0.8 }, camera, width, height);
  if (handoffPoint) {
    ctx.save();
    ctx.fillStyle = "rgba(216, 232, 225, .72)";
    ctx.font = "600 9px Inter, system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("HANDOFF ZONE", handoffPoint.x, handoffPoint.y + 22);
    ctx.restore();
  }
}

export function RobotSimulation({
  frame,
  objects,
  selectedObjectId,
  cameraPreset,
  paused,
  onSelectObject,
  onCameraChange,
}: RobotSimulationProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const orbitRef = useRef<Camera>({ yaw: -0.72, pitch: 0.47, distance: 7.1 });
  const dragRef = useRef<{ pointerId: number; x: number; y: number; moved: number } | null>(null);
  const frameRef = useRef(frame);
  const objectsRef = useRef(objects);
  const selectionRef = useRef(selectedObjectId);
  const presetRef = useRef(cameraPreset);
  const pausedRef = useRef(paused);
  const [interactiveCamera, setInteractiveCamera] = useState(false);

  useEffect(() => { frameRef.current = frame; }, [frame]);
  useEffect(() => { objectsRef.current = objects; }, [objects]);
  useEffect(() => { selectionRef.current = selectedObjectId; }, [selectedObjectId]);
  useEffect(() => { presetRef.current = cameraPreset; }, [cameraPreset]);
  useEffect(() => { pausedRef.current = paused; }, [paused]);
  useEffect(() => { setInteractiveCamera(false); }, [cameraPreset]);

  const renderOnce = useCallback((time: number) => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const rect = wrap.getBoundingClientRect();
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    const pixelWidth = Math.max(1, Math.round(rect.width * ratio));
    const pixelHeight = Math.max(1, Math.round(rect.height * ratio));
    if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
      canvas.width = pixelWidth;
      canvas.height = pixelHeight;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    const preset = interactiveCamera ? "orbit" : presetRef.current;
    drawScene(ctx, rect.width, rect.height, cameraFor(preset, orbitRef.current), frameRef.current, objectsRef.current, selectionRef.current, time);
  }, [interactiveCamera]);

  useEffect(() => {
    let animation = 0;
    const loop = (time: number) => {
      renderOnce(time);
      animation = window.requestAnimationFrame(loop);
    };
    animation = window.requestAnimationFrame(loop);
    return () => window.cancelAnimationFrame(animation);
  }, [renderOnce]);

  const pointerDown = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, moved: 0 };
  };

  const pointerMove = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const deltaX = event.clientX - drag.x;
    const deltaY = event.clientY - drag.y;
    orbitRef.current.yaw -= deltaX * 0.008;
    orbitRef.current.pitch = clamp(orbitRef.current.pitch + deltaY * 0.006, 0.08, 1.38);
    dragRef.current = { ...drag, x: event.clientX, y: event.clientY, moved: drag.moved + Math.hypot(deltaX, deltaY) };
    setInteractiveCamera(true);
    onCameraChange?.();
  };

  const pointerUp = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null;
  };

  const wheel = (event: ReactWheelEvent<HTMLCanvasElement>) => {
    orbitRef.current.distance = clamp(orbitRef.current.distance + event.deltaY * 0.006, 4.8, 10.5);
    setInteractiveCamera(true);
    onCameraChange?.();
  };

  const selectNearest = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if ((dragRef.current?.moved ?? 0) > 5) return;
    const canvas = canvasRef.current;
    const rect = canvas?.getBoundingClientRect();
    if (!rect) return;
    const camera = cameraFor(interactiveCamera ? "orbit" : cameraPreset, orbitRef.current);
    let nearestId: string | null = null;
    let nearestDistance = Number.POSITIVE_INFINITY;
    for (const [index, object] of objects.entries()) {
      const point = project(worldPosition(object, index), camera, rect.width, rect.height);
      if (!point) continue;
      const distance = Math.hypot(point.x - (event.clientX - rect.left), point.y - (event.clientY - rect.top));
      if (distance < 48 && distance < nearestDistance) {
        nearestId = object.object_id;
        nearestDistance = distance;
      }
    }
    if (nearestId) onSelectObject(nearestId);
  };

  return (
    <div ref={wrapRef} className="robot-canvas-wrap">
      <canvas
        ref={canvasRef}
        className="robot-canvas"
        role="img"
        aria-label={`Interactive 3D robot workcell. ${frame.state}, ${frame.stage}, ${Math.round(frame.progress * 100)} percent complete.`}
        onPointerDown={pointerDown}
        onPointerMove={pointerMove}
        onPointerUp={(event) => { selectNearest(event); pointerUp(event); }}
        onPointerCancel={pointerUp}
        onWheel={wheel}
      />
      <div className="robot-canvas-hint">Drag to orbit · scroll to zoom</div>
      <div className={`robot-pause-indicator ${paused ? "show" : ""}`} aria-hidden={!paused}>
        <span>Ⅱ</span> Simulation paused
      </div>
    </div>
  );
}
