// Re-record docs/screenshot.png and docs/demo.gif from a running local copy of the app.
//   streamlit run app.py --server.headless true --server.port 8599
//   node docs/media/record.cjs          (needs playwright and ffmpeg)
// Uses whatever data is in data/brief.db, so the images show real data.
const { chromium } = require("playwright");
const { execFileSync } = require("node:child_process");
const { mkdtempSync, readdirSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");

(async () => {

const URL = "http://localhost:8599";
const frames = mkdtempSync(join(tmpdir(), "frames-"));
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2 });
await page.goto(URL, { waitUntil: "networkidle" });
await page.waitForSelector('[data-testid="stAppViewContainer"] h1');
await page.waitForTimeout(4000);
await page.screenshot({ path: "docs/screenshot.png" });

let n = 0;
const snap = async (repeat = 1) => {
  const path = join(frames, `f${String(n).padStart(3, "0")}.png`);
  await page.screenshot({ path });
  for (let i = 1; i < repeat; i++) execFileSync("cp", [path, join(frames, `f${String(n + i).padStart(3, "0")}.png`)]);
  n += repeat;
};
await page.setViewportSize({ width: 1280, height: 720 });
await snap(4);
await page.getByText("Try to break it:").first().click();
await page.waitForTimeout(1500);
const demo = page.getByRole("button", { name: "Inject fault (simulated)" });
await demo.scrollIntoViewIfNeeded();
await page.mouse.wheel(0, 120);
await page.waitForTimeout(800);
await snap(4);
await demo.click();
await page.waitForTimeout(3000);
await page.getByText("Simulated result").first().evaluate((el) => el.scrollIntoView({ block: "start" }));
await page.mouse.wheel(0, -90);
await page.waitForTimeout(800);
await snap(10);
await browser.close();

console.log(`${readdirSync(frames).length} frames`);
execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-framerate", "1", "-i", join(frames, "f%03d.png"),
  "-vf", "scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=none",
  "-loop", "0", "docs/demo.gif"]);
console.log("wrote docs/screenshot.png and docs/demo.gif");
})();
