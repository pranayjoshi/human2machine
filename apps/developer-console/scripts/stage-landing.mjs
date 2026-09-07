import { cp, mkdir, rm } from "node:fs/promises";
import path from "node:path";

const source = path.resolve("out");
const destination = path.resolve("landing-dist");

await rm(destination, { recursive: true, force: true });
await mkdir(destination, { recursive: true });

for (const asset of [
  "_next",
  "404.html",
  "h2m-icon.png",
  "h2m-mark.svg",
  "human-skin-model.png",
  "index.html",
  "index.txt",
  "musculoskeletal-system.png",
  "og.png",
  "privacy.html",
  "privacy.txt",
]) {
  await cp(path.join(source, asset), path.join(destination, asset), { recursive: true });
}
