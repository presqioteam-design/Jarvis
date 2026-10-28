/**
 * Jarvis cron worker.
 * Each Cron Trigger calls one job on the API. The first request also wakes
 * the free Render instance, so we allow a long timeout and one retry.
 */

export interface Env {
  API_URL: string;
  CRON_SECRET: string;
}

const JOBS: Record<string, string> = {
  "30 2 * * MON-FRI": "/jobs/morning-brief",
  "30 4-12 * * MON-FRI": "/jobs/focus-check",
  "30 13 * * MON-FRI": "/jobs/daily-review",
};

async function runJob(env: Env, path: string): Promise<void> {
  const url = `${env.API_URL.replace(/\/$/, "")}${path}`;
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "X-Cron-Secret": env.CRON_SECRET },
        signal: AbortSignal.timeout(90_000),
      });
      console.log(`${path} → ${res.status}`);
      if (res.ok) return;
    } catch (err) {
      console.warn(`${path} attempt ${attempt} failed`, err);
    }
  }
}

export default {
  async scheduled(event: ScheduledController, env: Env, ctx: ExecutionContext) {
    const path = JOBS[event.cron];
    if (!path) {
      console.warn(`No job mapped for cron "${event.cron}"`);
      return;
    }
    ctx.waitUntil(runJob(env, path));
  },

  async fetch(): Promise<Response> {
    return new Response("jarvis-cron is running", { status: 200 });
  },
} satisfies ExportedHandler<Env>;
