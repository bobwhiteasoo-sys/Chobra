// Derived brand files from the unchanged master mark (spec section 22).
// The master has a dark background, so the square icons keep their own dark underlay;
// a transparent mark is derived by alpha keying and checked against the master.
import sharp from "sharp";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const master = path.resolve(here, "../../../assets/brand/chobra-logo-master.png");
const out = path.resolve(here, "../public/brand");
const appDir = path.resolve(here, "../src/app");
const CANVAS = { r: 7, g: 5, b: 17 };

await mkdir(out, { recursive: true });
const meta = await sharp(master).metadata();
const { data, info } = await sharp(master).removeAlpha().raw().toBuffer({ resolveWithObject: true });

// Bounding box of the yellow mark.
let minX = info.width, minY = info.height, maxX = 0, maxY = 0;
for (let y = 0; y < info.height; y++) {
  for (let x = 0; x < info.width; x++) {
    const i = (y * info.width + x) * 3;
    if (data[i] > 120 && data[i + 1] > 90 && data[i + 2] < 140) {
      if (x < minX) minX = x; if (x > maxX) maxX = x; if (y < minY) minY = y; if (y > maxY) maxY = y;
    }
  }
}
const markW = maxX - minX + 1, markH = maxY - minY + 1;
const side = Math.round(Math.max(markW, markH) * 1.5); // a quarter of the mark height on each side, at least
const cx = Math.round((minX + maxX) / 2), cy = Math.round((minY + maxY) / 2);
const left = Math.max(0, cx - Math.round(side / 2)), top = Math.max(0, cy - Math.round(side / 2));
const square = await sharp(master).extract({ left, top, width: Math.min(side, meta.width - left), height: Math.min(side, meta.height - top) })
  .resize(1024, 1024, { fit: "contain", background: { ...CANVAS, alpha: 1 } }).png().toBuffer();

for (const size of [24, 32, 48, 64, 128, 192, 512]) {
  await sharp(square).resize(size, size, { kernel: "lanczos3" }).png({ compressionLevel: 9 }).toFile(path.join(out, `chobra-${size}.png`));
}
await sharp(square).resize(32, 32).png().toFile(path.join(appDir, "icon.png"));
await sharp(square).resize(180, 180).png().toFile(path.join(appDir, "apple-icon.png"));

// Maskable: the mark inside the 80 % safe circle.
const inner = await sharp(square).resize(360, 360).png().toBuffer();
await sharp({ create: { width: 512, height: 512, channels: 4, background: { ...CANVAS, alpha: 1 } } })
  .composite([{ input: inner, left: 76, top: 76 }]).png().toFile(path.join(out, "chobra-maskable-512.png"));

// Transparent mark by alpha keying against the dark background.
const crop = await sharp(master).extract({ left: minX - 8, top: minY - 8, width: markW + 16, height: markH + 16 }).removeAlpha().raw().toBuffer({ resolveWithObject: true });
const rgba = Buffer.alloc(crop.info.width * crop.info.height * 4);
const yellow = { r: 252, g: 207, b: 74 };
for (let p = 0; p < crop.info.width * crop.info.height; p++) {
  const r = crop.data[p * 3], g = crop.data[p * 3 + 1], b = crop.data[p * 3 + 2];
  const alpha = Math.max(0, Math.min(1, ((r + g) / 2 - 12) / ((yellow.r + yellow.g) / 2 - 12)));
  rgba[p * 4] = yellow.r; rgba[p * 4 + 1] = yellow.g; rgba[p * 4 + 2] = yellow.b; rgba[p * 4 + 3] = Math.round(alpha * 255);
}
const transparent = await sharp(rgba, { raw: { width: crop.info.width, height: crop.info.height, channels: 4 } }).png().toBuffer();
await writeFile(path.join(out, "chobra-mark-transparent.png"), transparent);

// Visual comparison: the keyed mark over the master's own background vs the master crop.
const bgSample = { r: crop.data[0], g: crop.data[1], b: crop.data[2] };
const recomposed = await sharp({ create: { width: crop.info.width, height: crop.info.height, channels: 3, background: bgSample } })
  .composite([{ input: transparent }]).removeAlpha().raw().toBuffer();
let total = 0, worst = 0;
for (let i = 0; i < recomposed.length; i++) {
  const d = Math.abs(recomposed[i] - crop.data[i]);
  total += d; if (d > worst) worst = d;
}
const meanError = total / recomposed.length;
await writeFile(path.join(out, "transparent-check.json"), JSON.stringify({ meanAbsoluteError: Number(meanError.toFixed(3)), worstChannelError: worst, verdict: meanError < 3 ? "ok" : "review" }, null, 2));

// Social image 1200x630.
const markSmall = await sharp(transparent).resize({ height: 300 }).png().toBuffer();
const svg = `<svg width="1200" height="630" xmlns="http://www.w3.org/2000/svg"><rect width="1200" height="630" fill="#070511"/>
<text x="470" y="300" font-family="Inter, Helvetica, Arial, sans-serif" font-size="96" font-weight="700" fill="#FFD447">Chobra</text>
<text x="472" y="370" font-family="Inter, Helvetica, Arial, sans-serif" font-size="34" fill="#A6A0B5">Испытание правил мотивации</text>
<text x="472" y="416" font-family="Inter, Helvetica, Arial, sans-serif" font-size="34" fill="#A6A0B5">до того, как их введут для людей</text></svg>`;
await sharp(Buffer.from(svg)).composite([{ input: markSmall, left: 150, top: 165 }]).png().toFile(path.join(out, "chobra-social.png"));
await sharp(path.join(out, "chobra-social.png")).toFile(path.join(appDir, "opengraph-image.png"));
console.log(JSON.stringify({ box: { minX, minY, markW, markH }, meanError: Number(meanError.toFixed(3)), worst }));
