# Scheduler and heartbeat

GitHub's `schedule` trigger only promises to try. In this repo it was missed three
weekdays in a row and then started 7h20m late (build notes 28, 29 and 31). So the
refresh now has three triggers and a monitor that sits outside GitHub:

| Piece | When (UTC, weekdays) | What it does |
|---|---|---|
| Cloudflare Worker (this folder) | 11:05, retry 11:35 | Calls `workflow_dispatch` on `refresh.yml` with `trigger=scheduler` |
| GitHub cron in `refresh.yml` | 11:21 | Backup |
| `scripts/should_refresh.py` | first step of every run | Lets the first automatic run of the New York day refresh; later ones stop |
| Healthchecks.io | deadline about 12:20 | Emails you if no refresh has pinged by then, or at once if one pinged `/fail` |

A manual "Run workflow" always refreshes.

## One-time setup (about 20 minutes)

### 1. GitHub token for the Worker

1. GitHub → your avatar → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. Token name: `morning-brief-scheduler`. Expiration: 90 days (put a calendar reminder to rotate it).
3. Repository access: **Only select repositories** → `kechunwu/morning-brief`.
4. Permissions → Repository permissions → **Actions: Read and write**. Leave everything else at No access.
5. **Generate token** and copy it. It is shown once.

### 2. Deploy the Worker

Needs Node 18+ and a free Cloudflare account.

```bash
cd ops/scheduler
npx wrangler login
npx wrangler secret put GITHUB_TOKEN     # paste the token from step 1
npx wrangler deploy
```

The token is stored encrypted by Cloudflare, not in this repo. In the Cloudflare
dashboard, **Workers & Pages → morning-brief-scheduler → Settings → Triggers** should
list both cron times.

To test without waiting for 11:05, put the token in a local file that git ignores, then
start the Worker locally and fire its timer by hand:

```bash
echo "GITHUB_TOKEN=<the token>" > .dev.vars
npx wrangler dev --test-scheduled
```

```bash
curl "http://localhost:8787/__scheduled?cron=5+11+*+*+1-5"
```

A new `pre-open refresh` run should appear in the Actions tab within a minute, labeled
`workflow_dispatch`. Because it's an automatic trigger, it skips if a refresh already
ran today. That's the guard working, not a failure.

### 3. Heartbeat

1. Sign up at https://healthchecks.io (free plan) → **Add Check**.
2. Name `morning-brief refresh`. Schedule: **Cron**, expression `5 11 * * 1-5`, time zone **UTC**, grace time **75 minutes**.
3. Copy the ping URL (`https://hc-ping.com/...`). Under **Integrations**, keep email on.
4. GitHub → the repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**. Name `HEALTHCHECK_URL`, value: the ping URL.

The next refresh pings it. Until the secret exists, that step logs "HEALTHCHECK_URL not
set, skipping".

## Running the Worker tests

```bash
node --test ops/scheduler/test/worker.test.mjs
```

`pytest` runs these too when Node is installed.
