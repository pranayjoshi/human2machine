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

  const objectPositions = objects.map(worldPosition);
  const selectedIndex = Math.max(0, objects.findIndex((object) => object.object_id === selectedObjectId));
  const selectedPosition = objectPositions[selectedIndex] ?? { x: 0.2, y: 0.92, z: 0 };
  const state = frame.state.toUpperCase();
  const stage = frame.stage.toUpperCase();
  const moving = state === "EXECUTING" || state === "HOLDING";
  const p = clamp(frame.progress, 0, 1);
  const base = { x: -1.92, y: 1.03, z: 0.92 };
  const ready = { x: -0.78, y: 1.84, z: 0.58 };
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
  const robotXY = frame.robotXY;
  if (robotXY?.length === 2 && robotXY.every(Number.isFinite)) {
    const normalized = { x: mix(-1.65, 1.55, robotXY[0]), y: effector.y, z: mix(-1.05, 1.05, robotXY[1]) };
    effector = normalized;
  }

  const wrist = mixVec(base, effector, 0.72);
  wrist.y += 0.32;
  wrist.z += 0.05;
  const elbow = mixVec(base, wrist, 0.47);
  elbow.y += 0.7 + Math.min(0.25, Math.abs(effector.x - base.x) * 0.05);
  elbow.z += 0.22;

  renderObjects.push(...box({ x: -1.92, y: 0.91, z: 0.92 }, { x: 0.72, y: 0.34, z: 0.72 }, ["#d9ddda", "#8d9794", "#5e6966"], camera, width, height));
  const links: [Vec3, Vec3][] = [[base, elbow], [elbow, wrist], [wrist, effector]];
  links.forEach(([a, b], index) => {
    const shadow = line3d(a, b, "#65716e", index === 2 ? 0.15 : 0.2, camera, width, height);
    const highlight = line3d(a, b, COLORS.arm, index === 2 ? 0.105 : 0.145, camera, width, height);
    if (shadow) renderObjects.push(shadow);
    if (highlight) renderObjects.push(highlight);
  });
  [base, elbow, wrist].forEach((joint, index) => {
    const disc = disc3d(joint, index === 0 ? 0.19 : 0.15, COLORS.joint, camera, width, height);
    if (disc) renderObjects.push(disc);
  });

  const faulted = state === "FAULT" || state === "ESTOPPED";
  const toolColor = faulted ? COLORS.danger : moving ? COLORS.accent : "#5f706b";
  const gripper = disc3d(effector, 0.12, toolColor, camera, width, height, moving && !faulted);
  if (gripper) renderObjects.push(gripper);
  const fingerA = line3d(effector, { x: effector.x + 0.13, y: effector.y - 0.12, z: effector.z + 0.06 }, toolColor, 0.035, camera, width, height);
  const fingerB = line3d(effector, { x: effector.x - 0.03, y: effector.y - 0.13, z: effector.z - 0.13 }, toolColor, 0.035, camera, width, height);
  if (fingerA) renderObjects.push(fingerA);
  if (fingerB) renderObjects.push(fingerB);

  const carrying = frame.heldObjectId != null || (moving && p >= 0.45 && p < 0.96);
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
    if (selected) {
      const pulse = 0.24 + Math.sin(time / 320) * 0.025;
      const marker = disc3d({ ...position, y: 0.765 }, pulse, "rgba(225,120,82,.32)", camera, width, height, true);
      if (marker) renderObjects.push(marker);
    }
  });
  if (carrying) {
    renderObjects.push(...box({ ...effector, y: effector.y - 0.22 }, { x: 0.3, y: 0.3, z: 0.3 }, ["#e18a65", "#b9563d", "#71382e"], camera, width, height));
  }

  const handoffMarker = disc3d({ x: handoff.x, y: 0.77, z: handoff.z }, 0.35, "rgba(143,197,168,.22)", camera, width, height, stage.includes("HANDOFF"));
  if (handoffMarker) renderObjects.push(handoffMarker);
  renderObjects.sort((a, b) => b.depth - a.depth).forEach((item) => item.draw(ctx));

  objects.forEach((object, index) => {
    const position = carrying && object.object_id === selectedObjectId
      ? { ...effector, y: effector.y - 0.06 }
      : objectPositions[index];
    const point = project({ ...position, y: position.y + 0.32 }, camera, width, height);
    if (point) roundedLabel(ctx, point, object.class_name.replaceAll("_", " "), object.object_id === selectedObjectId);
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
      <div className="robot-canvas-hint">Drag to orbit · scroll to zoom · select an object</div>
      <div className={`robot-pause-indicator ${paused ? "show" : ""}`} aria-hidden={!paused}>
        <span>Ⅱ</span> Simulation paused
      </div>
    </div>
  );
}
