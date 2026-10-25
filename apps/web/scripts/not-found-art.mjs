// Derives the 404 artwork from the supplied source: the dark backdrop is keyed out
// ("color to alpha" against the sampled background) so the glow survives on any canvas.
import { writeFile } from "node:fs/promises";
import path from "node:path";
import sharp from "sharp";

const root = path.resolve(import.meta.dirname, "../../..");
const source = path.join(root, "assets/brand/chobra-404-source.png");
const out = path.resolve(import.meta.dirname, "../public/brand");

const { data, info } = await sharp(source).removeAlpha().raw().toBuffer({ resolveWithObject: true });
const corners = [[4, 4], [info.width - 5, 4], [4, info.height - 5], [info.width - 5, info.height - 5]];
const bg = [0, 1, 2].map((c) => Math.round(corners.reduce((sum, [x, y]) => sum + data[(y * info.width + x) * 3 + c], 0) / corners.length));

const rgba = Buffer.alloc(info.width * info.height * 4);
let minX = info.width, minY = info.height, maxX = 0, maxY = 0;
for (let i = 0; i < info.width * info.height; i++) {
  const px = [data[i * 3], data[i * 3 + 1], data[i * 3 + 2]];
  let alpha = 0;
  for (let c = 0; c < 3; c++) {
    // only brightening counts: darker-than-backdrop noise would otherwise divide by a tiny span
    alpha = Math.max(alpha, Math.max(0, px[c] - bg[c]) / (255 - bg[c]));
  }
  if (alpha < 0.04) alpha = 0; // compression noise in the backdrop
  for (let c = 0; c < 3; c++) rgba[i * 4 + c] = alpha ? Math.max(0, Math.min(255, Math.round(bg[c] + (px[c] - bg[c]) / alpha))) : 0;
  rgba[i * 4 + 3] = Math.round(alpha * 255);
  if (px[0] > 150 && px[1] > 100 && px[2] < 140) {
    // bounds follow the yellow artwork itself; the source has a light 1px frame at its edges
    const x = i % info.width, y = Math.floor(i / info.width);
    minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }
}
const pad = 72; // room for the soft glow
const box = { left: Math.max(0, minX - pad), top: Math.max(0, minY - pad) };
box.width = Math.min(info.width, maxX + pad) - box.left;
box.height = Math.min(info.height, maxY + pad) - box.top;
const keyed = await sharp(rgba, { raw: { width: info.width, height: info.height, channels: 4 } }).extract(box).png().toBuffer();
await writeFile(path.join(out, "chobra-404.png"), await sharp(keyed).png({ compressionLevel: 9 }).toBuffer());
await sharp(keyed).webp({ quality: 90, alphaQuality: 95 }).toFile(path.join(out, "chobra-404.webp"));

// Recompose over the sampled backdrop and compare with the source crop.
const original = await sharp(source).removeAlpha().extract(box).raw().toBuffer();
const recomposed = await sharp({ create: { width: box.width, height: box.height, channels: 3, background: { r: bg[0], g: bg[1], b: bg[2] } } })
  .composite([{ input: keyed }]).removeAlpha().raw().toBuffer();
let total = 0;
for (let i = 0; i < original.length; i++) total += Math.abs(original[i] - recomposed[i]);
console.log(JSON.stringify({ background: bg, size: [box.width, box.height], meanAbsoluteError: Number((total / original.length).toFixed(3)) }));
