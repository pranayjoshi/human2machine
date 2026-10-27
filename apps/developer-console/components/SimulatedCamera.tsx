"use client";

import { useEffect, useRef } from "react";

import type { VisionObject } from "@/lib/types";

/** Detections arrive in the camera's pixel space. The simulator's mock camera is 640x480. */
export const SIM_FRAME = { width: 640, height: 480 };
const CANVAS = { width: 1280, height: 720 };
const SCALE = CANVAS.height / SIM_FRAME.height;
const OFFSET_X = (CANVAS.width - SIM_FRAME.width * SCALE) / 2;

export const CLASS_COLORS: Record<string, string> = {
  blue: "#3b6fd1",
  red: "#c9453a",
  green: "#3f9a6a",
  yellow: "#e2b43d",
};

export function colorFor(className: string): string {
  const match = Object.keys(CLASS_COLORS).find((name) => className.toLowerCase().includes(name));
  return match ? CLASS_COLORS[match] : "#9aa3ad";
}

function rng(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

function shade(hex: string, k: number): string {
  const n = parseInt(hex.slice(1), 16);
  const f = (c: number) => Math.round(Math.max(0, Math.min(255, c * k)));
  return `rgb(${f(n >> 16)},${f((n >> 8) & 255)},${f(n & 255)})`;
}

function paintTable(ctx: CanvasRenderingContext2D): void {
  const base = ctx.createLinearGradient(0, 0, CANVAS.width, CANVAS.height);
  base.addColorStop(0, "#d8c19a");
  base.addColorStop(0.55, "#cdb48b");
  base.addColorStop(1, "#bda177");
  ctx.fillStyle = base;
  ctx.fillRect(0, 0, CANVAS.width, CANVAS.height);

  const random = rng(7);
  ctx.save();
  ctx.lineCap = "round";
  for (let index = 0; index < 190; index += 1) {
    const y = random() * CANVAS.height;
    const x = random() * CANVAS.width * 1.1 - 80;
    const length = 160 + random() * 520;
    ctx.strokeStyle = `rgba(112, 82, 44, ${0.04 + random() * 0.09})`;
    ctx.lineWidth = 0.6 + random() * 1.6;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.bezierCurveTo(x + length * 0.3, y + (random() - 0.5) * 7, x + length * 0.7, y + (random() - 0.5) * 7, x + length, y + (random() - 0.5) * 4);
    ctx.stroke();
  }
  ctx.restore();

  // Soft key light from above-left.
  const light = ctx.createRadialGradient(CANVAS.width * 0.42, CANVAS.height * 0.3, 40, CANVAS.width * 0.42, CANVAS.height * 0.4, CANVAS.width * 0.75);
  light.addColorStop(0, "rgba(255, 246, 226, .32)");
  light.addColorStop(1, "rgba(255, 246, 226, 0)");
  ctx.fillStyle = light;
  ctx.fillRect(0, 0, CANVAS.width, CANVAS.height);
}

function paintMat(ctx: CanvasRenderingContext2D): void {
  ctx.save();
  ctx.fillStyle = "rgba(60, 74, 66, .10)";
  ctx.beginPath();
  ctx.roundRect(50, 46, 440, 372, 10);
  ctx.fill();
  ctx.setLineDash([7, 6]);
  ctx.strokeStyle = "rgba(34, 98, 74, .55)";
  ctx.lineWidth = 1.4;
  ctx.stroke();
  ctx.restore();
}

function segmentPlate(ctx: CanvasRenderingContext2D, a: [number, number], b: [number, number], width: number, color: string): void {
  const angle = Math.atan2(b[1] - a[1], b[0] - a[0]);
  const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
  ctx.save();
  ctx.translate(a[0], a[1]);
  ctx.rotate(angle);
  const fill = ctx.createLinearGradient(0, -width / 2, 0, width / 2);
  fill.addColorStop(0, shade(color, 1.05));
  fill.addColorStop(0.5, shade(color, 0.93));
  fill.addColorStop(1, shade(color, 0.78));
  ctx.fillStyle = fill;
  ctx.beginPath();
  ctx.roundRect(-8, -width / 2, length + 16, width, 9);
  ctx.fill();
  ctx.strokeStyle = "rgba(60, 50, 38, .35)";
  ctx.lineWidth = 0.8;
  ctx.stroke();
  // Twin-plate cutout.
  ctx.fillStyle = "rgba(40, 34, 28, .18)";
  ctx.beginPath();
  ctx.roundRect(14, -width / 2 + 7, length - 12, width - 14, 5);
  ctx.fill();
  ctx.restore();
}

function servoBlock(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, angle: number): void {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(angle);
  const fill = ctx.createLinearGradient(0, -h / 2, 0, h / 2);
  fill.addColorStop(0, "#2d3138");
  fill.addColorStop(1, "#14171b");
  ctx.fillStyle = fill;
  ctx.beginPath();
  ctx.roundRect(-w / 2, -h / 2, w, h, 4);
  ctx.fill();
  ctx.fillStyle = "#d87855";
  ctx.beginPath();
  ctx.arc(0, 0, Math.min(w, h) * 0.26, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "rgba(0,0,0,.45)";
  ctx.beginPath();
  ctx.arc(0, 0, Math.min(w, h) * 0.1, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function paintArm(ctx: CanvasRenderingContext2D): void {
  const base: [number, number] = [588, 66];
  const elbow: [number, number] = [508, 186];
  const wrist: [number, number] = [440, 286];
  const tip: [number, number] = [404, 322];
  ctx.save();
  // Shadows first.
  ctx.filter = "blur(7px)";
  ctx.globalAlpha = 0.32;
  ctx.translate(11, 15);
  ctx.fillStyle = "#1a120a";
  ctx.beginPath();
  ctx.roundRect(base[0] - 52, base[1] - 40, 104, 80, 8);
  ctx.fill();
  ctx.strokeStyle = "#1a120a";
  ctx.lineCap = "round";
  ctx.lineWidth = 32;
  ctx.beginPath();
  ctx.moveTo(...base);
  ctx.lineTo(...elbow);
  ctx.lineTo(...wrist);
  ctx.lineWidth = 26;
  ctx.lineTo(...tip);
  ctx.stroke();
  ctx.restore();

  // Clamped base plate.
  ctx.save();
  ctx.fillStyle = "#2a2e33";
  ctx.beginPath();
  ctx.roundRect(base[0] - 50, base[1] - 38, 100, 76, 7);
  ctx.fill();
  ctx.fillStyle = "#3b4046";
  ([[-40, -28], [40, -28], [-40, 28], [40, 28]] as const).forEach(([dx, dy]) => {
    ctx.beginPath();
    ctx.arc(base[0] + dx, base[1] + dy, 4, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.restore();

  segmentPlate(ctx, base, elbow, 36, "#e8e3d6");
  segmentPlate(ctx, elbow, wrist, 32, "#e8e3d6");
  servoBlock(ctx, base[0], base[1], 46, 40, Math.atan2(elbow[1] - base[1], elbow[0] - base[0]));
  servoBlock(ctx, elbow[0], elbow[1], 42, 36, Math.atan2(wrist[1] - elbow[1], wrist[0] - elbow[0]));
  servoBlock(ctx, wrist[0], wrist[1], 34, 30, Math.atan2(tip[1] - wrist[1], tip[0] - wrist[0]));

  // Two-jaw gripper seen from above.
  const angle = Math.atan2(tip[1] - wrist[1], tip[0] - wrist[0]);
  ctx.save();
  ctx.translate(wrist[0], wrist[1]);
  ctx.rotate(angle);
  ctx.fillStyle = "#1c1f24";
  ctx.beginPath();
  ctx.roundRect(8, -15, 24, 30, 4);
  ctx.fill();
  ([-1, 1] as const).forEach((side) => {
    ctx.fillStyle = "#e8e3d6";
    ctx.beginPath();
    ctx.roundRect(28, side * 13 - 3.5, 40, 7, 3);
    ctx.fill();
    ctx.fillStyle = "#5f706b";
    ctx.beginPath();
    ctx.roundRect(60, side * 13 - 4.5, 10, 9, 2);
    ctx.fill();
  });
  ctx.restore();

  // Servo cable.
  ctx.save();
  ctx.strokeStyle = "#121417";
  ctx.lineWidth = 3;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(base[0] + 18, base[1] + 22);
  ctx.quadraticCurveTo(elbow[0] + 34, elbow[1] - 30, elbow[0] + 16, elbow[1] + 18);
  ctx.quadraticCurveTo(wrist[0] + 30, wrist[1] - 18, wrist[0] + 8, wrist[1] + 14);
  ctx.stroke();
  ctx.restore();
}

function paintBlock(ctx: CanvasRenderingContext2D, object: VisionObject): void {
  const [x1, y1, x2, y2] = object.bbox_xyxy;
  const size = Math.min(x2 - x1, y2 - y1) * 0.62;
  const cx = (x1 + x2) / 2;
  const cy = (y1 + y2) / 2;
  const left = cx - size / 2;
  const top = cy - size / 2;
  const color = colorFor(object.class_name);
  const depth = size * 0.17;

  ctx.save();
  ctx.filter = "blur(5px)";
  ctx.fillStyle = "rgba(34, 22, 10, .42)";
  ctx.beginPath();
  ctx.roundRect(left + size * 0.1, top + size * 0.16, size, size + depth, 6);
  ctx.fill();
  ctx.restore();

  // South face.
  ctx.fillStyle = shade(color, 0.62);
  ctx.beginPath();
  ctx.roundRect(left, top + size - 4, size, depth + 4, [0, 0, 5, 5]);
  ctx.fill();
  // Top face with a soft gradient and bevel.
  const topFill = ctx.createLinearGradient(left, top, left + size, top + size);
  topFill.addColorStop(0, shade(color, 1.22));
  topFill.addColorStop(1, shade(color, 0.94));
  ctx.fillStyle = topFill;
  ctx.beginPath();
  ctx.roundRect(left, top, size, size, 5);
  ctx.fill();
  ctx.strokeStyle = "rgba(255,255,255,.34)";
  ctx.lineWidth = 1.1;
  ctx.beginPath();
  ctx.roundRect(left + 1, top + 1, size - 2, size - 2, 4);
  ctx.stroke();
  // Faint grain on the block.
  const random = rng(Math.round(cx * 13 + cy * 7));
  ctx.strokeStyle = "rgba(255,255,255,.10)";
  ctx.lineWidth = 0.8;
  for (let index = 0; index < 5; index += 1) {
    const y = top + 6 + random() * (size - 12);
    ctx.beginPath();
    ctx.moveTo(left + 5, y);
    ctx.lineTo(left + size - 5, y + (random() - 0.5) * 3);
    ctx.stroke();
  }
}

function paintGrain(ctx: CanvasRenderingContext2D): void {
  const random = rng(99);
  for (let index = 0; index < 9000; index += 1) {
    const light = random() > 0.5;
    ctx.fillStyle = light ? "rgba(255,255,255,.035)" : "rgba(0,0,0,.04)";
    ctx.fillRect(random() * CANVAS.width, random() * CANVAS.height, 1.4, 1.4);
  }
  const vignette = ctx.createRadialGradient(CANVAS.width / 2, CANVAS.height / 2, CANVAS.height * 0.35, CANVAS.width / 2, CANVAS.height / 2, CANVAS.width * 0.66);
  vignette.addColorStop(0, "rgba(0,0,0,0)");
  vignette.addColorStop(1, "rgba(18, 10, 4, .5)");
  ctx.fillStyle = vignette;
  ctx.fillRect(0, 0, CANVAS.width, CANVAS.height);
}

export function SimulatedCamera({ objects }: { objects: VisionObject[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const key = JSON.stringify(objects.map((object) => [object.object_id, object.class_name, object.bbox_xyxy]));

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    ctx.clearRect(0, 0, CANVAS.width, CANVAS.height);
    paintTable(ctx);
    ctx.save();
    ctx.translate(OFFSET_X, 0);
    ctx.scale(SCALE, SCALE);
    paintMat(ctx);
    objects.forEach((object) => paintBlock(ctx, object));
    paintArm(ctx);
    ctx.restore();
    paintGrain(ctx);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return (
    <canvas
      ref={canvasRef}
      width={CANVAS.width}
      height={CANVAS.height}
      aria-hidden="true"
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
    />
  );
}
