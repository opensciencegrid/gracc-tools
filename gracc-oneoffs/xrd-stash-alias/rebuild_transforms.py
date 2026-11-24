#!/usr/bin/env python3
"""
rebuild_transforms.py

Drive the Nov 2026 rebuild of the OSDF summary transforms (TRANSFORMS.md, "Rebuilding After the Unmatched-Close
Exclusion"), one transform at a time, verifying every one-shot against a fresh source query. Made to run in the
background and be watched: every milestone is one stdout line starting with "EVENT", also appended to
<state-dir>/rebuild.log. State lives in <state-dir>/state.json, so a rerun resumes where the last one stopped.

Usage:
  rebuild_transforms.py plan                                     # the steps; contacts no OpenSearch
  rebuild_transforms.py status --url URL --user USER --state-dir DIR   # read-only snapshot
  rebuild_transforms.py run    --url URL --user USER --state-dir DIR --yes [--through STEP]

The password comes from $OPENSEARCH_PASSWORD (never the command line, which other users can see).

Steps, in order:
  retire-live    stop and delete the failed live transforms osdf-summary-2026-from-10-30 and -2027-from-01-01
  2026-11+live   one-shot for Nov 1 to the run day, and a new live transform from the run day (current data first)
  2027-live      a new live transform for 2027 from Jan 1
  2026-10 ... 2026-01, 2025-12   one month each, newest first, each with --clean-target --force

Each install runs install_transforms.py itself, so it gets the installer's clause check and cleanup. A one-shot is
then waited on until it finishes and verified: its rows in the target must be the only rows in its range, their
summed transform._doc_count must equal the source count under the transform's own data_selection_query, and their
summed read_sum must match the source's summed read. A transform that fails because a source index was briefly
unhealthy is restarted once the cluster is green again; any other failure stops the run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import requests

import install_transforms as it

HERE = Path(__file__).resolve().parent
INSTALLER = HERE / "install_transforms.py"

LIVE_TO_RETIRE = ["osdf-summary-2026-from-10-30", "osdf-summary-2027-from-01-01"]

# Expected totals after the rebuild, from read-only queries on 2026-11-23 (the table in TRANSFORMS.md). Only a
# sanity check: late records can still arrive. The real check is against a fresh source query.
EXPECTED = {
    "2025-12": (1_908_162_379, 25.36e15), "2026-01": (2_009_371_519, 38.05e15), "2026-02": (2_332_561_513, 38.40e15),
    "2026-03": (2_937_382_055, 46.59e15), "2026-04": (2_082_545_965, 32.97e15), "2026-05": (1_253_976_813, 18.40e15),
    "2026-06": (558_662_285, 9.38e15), "2026-07": (1_646_656_053, 19.33e15), "2026-08": (2_474_599_886, 32.79e15),
    "2026-09": (3_008_626_639, 24.51e15), "2026-10": (1_549_212_020, 16.14e15),
}

POLL_SECONDS = 60
PROGRESS_EVERY_SECONDS = 30 * 60
STALL_AFTER_SECONDS = 2 * 3600
MAX_HEALTH_RETRIES = 3
READ_TOLERANCE = 1e-9            # relative difference allowed between summed read_sum and the source's summed read
LATE_TOLERANCE = 1e-3            # share of records allowed to arrive late for a range that ended in the last 3 days


@dataclass(frozen=True)
class Step:
    name: str
    kind: str                     # "retire" or "install"
    installer_args: tuple = ()


def month_args(year: int, first: int, last: int, clean: bool = True) -> tuple:
    args = ("--start-year", str(year), "--end-year", str(year), "--start-month", str(first), "--end-month", str(last))
    return args + (("--clean-target", "--force") if clean else ())


def build_steps() -> list[Step]:
    steps = [Step("retire-live", "retire"),
             Step("2026-11+live", "install", month_args(2026, 11, 12)),
             Step("2027-live", "install", ("--start-year", "2027", "--end-year", "2027"))]
    for year, month in [(2026, m) for m in range(10, 0, -1)] + [(2025, 12)]:
        steps.append(Step(f"{year}-{month:02d}", "install", month_args(year, month, month)))
    return steps


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Cluster:
    """
    The few OpenSearch calls the driver makes. Tests replace it with a fake.
    """

    def __init__(self, url: str, user: str, password: str, verify: bool = True):
        self.url, self.auth, self.verify = url.rstrip("/"), (user, password), verify

    def _call(self, method: str, path: str, body: Optional[dict] = None, timeout: int = 120) -> tuple[int, dict]:
        resp = requests.request(method, self.url + path, json=body, auth=self.auth, verify=self.verify,
                                timeout=timeout, headers={"Content-Type": "application/json"})
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, {"text": resp.text[:500]}

    def transform(self, tid: str) -> Optional[dict]:
        code, body = self._call("GET", f"/_plugins/_transform/{tid}")
        return body.get("transform") if code == 200 else None

    def transform_ids(self) -> list[str]:
        code, body = self._call("GET", "/_plugins/_transform?size=1000")
        if code != 200:
            raise RuntimeError(f"listing transforms returned HTTP {code}: {json.dumps(body)[:300]}")
        return [t["_id"] for t in body.get("transforms", [])]

    def explain(self, tid: str) -> dict:
        code, body = self._call("GET", f"/_plugins/_transform/{tid}/_explain")
        if code != 200:
            raise RuntimeError(f"_explain {tid} returned HTTP {code}: {json.dumps(body)[:300]}")
        return (body.get(tid) or {}).get("transform_metadata") or {}

    def stop(self, tid: str) -> int:
        return self._call("POST", f"/_plugins/_transform/{tid}/_stop")[0]

    def start(self, tid: str) -> int:
        return self._call("POST", f"/_plugins/_transform/{tid}/_start")[0]

    def delete(self, tid: str) -> int:
        return self._call("DELETE", f"/_plugins/_transform/{tid}")[0]

    def health(self, index: str = "xrd-stash*") -> str:
        code, body = self._call("GET", f"/_cluster/health/{index}")
        return body.get("status", f"HTTP {code}")

    def search(self, index: str, body: dict, timeout: int = 3600) -> dict:
        code, result = self._call("POST", f"/{index}/_search", body, timeout=timeout)
        if code != 200 or "aggregations" not in result:
            raise RuntimeError(f"search on {index} returned HTTP {code}: {json.dumps(result)[:300]}")
        return result


def run_installer(url: str, user: str, args: tuple, log_path: Path) -> tuple[int, str]:
    """
    Run install_transforms.py with the password from the environment, logging its output. Returns (exit code, output).
    """
    cmd = [sys.executable, str(INSTALLER), "--url", url, "--user", user, *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=os.environ.copy(), cwd=str(HERE))
    output = proc.stdout + proc.stderr
    with open(log_path, "a") as log:
        log.write(f"$ {' '.join(cmd[1:])}\n{output}\n[exit {proc.returncode}]\n")
    return proc.returncode, output


INSTALLED_RE = re.compile(r"Installing transform job: (\S+)\s+\[(\S+), (\S+)\)(\s+continuous)?")


def parse_installed(output: str) -> list[dict]:
    return [{"id": m[1], "start": m[2], "end": m[3], "live": bool(m[4])} for m in INSTALLED_RE.finditer(output)]


class Driver:
    def __init__(self, cluster: Cluster, state_dir: Path, installer: Callable[[tuple, Path], tuple[int, str]],
                 poll: int = POLL_SECONDS, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.time):
        self.cluster, self.state_dir, self.installer = cluster, state_dir, installer
        self.poll, self.sleep, self.clock = poll, sleep, clock
        self.state_path = state_dir / "state.json"
        self.log_path = state_dir / "rebuild.log"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {"steps": {}}

    # --- bookkeeping -------------------------------------------------------------------------------------------
    def event(self, step: str, kind: str, detail: str = "") -> None:
        line = f"EVENT {utcnow()} {step} {kind} {detail}".rstrip()
        print(line, flush=True)
        with open(self.log_path, "a") as log:
            log.write(line + "\n")

    def save(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=1))
        tmp.replace(self.state_path)

    def step_state(self, name: str) -> dict:
        return self.state["steps"].setdefault(name, {"status": "pending"})

    # --- the run -----------------------------------------------------------------------------------------------
    def run(self, steps: list[Step], through: Optional[str] = None) -> int:
        self.event("run", "start", f"{len(steps)} steps, state in {self.state_dir}")
        if not self.preflight():
            return 3
        for step in steps:
            st = self.step_state(step.name)
            if st["status"] == "done":
                self.event(step.name, "skip", "already done")
            else:
                ok = self.retire(step, st) if step.kind == "retire" else self.install(step, st)
                self.save()
                if not ok:
                    self.event(step.name, "STOPPED", "run stopped; fix the cause and rerun to resume")
                    return 3
            if step.name == through:
                self.event("run", "paused", f"stopped after {through} as asked (--through)")
                return 0
        self.check_live(final=True)
        self.event("run", "done", "every step finished and verified")
        return 0

    def preflight(self) -> bool:
        health = self.cluster.health()
        if health != "green":
            self.event("preflight", "wait", f"xrd-stash* health is {health}")
            if not self.wait_green("preflight"):
                return False
        if "before" not in self.state:
            self.state["before"] = self.summary_totals()
            self.save()
        self.event("preflight", "ok", f"xrd-stash* green; summary totals before the rebuild saved for "
                                      f"{len(self.state['before'])} months")
        return True

    def summary_totals(self) -> dict:
        body = {"size": 0, "query": {"range": {"@timestamp": {"gte": "2025-12-01T00:00:00Z", "lt": "2027-01-01T00:00:00Z"}}},
                "aggs": {"m": {"date_histogram": {"field": "@timestamp", "calendar_interval": "month"},
                               "aggs": {"n": {"sum": {"field": "transform._doc_count"}}, "r": {"sum": {"field": "read_sum"}}}}}}
        result = self.cluster.search("osdf-summary-2025,osdf-summary-2026", body, timeout=300)
        return {b["key_as_string"][:7]: {"records": int(b["n"]["value"]), "read": b["r"]["value"]}
                for b in result["aggregations"]["m"]["buckets"]}

    def retire(self, step: Step, st: dict) -> bool:
        existing = set(self.cluster.transform_ids())
        for tid in LIVE_TO_RETIRE:
            if tid not in existing:
                self.event(step.name, "absent", tid)
                continue
            self.cluster.stop(tid)
            code = self.cluster.delete(tid)
            if not 200 <= code < 300:
                self.event(step.name, "FAILED", f"delete {tid} returned HTTP {code}")
                st["status"] = "failed"
                return False
            self.event(step.name, "deleted", tid)
        st["status"] = "done"
        return True

    def install(self, step: Step, st: dict) -> bool:
        existing = set(self.cluster.transform_ids())
        installed = st.get("installed")
        # An interrupted step resumes waiting on what it installed; a failed one is installed again (--force)
        if st["status"] in ("installing", "running") and installed and all(job["id"] in existing for job in installed):
            self.event(step.name, "resume", "transforms already installed: " + ",".join(j["id"] for j in installed))
        else:
            st["status"] = "installing"
            st["install_started"] = utcnow()
            self.save()
            code, output = self.installer(step.installer_args, self.state_dir / f"installer-{step.name}.log")
            installed = parse_installed(output)
            st["installed"] = installed
            if code != 0 or not installed:
                self.event(step.name, "FAILED", f"installer exited {code}; see installer-{step.name}.log")
                st["status"] = "failed"
                return False
            self.event(step.name, "installed", ",".join(
                f"{j['id']}[{j['start']},{j['end']}){' live' if j['live'] else ''}" for j in installed))
        st["status"] = "running"
        self.save()
        for job in installed:
            if job["live"]:
                if job["id"] not in st.setdefault("live", []):
                    st["live"].append(job["id"])
                continue
            if job["id"] in st.get("verified", {}):
                continue
            if not self.wait_finished(step.name, job["id"]):
                st["status"] = "failed"
                return False
            result = self.verify(job)
            st.setdefault("verified", {})[job["id"]] = result
            self.save()
            if not result["ok"]:
                self.event(step.name, "VERIFY_FAILED", json.dumps(result))
                st["status"] = "failed"
                return False
            self.event(step.name, "verified", f"{job['id']}: {result['records']:,} records, "
                                              f"read {result['read'] / 1e15:.2f} PB{result.get('note', '')}")
        st["status"] = "done"
        st["finished"] = utcnow()
        return True

    def wait_green(self, step: str) -> bool:
        waited = 0
        while (health := self.cluster.health()) != "green":
            if waited % 3600 == 0:
                self.event(step, "waiting", f"xrd-stash* health is {health}")
            self.sleep(self.poll)
            waited += self.poll
            if waited > 24 * 3600:
                self.event(step, "FAILED", "xrd-stash* not green for 24 hours")
                return False
        return True

    def wait_finished(self, step: str, tid: str) -> bool:
        retries, last_stats, last_change, last_progress, stall_reported = 0, None, self.clock(), self.clock(), 0.0
        errors = 0
        while True:
            try:
                meta = self.cluster.explain(tid)
                errors = 0
            except (requests.RequestException, RuntimeError) as e:
                errors += 1
                if errors in (1, 10, 100):
                    self.event(step, "warning", f"_explain {tid} failed {errors}x: {e}")
                self.sleep(self.poll)
                continue
            status, stats = meta.get("status"), meta.get("stats")
            if status == "finished":
                self.event(step, "finished", f"{tid}: {stats.get('pages_processed')} pages, "
                                             f"{stats.get('documents_indexed'):,} rows")
                return True
            if status == "failed":
                reason = meta.get("failure_reason") or ""
                if "healthy" in reason and retries < MAX_HEALTH_RETRIES:
                    retries += 1
                    self.event(step, "retrying", f"{tid} failed ({reason}); restart {retries}/{MAX_HEALTH_RETRIES} "
                                                 f"once xrd-stash* is green")
                    if not self.wait_green(step):
                        return False
                    self.cluster.start(tid)
                    last_change = self.clock()
                    self.sleep(self.poll)
                    continue
                self.event(step, "FAILED", f"{tid}: {reason}")
                return False
            now = self.clock()
            if stats != last_stats:
                last_stats, last_change = stats, now
            elif now - last_change > STALL_AFTER_SECONDS and now - stall_reported > 3600:
                stall_reported = now
                self.event(step, "STALLED", f"{tid}: status {status}, no progress for "
                                            f"{(now - last_change) / 3600:.1f} h")
            if now - last_progress >= PROGRESS_EVERY_SECONDS:
                last_progress = now
                stats = stats or {}
                self.event(step, "progress", f"{tid}: status {status}, {stats.get('pages_processed', 0)} pages, "
                                             f"{stats.get('documents_indexed', 0):,} rows")
                self.check_live()
            self.sleep(self.poll)

    def verify(self, job: dict) -> dict:
        config = self.cluster.transform(job["id"])
        if config is None:
            return {"ok": False, "why": "transform not found"}
        src = self.cluster.search(config["source_index"], {
            "size": 0, "track_total_hits": True, "query": config["data_selection_query"],
            "aggs": {"read": {"sum": {"field": "read"}}}})
        tgt = self.cluster.search(config["target_index"], {
            "size": 0, "query": {"range": {"@timestamp": {"gte": job["start"], "lt": job["end"]}}},
            "aggs": {"t": {"terms": {"field": "transform._id.keyword", "size": 20},
                           "aggs": {"n": {"sum": {"field": "transform._doc_count"}}, "r": {"sum": {"field": "read_sum"}}}}}})
        by_id = {b["key"]: b for b in tgt["aggregations"]["t"]["buckets"]}
        mine = by_id.get(job["id"])
        records = int(mine["n"]["value"]) if mine else 0
        read = mine["r"]["value"] if mine else 0.0
        src_records, src_read = src["hits"]["total"]["value"], src["aggregations"]["read"]["value"]
        others = sorted(set(by_id) - {job["id"]})
        read_ok = abs(read - src_read) <= READ_TOLERANCE * max(abs(src_read), 1.0) + 1e6
        result = {"ok": records == src_records and read_ok and not others, "records": records,
                  "source_records": src_records, "read": read, "source_read": src_read, "other_transforms": others}
        # Records for a range that ended in the last few days can still arrive after the one-shot ran. A small
        # surplus in the source is late data, not a mismatch (TRANSFORMS.md, "Late data in the current month's one-shot").
        ended_recently = self.clock() - it.parse_timestamp(job["end"]).timestamp() < 3 * 86400
        late = src_records - records
        if not result["ok"] and ended_recently and not others and 0 < late <= LATE_TOLERANCE * src_records:
            result["ok"] = True
            result["note"] = (f" ({late:,} records arrived after the one-shot ran; re-create it in a day or two "
                              f"to include them)")
        month = job["start"][:7]
        if month in EXPECTED and job["start"][8:10] == "01":
            exp_records, exp_read = EXPECTED[month]
            if abs(records - exp_records) > 1e-3 * exp_records or abs(read - exp_read) > 0.01e15:
                result["note"] = f" (table of 2026-11-23 expected {exp_records:,} records, {exp_read / 1e15:.2f} PB)"
        return result

    def check_live(self, final: bool = False) -> None:
        """
        Check the live transforms this run created. One that failed because a source index was briefly unhealthy is
        restarted (up to MAX_HEALTH_RETRIES times over the run) once xrd-stash* is green; any other failure is
        reported, and the run carries on with its one-shots.
        """
        restarts = self.state.setdefault("live_restarts", {})
        for name, st in self.state["steps"].items():
            for tid in st.get("live", []):
                try:
                    meta = self.cluster.explain(tid)
                except (requests.RequestException, RuntimeError) as e:
                    self.event(name, "warning", f"live {tid}: {e}")
                    continue
                status, reason = meta.get("status"), meta.get("failure_reason") or ""
                if status == "failed" and "healthy" in reason and restarts.get(tid, 0) < MAX_HEALTH_RETRIES:
                    restarts[tid] = restarts.get(tid, 0) + 1
                    self.save()
                    self.event(name, "live-retrying", f"{tid} failed ({reason}); restart {restarts[tid]}/{MAX_HEALTH_RETRIES}")
                    if self.wait_green(name):
                        self.cluster.start(tid)
                elif status == "failed":
                    self.event(name, "LIVE_FAILED", f"{tid}: {reason}")
                elif final:
                    stats = meta.get("stats") or {}
                    self.event(name, "live-ok", f"{tid}: status {status}, {stats.get('documents_indexed', 0):,} rows so far")


def print_plan() -> None:
    today = datetime.now(timezone.utc).date()
    live_starts: dict[int, date] = {}
    print(f"Plan as of {today.isoformat()} (UTC); a run on a later day moves the November/live split to that day.\n")
    for n, step in enumerate(build_steps(), 1):
        if step.kind == "retire":
            print(f"{n:2d}. {step.name}: stop and delete {', '.join(LIVE_TO_RETIRE)}")
            continue
        def value(flag: str, default: int) -> int:
            a = step.installer_args
            return int(a[a.index(flag) + 1]) if flag in a else default
        ns = argparse.Namespace(start_year=value("--start-year", 0), end_year=value("--end-year", 0),
                                start_month=value("--start-month", 1), end_month=value("--end-month", 12))
        jobs = it.plan_jobs(ns, today, lambda year: live_starts.get(year))
        for job in jobs:
            if job.live:
                live_starts[job.year] = it.parse_timestamp(job.start).date()
        print(f"{n:2d}. {step.name}: install_transforms.py {' '.join(step.installer_args)}")
        for job in jobs:
            used, budget = it.clause_budget(it.create_transform_config(job))
            print(f"      {job.transform_id}  [{job.start}, {job.end}){'  live' if job.live else ''}  clauses: {budget}")


def print_status(cluster: Cluster, state_dir: Path) -> None:
    state_path = state_dir / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"steps": {}}
    print(f"xrd-stash* health: {cluster.health()}")
    for step in build_steps():
        st = state["steps"].get(step.name, {"status": "pending"})
        line = f"{step.name:14s} {st['status']:10s}"
        for job in st.get("installed", []):
            try:
                meta = cluster.explain(job["id"])
                stats = meta.get("stats") or {}
                line += (f"  {job['id']}: {meta.get('status')} {stats.get('pages_processed', 0)} pages "
                         f"{stats.get('documents_indexed', 0):,} rows")
                if meta.get("failure_reason"):
                    line += f" ({meta['failure_reason']})"
            except (requests.RequestException, RuntimeError) as e:
                line += f"  {job['id']}: {e}"
        for tid, v in st.get("verified", {}).items():
            line += f"  verified {tid}: {'OK' if v['ok'] else 'MISMATCH'} {v['records']:,} records {v['read'] / 1e15:.2f} PB"
        print(line)


def main() -> int:
    p = argparse.ArgumentParser(description="Drive and verify the Nov 2026 OSDF summary rebuild.")
    p.add_argument("command", choices=["plan", "status", "run"])
    p.add_argument("--url", help="OpenSearch base URL (status, run)")
    p.add_argument("--user", help="OpenSearch user (status, run); the password comes from $OPENSEARCH_PASSWORD")
    p.add_argument("--state-dir", type=Path, help="Where state.json, rebuild.log and installer logs live (status, run)")
    p.add_argument("--insecure", action="store_true", help="Do not verify TLS certificates")
    p.add_argument("--through", help="Stop after this step (e.g. 2027-live), to rebuild in stages")
    p.add_argument("--yes", action="store_true", help="Required for run: it deletes and recreates transforms")
    args = p.parse_args()

    if args.command == "plan":
        print_plan()
        return 0
    password = os.environ.get("OPENSEARCH_PASSWORD")
    if not (args.url and args.user and args.state_dir and password):
        print("Error: --url, --user, --state-dir and $OPENSEARCH_PASSWORD are required", file=sys.stderr)
        return 1
    steps = build_steps()
    if args.through and args.through not in {s.name for s in steps}:
        print(f"Error: --through must be one of {', '.join(s.name for s in steps)}", file=sys.stderr)
        return 1
    cluster = Cluster(args.url, args.user, password, verify=not args.insecure)
    if args.command == "status":
        print_status(cluster, args.state_dir)
        return 0
    if not args.yes:
        print("run deletes and recreates transforms and their summary rows; rerun with --yes to go ahead. "
              "The steps:\n", file=sys.stderr)
        print_plan()
        return 1
    args.state_dir.mkdir(parents=True, exist_ok=True)
    installer_args = ("--insecure",) if args.insecure else ()
    driver = Driver(cluster, args.state_dir,
                    lambda step_args, log: run_installer(args.url, args.user, step_args + installer_args, log))
    return driver.run(steps, through=args.through)


if __name__ == "__main__":
    raise SystemExit(main())
