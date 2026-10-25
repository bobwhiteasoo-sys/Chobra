// Turns tokens.json (spec section 22) into CSS custom properties for the web app.
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const tokens = JSON.parse(await readFile(path.join(here, "tokens.json"), "utf8"));
const lines = ["/* Generated from packages/design-tokens/tokens.json. Do not edit by hand. */", ":root {"];
for (const [name, value] of Object.entries(tokens.colors)) lines.push(`  --${name.replaceAll(".", "-")}: ${value};`);
tokens.spacing_px.forEach((value) => lines.push(`  --space-${value}: ${value}px;`));
for (const [name, value] of Object.entries(tokens.radius_px)) lines.push(`  --radius-${name}: ${value}px;`);
lines.push(`  --font-family: "${tokens.font_family}", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;`);
const m = tokens.motion;
lines.push(`  --motion-press: ${m.press_ms}ms;`, `  --motion-inspector: ${m.inspector_ms}ms;`, `  --motion-marker: ${m.event_marker_ms}ms;`, `  --motion-highlight: ${m.highlight_ms}ms;`, `  --ease-out: ${m.ease_out};`);
lines.push("}", "@media (prefers-reduced-motion: reduce) {", "  :root { --motion-press: 0ms; --motion-inspector: 0ms; --motion-marker: 0ms; --motion-highlight: 0ms; }", "}");
await writeFile(path.resolve(here, "../../apps/web/src/styles/tokens.css"), lines.join("\n") + "\n");
console.log("tokens.css written");
