// Cloudflare Worker that starts the refresh workflow on a timer.
//
// GitHub's own cron can start hours late or not at all, while workflow_dispatch has
// started every time it was called. So this Worker is the main trigger and the
// workflow's cron is the backup. Both pass through scripts/should_refresh.py, so only
// the first refresh of the day runs.
//
// Secret: GITHUB_TOKEN, a fine-grained token for this one repository with only
// "Actions: Read and write". Set it with `npx wrangler secret put GITHUB_TOKEN`.

const WORKFLOW = "refresh.yml";

export async function dispatch(env, fetchImpl = fetch, wait = (ms) => new Promise((r) => setTimeout(r, ms))) {
  const url = `https://api.github.com/repos/${env.REPO}/actions/workflows/${WORKFLOW}/dispatches`;
  for (let attempt = 1; attempt <= 3; attempt++) {
    const res = await fetchImpl(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "morning-brief-scheduler",
      },
      body: JSON.stringify({ ref: env.BRANCH, inputs: { trigger: "scheduler" } }),
    });
    if (res.status === 204) {
      console.log(`dispatched ${WORKFLOW} on attempt ${attempt}`);
      return true;
    }
    console.log(`attempt ${attempt}: HTTP ${res.status} ${await res.text()}`);
    // Bad or expired token, wrong repo or branch: retrying won't help
    if ([401, 403, 404, 422].includes(res.status)) break;
    await wait(5000 * attempt);
  }
  // A thrown error marks this invocation failed in the Cloudflare dashboard.
  // Healthchecks.io still alerts if no refresh happens.
  throw new Error(`could not dispatch ${WORKFLOW}`);
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispatch(env));
  },
};
