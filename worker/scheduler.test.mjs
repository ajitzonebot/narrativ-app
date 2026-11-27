// node --test worker/scheduler.test.mjs : the Worker's 10-minute scheduler table and watchdog (pure functions only)
import test from "node:test";
import assert from "node:assert/strict";
import { dueJobs, overdue } from "./worker.js";

const at = (iso) => Date.parse(iso);

test("daily run and its retries on weekdays only", () => {
  assert.ok(dueJobs(at("2026-11-27T11:40:00Z")).includes("daily.yml"));   // Fri 17:10 IST
  assert.ok(dueJobs(at("2026-11-27T14:40:00Z")).includes("daily.yml"));   // 20:10 IST retry
  assert.ok(dueJobs(at("2026-11-27T16:40:00Z")).includes("daily.yml"));   // 22:10 IST retry
  assert.ok(!dueJobs(at("2026-11-28T11:40:00Z")).includes("daily.yml"));  // Saturday
  assert.ok(!dueJobs(at("2026-11-27T11:50:00Z")).includes("daily.yml"));
});

test("a late tick still lands in its 10-minute slot", () => {
  assert.ok(dueJobs(at("2026-11-27T11:40:00Z") + 50 * 1000).includes("daily.yml"));
});

test("every-N jobs", () => {
  assert.ok(dueJobs(at("2026-11-27T11:30:00Z")).includes("republish.yml"));
  assert.ok(!dueJobs(at("2026-11-27T11:10:00Z")).includes("republish.yml"));
  assert.ok(dueJobs(at("2026-11-27T14:20:00Z")).includes("news.yml"));
  assert.ok(!dueJobs(at("2026-11-27T15:20:00Z")).includes("news.yml"));
  assert.ok(dueJobs(at("2026-11-27T00:40:00Z")).includes("histfin.yml"));
  assert.ok(dueJobs(at("2026-11-27T22:40:00Z")).includes("histfin.yml"));
  assert.ok(!dueJobs(at("2026-11-27T01:40:00Z")).includes("histfin.yml"));
});

test("weekend, weekly and monthly jobs", () => {
  assert.ok(dueJobs(at("2026-11-28T09:20:00Z")).includes("reader.yml"));   // Saturday
  assert.ok(!dueJobs(at("2026-11-27T09:20:00Z")).includes("reader.yml"));  // Friday: the reader follows the daily run
  assert.ok(dueJobs(at("2026-11-28T06:50:00Z")).includes("factors.yml"));
  assert.ok(dueJobs(at("2026-12-01T07:20:00Z")).includes("replay.yml"));
  assert.ok(!dueJobs(at("2026-12-02T07:20:00Z")).includes("replay.yml"));
  assert.deepEqual(dueJobs(at("2026-11-27T03:00:00Z")).filter((w) => w === "ipo.yml"), ["ipo.yml"]);
});

test("watchdog: missed window and failed last run", () => {
  const now = at("2026-11-27T03:30:00Z"); // Friday 09:00 IST
  const run = (h, status = "completed", conclusion = "success") =>
    ({ created_at: new Date(now - h * 3600000).toISOString(), status, conclusion, html_url: "u" });
  const bad = overdue({ "news.yml": [run(9)], "republish.yml": [run(0.4)], "filings.yml": [run(20, "completed", "failure")],
                        "story.yml": [run(2)], "daily.yml": [run(15)] }, now);
  assert.deepEqual(bad.map((b) => b.wf), ["filings.yml", "news.yml"]);
  assert.match(bad.find((b) => b.wf === "news.yml").why, /no run for 9 hours/);
  // Monday morning: the daily run is not watched (its last run was Friday)
  const mon = at("2026-11-30T03:30:00Z");
  assert.deepEqual(overdue({ "daily.yml": [{ created_at: "2026-11-27T11:40:00Z", status: "completed", conclusion: "success" }] }, mon), []);
});
