import { cp, mkdir, rm } from "node:fs/promises";
import path from "node:path";

const source = path.resolve("out");
const destination = path.resolve("landing-dist");

await rm(destination, { recursive: true, force: true });
await mkdir(destination, { recursive: true });

// Only the public landing is published; the operator console pages stay out of the bundle.
for (const asset of [
  "_next",
  "404.html",
  "console-operate.png",
  "console-robot.png",
  "h2m-icon.png",
  "h2m-mark.svg",
  "human-skin-model.png",
  "index.html",
  "index.txt",
  "musculoskeletal-system.png",
  "og.png",
  "robot-arm-poster-tall.webp",
  "robot-arm-poster-wide.webp",
  "privacy.html",
  "privacy.txt",
  "robots.txt",
  "sitemap.xml",
]) {
  await cp(path.join(source, asset), path.join(destination, asset), { recursive: true });
}

// Static hosts that do not map /privacy to privacy.html answer 404; also publish /privacy/index.html.
await mkdir(path.join(destination, "privacy"), { recursive: true });
await cp(path.join(source, "privacy.html"), path.join(destination, "privacy", "index.html"));
