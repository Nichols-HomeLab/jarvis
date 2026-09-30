import { copyFile, mkdir, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join } from "node:path";

const publicDir = join(process.cwd(), "public", "gestures");
await mkdir(publicDir, { recursive: true });
const wasmDir = join(process.cwd(), "node_modules", "@mediapipe", "tasks-vision", "wasm");
for (const file of ["vision_wasm_internal.wasm", "vision_wasm_internal.js", "vision_wasm_nosimd_internal.wasm", "vision_wasm_nosimd_internal.js"]) {
  await copyFile(join(wasmDir, file), join(publicDir, file));
}
const modelPath = join(publicDir, "hand_landmarker.task");
if (!existsSync(modelPath)) {
  const url = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task";
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Hand model download failed: ${response.status}`);
  await writeFile(modelPath, Buffer.from(await response.arrayBuffer()));
}
