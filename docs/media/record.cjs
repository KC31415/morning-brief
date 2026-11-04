// Re-record docs/screenshot.png and docs/demo.gif from a local build of the static site.
//   python scripts/build_site.py --out public
//   python -m http.server 8601 --directory public
//   node docs/media/record.cjs          (needs playwright and ffmpeg)
// Uses whatever data is in data/, so the images show real data.
const { chromium } = require("playwright");
const { execFileSync } = require("node:child_process");
const { mkdtempSync, readdirSync, copyFileSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");

const URL = process.env.SITE_URL || "http://localhost:8601/index.html";

(async () => {
  const frames = mkdtempSync(join(tmpdir(), "frames-"));
  const browser = await browserLaunch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2 });
  await page.goto(URL, { waitUntil: "networkidle" });
  await page.waitForTimeout(800);
  await page.screenshot({ path: "docs/screenshot.png" });

  let n = 0;
  const snap = async (repeat = 1) => {
    const path = join(frames, `f${String(n).padStart(3, "0")}.png`);
    await page.screenshot({ path });
    for (let i = 1; i < repeat; i++) copyFileSync(path, join(frames, `f${String(n + i).padStart(3, "0")}.png`));
    n += repeat;
  };
  await page.setViewportSize({ width: 1280, height: 720 });
  await snap(3);
  await page.click("#try-to-break-it summary");
  await page.waitForTimeout(300);
  await page.locator(".demo-controls").evaluate((el) => el.scrollIntoView({ block: "center" }));
  await page.waitForTimeout(300);
  await snap(3);
  await page.selectOption("#demo-fault", { label: "+50% bad print" });
  await page.click("#demo-run");
  await page.waitForTimeout(300);
  await page.locator("#demo-result").evaluate((el) => el.scrollIntoView({ block: "center" }));
  await page.waitForTimeout(300);
  await snap(6);
  await page.selectOption("#demo-fault", { label: "Frozen feed" });
  await page.click("#demo-run");
  await page.waitForTimeout(300);
  await snap(6);
  await browser.close();

  console.log(`${readdirSync(frames).length} frames`);
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-framerate", "1", "-i", join(frames, "f%03d.png"),
    "-vf", "scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=none",
    "-loop", "0", "docs/demo.gif"]);
  console.log("wrote docs/screenshot.png and docs/demo.gif");
})();

function browserLaunch() {
  return chromium.launch();
}
