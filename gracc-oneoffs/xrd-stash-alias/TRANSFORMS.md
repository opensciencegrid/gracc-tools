# OpenSearch Transform Jobs for OSDF Summary

This directory contains scripts and configurations for creating OpenSearch transform jobs that aggregate OSDF data into one summary index per year.

## Overview

The transform jobs replace the previous rollup approach with a more flexible transform-based solution.

- **Completed months** each get a one-shot transform (`osdf-summary-<year>-<MM>`).
- **The rest of the current year, from the day the installer runs (UTC),** gets one continuous "live" transform, `osdf-summary-<year>-from-<MM>-<DD>`, named for the day it starts on.
- **The days of the current month before that** get a one-shot of their own (`osdf-summary-<year>-<MM>`), which ends where the live transform starts.
- **A future year** gets one live transform from Jan 1 (`osdf-summary-<year>-from-01-01`), so next year's can be installed ahead of time (see [Installing next year ahead of time](#installing-next-year-ahead-of-time)).
- Once a live transform exists, the days from its start on belong to it, and the installer won't create one-shots for them.

Every transform:

- Processes data from `xrd-stash*` indices
- Filters data to its month (or, for a live transform, its start day through year end) using timestamp ranges
- Leaves out `/replicate:` pseudo-paths, close records with no matching open, and garbage byte counters (see [Excluded data](#excluded-data))
- Groups data by day and multiple dimension fields
- Calculates min, max, sum, avg, and count metrics for filesize, read, readv, and write fields
- Outputs to a year-specific index: `osdf-summary-<year>`

### Why monthly

A transform pages through its buckets with a composite aggregation. **Every page re-scans every document its query matches.**

The old single-year 2025 transform used 1,000-bucket pages. Each page read all 16B documents of 2025, which took 9–15 min, and it would have needed months to finish.

With a one-month query, OpenSearch skips most of the 1,100+ `xrd-stash*` shards before searching. Combined with 10,000-bucket pages, the whole of Sep–Dec 2025 was rebuilt in under two hours (Oct 2026).

### Why the live transform starts on install day

A continuous transform is far slower per summary row than a one-shot (from the OpenSearch 2.11 transform source):

- **Small pages.** It writes at most 100 buckets per page (its `page_size`), against up to 10,000 for a one-shot. See [Page Size](#page-size) for why.
- **Same cost per page.** A page still takes about as long as a one-shot page, about 2 minutes on the test cluster.
- **One shard at a time.** Its first pass walks the source shard by shard, through all 1,100+ `xrd-stash*` shards.
- **No partial progress.** It saves its progress only when a run finishes, so a failure part-way through the first pass starts it over.

The first live transform, `osdf-summary-2026-from-10`, was created on Oct 27 to cover Oct 1 on, so its first pass had four weeks of data. It wrote about 3,200 summary rows an hour, so its first pass would have taken days, and an HDD-node outage restarted it once. On Oct 29 it was replaced by a one-shot for Oct 1–28 and a live transform from Oct 29.

So the live transform starts on the day the installer runs, and its first pass has almost nothing to summarize. After that, each hourly run only revisits the shards that received new data.

### Late data in the current month's one-shot

The one-shot for the live transform's first month ends at midnight UTC on the install day, and it runs once. Records for those days that arrive after it has run are not summarized. To pick them up, re-create that one-shot a day or two later:

```bash
python install_transforms.py \
  --url https://your-opensearch-host:9200 \
  --user admin \
  --start-year 2026 --end-year 2026 \
  --start-month 10 --end-month 10 \
  --force
```

With a live transform in place, that month's only job is the one-shot, and the live transform is left alone. The re-created one-shot has the same ID, so it overwrites its own documents and `--clean-target` isn't needed.

## Files

- `example-transform.json` - Example transform configuration (older yearly format, for reference)
- `install_transforms.py` - Python script to install the transform jobs
- `rebuild_transforms.py` - Drives and verifies the Nov 2026 rebuild one transform at a time (see [Managed rebuild](#managed-rebuild-rebuild_transformspy))
- `install_rollup.py` - Legacy script for installing rollup jobs (for reference)
- `example-rollup.json` - Legacy rollup configuration (for reference)

## Installation

### Prerequisites

```bash
pip install -r requirements.txt
```

### Install All Transform Jobs (2019-2025)

```bash
export OPENSEARCH_PASSWORD=your-password
python install_transforms.py \
  --url https://your-opensearch-host:9200 \
  --user admin
```

### Options

```
--url, -u          Base URL of OpenSearch (required)
--user             Username for basic auth (required)
--password         Password for basic auth (default: $OPENSEARCH_PASSWORD)
--start-year       Start year (default: 2019)
--end-year         End year (default: 2025)
--start-month      First month to install in each year (default: 1)
--end-month        Last month to install in each year (default: 12)
--insecure         Skip TLS certificate verification
--no-start         Create the transforms disabled, without starting them
--force            Delete and recreate transforms that already exist
--clean-target     Delete the existing summary documents in each transform's date range before creating it
--dry-run          Only print which transforms would be installed; change nothing
--print-config     Print the transform configurations as JSON and their clause counts; contacts no OpenSearch
```

`--dry-run` still asks OpenSearch which live transforms exist, so it needs `--url` and credentials. `--print-config` needs neither (see [Check a configuration without OpenSearch](#check-a-configuration-without-opensearch)).

When a year is installed as monthly transforms, the installer stops and deletes that year's old single-year transform (`osdf-summary-<year>`), if one exists. Its documents stay in the target index.

With `--no-start`, the transforms are created disabled. Start them yourself with `_start`, a few at a time if the cluster is busy. Each running transform is a full-month scan per page.

### Check a Configuration Without OpenSearch

`--print-config` prints the exact body the installer would `PUT` for each transform, without contacting OpenSearch:

- **stdout:** one JSON object keyed by transform ID.
- **stderr:** one line per transform with its date range and its Lucene clause count (see [Page Size](#page-size)).

```bash
python install_transforms.py --print-config \
  --start-year 2026 --end-year 2026 --start-month 10 --end-month 10 \
  | jq '."osdf-summary-2026-10".transform.data_selection_query'
```

With no OpenSearch to ask, it plans as if no live transform existed yet. For the current year, it shows the live transform the installer would create today. It exits 1 if any transform is over the clause limit. The installer runs the same check before it changes anything.

### Install a Subset of Years or Months

```bash
python install_transforms.py \
  --url https://your-opensearch-host:9200 \
  --user admin \
  --start-year 2025 \
  --end-year 2025 \
  --start-month 9 \
  --end-month 12
```

### Rebuild Months That Were Already Summarized

Target document IDs are derived from the transform ID. A month first summarized by a different transform, such as the old yearly one, therefore keeps its old documents next to the new ones, and dashboards double count it. Pass `--clean-target` to delete that month's documents from the target index before its transform is created:

```bash
python install_transforms.py \
  --url https://your-opensearch-host:9200 \
  --user admin \
  --start-year 2025 --end-year 2025 \
  --start-month 9 --end-month 12 \
  --clean-target
```

Add `--force` as well if the monthly transforms themselves already exist and should be recreated.

`--clean-target` empties the whole range before the transform starts, so queries return far less data until it finishes. When the months were summarized by the **same transform IDs** (for example, after changing the exclusions), rebuild them in place instead:

1. Record the target index's highest `_seq_no`. Every `osdf-summary-<year>` index has one primary shard, so one number covers it:

   ```bash
   curl -s -u admin:password -H 'Content-Type: application/json' \
     "https://your-opensearch-host:9200/osdf-summary-2026/_search" \
     -d '{"size": 0, "aggs": {"m": {"max": {"field": "_seq_no"}}}}'
   ```

2. Recreate and start the transform with `--force`, without `--clean-target`. It writes the same document IDs, so each row is overwritten when the transform reaches its bucket, and the old rows stay readable until then.
3. When it has finished, delete the rows in its range that it did not rewrite: buckets that no longer exist, such as ones made up only of excluded records.

   ```bash
   curl -s -u admin:password -H 'Content-Type: application/json' \
     "https://your-opensearch-host:9200/osdf-summary-2026/_delete_by_query" \
     -d '{"query": {"bool": {"filter": [
           {"range": {"@timestamp": {"gte": "2026-07-01T00:00:00Z", "lt": "2026-08-01T00:00:00Z"}}},
           {"range": {"_seq_no": {"lte": SEQ_NO_FROM_STEP_1}}}]}}}'
   ```

While a month is being rebuilt, its totals mix rewritten rows and old ones, but nothing goes missing. Keep the date range in step 3: the other months' rows have older sequence numbers too.

The Oct 30 – Nov 2, 2026 rebuild ran this way, through a driver script that also checked each month against the source.

### Rebuilding After the Unmatched-Close Exclusion (Nov 2026)

The unmatched-close rule and the 100 TB cap (see [Excluded data](#excluded-data)) change every month from 2025-12 to 2026-10. Nothing from 2026-10-30 on is affected: the rule stops at 14:00 UTC on 2026-10-29, and no record since has a counter near 100 TB. This rebuild was run with `rebuild_transforms.py` from 2026-11-23 21:58 to 2026-11-24 14:20 UTC, and every month matched the table below exactly (see [Results](#results-2026-11-24)).

The live transforms have to go first:

- `osdf-summary-2026-from-10-30` and `osdf-summary-2027-from-01-01` carry the old query.
- Both have been `failed` since 2026-11-07, with "Cannot determine that the requested source indices are healthy". A failed transform doesn't retry, so nothing from Nov 7 on is summarized.
- While a live transform exists, the installer leaves its days alone. Without retiring it first, October's one-shot would stop at Oct 30, and November would stay unsummarized.

```bash
export OPENSEARCH_PASSWORD=...
OS=https://gracc.opensciencegrid.org/q

# 1. Retire both live transforms. Their documents stay in the target index.
for t in osdf-summary-2026-from-10-30 osdf-summary-2027-from-01-01; do
  curl -s -u "admin:$OPENSEARCH_PASSWORD" -X POST   "$OS/_plugins/_transform/$t/_stop"; echo
  curl -s -u "admin:$OPENSEARCH_PASSWORD" -X DELETE "$OS/_plugins/_transform/$t"; echo
done

# 2. December 2025
python install_transforms.py --url "$OS" --user admin \
  --start-year 2025 --end-year 2025 --start-month 12 --end-month 12 \
  --clean-target --force

# 3. 2026: one-shots for Jan through the day before today, and a new live transform from today
python install_transforms.py --url "$OS" --user admin \
  --start-year 2026 --end-year 2026 \
  --clean-target --force

# 4. 2027: a new live transform from Jan 1 (osdf-summary-2027 is still empty)
python install_transforms.py --url "$OS" --user admin \
  --start-year 2027 --end-year 2027
```

- In step 3, `--force` replaces the one-shots `osdf-summary-2026-01` to `-10`. `--clean-target` empties each range before its transform starts, which also removes the old live transform's rows for Oct 30 – Nov 7.
- Step 3 starts about a dozen transforms at once. To go easier on the cluster, run it one month at a time (`--start-month M --end-month M`), and wait for each `_explain` to say `finished`. Run month 11 last: `--start-month 11 --end-month 12` creates the November one-shot and the new live transform.
- Run `--print-config` with the same year and month options first, to see exactly what each step will install.
- To keep the old rows readable until they are replaced, use the in-place procedure above instead of `--clean-target`. Its final `_seq_no` cleanup is required here, because most "unknown directory" buckets disappear.

#### Managed rebuild (`rebuild_transforms.py`)

`rebuild_transforms.py` runs the same steps one transform at a time, and checks each one before going on. It is meant to run in the background with Claude (or a person) watching its log.

The order:

1. Retire both live transforms.
2. `2026-11+live`: the November one-shot and a new live transform. Current data comes back first.
3. `2027-live`.
4. `2026-10` back to `2025-12`, one month at a time.

Each install calls `install_transforms.py` with the options above, so it gets the installer's clause check and `--clean-target`. Each month's rows are gone from the summary only while its own transform runs.

Each one-shot is checked when it finishes:

- Its rows must be the only rows in its range.
- Their summed `transform._doc_count` must equal a fresh source count under the transform's own installed `data_selection_query`.
- Their summed `read_sum` must equal the source's summed `read`.
- If the month differs from the table below, the result carries a note.
- A range that ended in the last 3 days may be short by at most 0.1%, as late data.

On a check run against the existing `osdf-summary-2026-09`, target and source agreed exactly (3,013,389,121 records), in about 30 seconds.

Failures:

- A transform that fails with "Cannot determine that the requested source indices are healthy" is restarted, up to 3 times, once `xrd-stash*` is green. The live transforms are checked every 30 minutes as well.
- Any other failure, a failed check, or a transform with no progress for 2 hours stops the run, or reports `STALLED`.
- Rerunning resumes: finished steps are skipped, an interrupted step goes back to waiting, and a failed step is installed again.

State and logs go to `--state-dir`: `state.json`, `rebuild.log` with one `EVENT` line per milestone, and one installer log per step. Use a directory that survives a reboot, not `/tmp`. The password comes from `$OPENSEARCH_PASSWORD`, never the command line.

```bash
python rebuild_transforms.py plan                      # the steps and transforms; contacts no OpenSearch
python rebuild_transforms.py status --url "$OS" --user admin --state-dir DIR   # read-only snapshot
python rebuild_transforms.py run    --url "$OS" --user admin --state-dir DIR --yes [--through 2027-live]
```

`run` without `--yes` only prints the plan. `--through STEP` stops after that step, for rebuilding in stages.

A one-shot takes 15 minutes to 2.5 hours. In the Nov 2026 run they took 17 min (Feb 2026) to 2 h 18 min (Sep 2026), and all 12 one-shots finished 12 h 55 min after the run started. The new live transform's first pass runs alongside.

**When Claude manages it:**

1. **Launch.** Claude asks for keep-awake on the Mac and starts `run --yes` in the background, with the password taken from `run.sh` and never printed. It streams `rebuild.log` through a monitor that wakes it on these events: `installed`, `verified`, `retrying`, `live-retrying`, `waiting`, `warning`, `FAILED`, `VERIFY_FAILED`, `STALLED`, `LIVE_FAILED`, `STOPPED`, `paused`, `done`. It re-arms the monitor every 30 minutes.
2. **While it runs.** Claude posts a `status` snapshot every few hours. A `FAILED`, `VERIFY_FAILED`, `STALLED` or `LIVE_FAILED` event gets a read-only diagnosis: `status`, `_explain`, cluster health, and source against target.
3. **What Claude may do on its own:** rerun the driver after a transient cause, and `_start` a transform from this plan once the cluster is green.
4. **What needs the user's OK:** anything else, such as deleting other transforms, a `_delete_by_query` outside the installer, changing the rule, or changing cluster settings.
5. **At the end.** Claude compares each month with `state.json`'s before totals and with the table below, and records the result here. A day or two later, it re-creates the November one-shot for late records:

   ```bash
   install_transforms.py --start-year 2026 --end-year 2026 --start-month 11 --end-month 11 --force
   ```

   If the rebuild runs in December, the month in that command changes to 12.

When a month finishes, its summed `transform._doc_count` and `read_sum` in the target should match this table. The table comes from read-only queries on 2026-11-23 that mirror the new `data_selection_query`. October has no data for Oct 14–26 (see the note below the table).

| Month | Summary today: read (PB) | Records dropped | Read dropped (PB) | Expected records | Expected read (PB) | Expected readv (PB) | Expected write (PB) |
|---|---|---|---|---|---|---|---|
| 2025-12 | 39.26 | 886,972 | 13.90 | 1,908,162,379 | 25.36 | 0.530 | 0.283 |
| 2026-01 | 135.00 | 4,454,287 | 96.95 | 2,009,371,519 | 38.05 | 0.032 | 0.078 |
| 2026-02 | 164.02 | 3,038,782 | 125.62 | 2,332,561,513 | 38.40 | 0.021 | 0.016 |
| 2026-03 | 65.28 | 3,815,716 | 18.70 | 2,937,382,055 | 46.59 | 0.035 | 0.062 |
| 2026-04 | 8,424.39 | 2,606,542 | 8,391.42 | 2,082,545,965 | 32.97 | 0.120 | 0.046 |
| 2026-05 | 4,245.68 | 2,598,855 | 4,227.28 | 1,253,976,813 | 18.40 | 0.015 | 0.108 |
| 2026-06 | 240.35 | 1,315,285 | 230.97 | 558,662,285 | 9.38 | 0.002 | 0.068 |
| 2026-07 | 8,584.96 | 8,166,788 | 8,565.63 | 1,646,656,053 | 19.33 | 0.030 | 0.035 |
| 2026-08 | 38,901.19 | 8,864,082 | 38,868.40 | 2,474,599,886 | 32.79 | 0.038 | 0.204 |
| 2026-09 | 355.00 | 4,762,482 | 330.49 | 3,008,626,639 | 24.51 | 0.006 | 0.079 |
| 2026-10 | 215.23 | 1,299,184 | 199.09 | 1,549,212,020 | 16.14 | 0.019 | 0.007 |
| 2026-11 (1–22) | not summarized after Nov 7 | 0 | 0.00 | 1,076,167,359 | 21.68 | 0.212 | 0.051 |

How the table was computed:

- **"Summary today"** is `read_sum` in `osdf-summary-*` on 2026-11-23. For Oct 2026 and Dec 2025 it matches raw `xrd-stash` exactly, both in records and in bytes.
- **"Dropped"** counts what the new rule removes on top of the old one.
- **Expected**, Oct 2026: running the exact query `--print-config` generates for `osdf-summary-2026-10` gives the same row.
- **Expected**, Nov 2026: covers Nov 1–22 only. The rebuild's November one-shot ended at Nov 23, the day it ran, so it covers the same days.
- **The gap:** Oct 14–26 has no records in raw either. The rebuild can't fill it.

#### Results (2026-11-24)

`rebuild_transforms.py run` ran all 14 steps. Every one-shot's summed records and `read_sum` in the target equal the source under its installed query, and equal the expected table above exactly.

| Step | Transform | Time to finish | Pages | Target rows | Records | Read (PB) |
|---|---|---:|---:|---:|---:|---:|
| 2026-11+live | `osdf-summary-2026-11` (Nov 1–22) | 33 min | 19 | 170,557 | 1,076,167,359 | 21.68 |
| 2026-10 | `osdf-summary-2026-10` | 59 min | 17 | 151,995 | 1,549,212,020 | 16.14 |
| 2026-09 | `osdf-summary-2026-09` | 2 h 18 min | 25 | 235,794 | 3,008,626,639 | 24.51 |
| 2026-08 | `osdf-summary-2026-08` | 1 h 56 min | 30 | 286,633 | 2,474,599,886 | 32.79 |
| 2026-07 | `osdf-summary-2026-07` | 56 min | 23 | 217,477 | 1,646,656,053 | 19.33 |
| 2026-06 | `osdf-summary-2026-06` | 25 min | 12 | 104,106 | 558,662,285 | 9.38 |
| 2026-05 | `osdf-summary-2026-05` | 35 min | 25 | 239,917 | 1,253,976,813 | 18.40 |
| 2026-04 | `osdf-summary-2026-04` | 30 min | 17 | 158,244 | 2,082,545,965 | 32.97 |
| 2026-03 | `osdf-summary-2026-03` | 36 min | 7 | 55,047 | 2,937,382,055 | 46.59 |
| 2026-02 | `osdf-summary-2026-02` | 17 min | 6 | 43,028 | 2,332,561,513 | 38.40 |
| 2026-01 | `osdf-summary-2026-01` | 52 min | 6 | 48,849 | 2,009,371,519 | 38.05 |
| 2025-12 | `osdf-summary-2025-12` | 2 h 14 min | 10 | 89,177 | 1,908,162,379 | 25.36 |

- The live transforms `osdf-summary-2026-from-11-23` and `osdf-summary-2027-from-01-01` replaced the two failed ones. Both were `started` at the end of the run; the 2027 one has no rows yet, as expected.
- No transform failed and none needed a restart.
- The driver itself stopped once. December's transform finished at 10:53 UTC. Its source query for the check then hung until the connection was reset at 13:43, and the driver exited. Rerunning `run --yes` resumed at that check, which then took 2.5 minutes.
- Still to do: re-create `osdf-summary-2026-11` with `--force` a day or two later, to pick up late records for Nov 1–22.

To check a month after its transform finishes (the summary indices are readable anonymously):

```bash
curl -s -H 'Content-Type: application/json' "$OS/osdf-summary-2026/_search" -d '{"size": 0,
  "query": {"range": {"@timestamp": {"gte": "2026-10-01T00:00:00Z", "lt": "2026-11-01T00:00:00Z"}}},
  "aggs": {"records": {"sum": {"field": "transform._doc_count"}}, "read": {"sum": {"field": "read_sum"}}}}'
```

### Installing Next Year Ahead of Time

Run the installer for next year before it starts, and it creates one live transform from Jan 1 instead of monthly one-shots:

```bash
python install_transforms.py \
  --url https://your-opensearch-host:9200 \
  --user admin \
  --start-year 2027 --end-year 2027
```

This avoids a manual step in January and leaves no gap at the year boundary. Until Jan 1, the transform has nothing in range:

- Its first pass still visits every `xrd-stash*` shard once (the Oct 29, 2026 live transform's took about 2.5 hours, most of it on shards with nothing in range).
- Each hourly run then checks only the shards that received new data, and finds nothing.
- Its target index (`osdf-summary-<year>`) exists, empty, from install on.

`osdf-summary-2027-from-01-01` was installed this way on Oct 30, 2026.

### Skip TLS Verification (for development)

```bash
python install_transforms.py \
  --url https://localhost:9200 \
  --user admin \
  --insecure
```

## Transform Configuration

Each transform job includes:

### Grouping Dimensions
- `@timestamp` - Date histogram with 1-day calendar interval (UTC)
- `dirname1` - First directory component
- `dirname2` - Second directory component
- `logical_dirname` - Logical directory name
- `server` - Server identifier
- `server_hostname` - Server hostname
- `site` - Site identifier
- `user_domain` - User domain

### Metrics
For each of the following fields: `filesize`, `read`, `readv`, `write`
- `min` - Minimum value
- `max` - Maximum value
- `sum` - Total sum
- `avg` - Average value
- `count` - Value count
- `doc_count` - Document count per bucket (value_count on `@timestamp`)

### Page Size
One-shot transforms use `page_size` 10000, the largest a transform accepts. Fewer pages means fewer full scans of the source.

The live transform uses `page_size` 100. A continuous transform re-queries each page of changed buckets with one clause per group for every bucket, and adds the `data_selection_query` on top. All of that has to fit in Lucene's limit of 1024 clauses, and Lucene counts a range query as 2:

- OpenSearch sizes the page at min(`page_size`, 1024 / (groups + 1)), which is 113 buckets with our 8 groups. Each bucket costs 9 clauses (the day range is 2), so 113 buckets take 1017.
- The `data_selection_query` costs 15 to 20:
  - the `@timestamp` range (2)
  - the `/replicate:` prefix (1)
  - the six garbage-counter ranges (2 each)
  - the unmatched-close rule, for transforms that start before its cutoff (14:00 UTC on 2026-10-29):
    - 3 clauses: two keyword terms, and a term on the long `filesize`, which OpenSearch 2.11.1 runs as a one-point range costing 1
    - 2 more for its `@timestamp` bound, if the transform also ends after the cutoff
- A live transform starts after the cutoff, so its query costs 15. With `page_size` 100, the buckets take 900, and 900 + 15 = 915 leaves 109 to spare. The worst case, 900 + 20 = 920, would still fit.

Two earlier configurations bear out these counts:

- Before the garbage-counter exclusion, the query cost 3, and `page_size` 1000 (113 in practice) worked: 1017 + 3 = 1020.
- With the garbage-counter ranges, it cost 15: 1017 + 15 = 1032. The transform failed its first search that had data with `too_many_nested_clauses` ("Failed to search data in source indices").

`query_clauses` and `clause_budget` in `install_transforms.py` do this arithmetic. `--print-config` shows it for each transform, and the installer refuses to install a transform that is over the limit. The per-clause costs were read from a `profile: true` search on the cluster (OpenSearch 2.11.1, Lucene 9.7.0). A range rewrites to an `IndexOrDocValuesQuery`, which Lucene counts as 2.

After its first pass, the live transform only recomputes the buckets that new data touches.

### Excluded Data
Three kinds of source documents are left out through the transform's `data_selection_query`. They are dropped entirely, including from the record counts. The raw documents are unchanged.

#### `/replicate:` pseudo-paths

Documents whose `dirname1` starts with `/replicate:` are left out.

These are Purdue EOS replication requests (site `T2_US_Purdue_EOS`, Sep 2025 – Jan 2026: about 13M documents in 2025 and 2.2M in 2026). Each one has a unique `dirname1`/`dirname2` like `/replicate:0000ca0f`, so each becomes its own bucket. On 2025-09-12 alone that was 1.6M buckets, against a few thousand on a normal day. The prefixes are listed in `EXCLUDED_DIRNAME1_PREFIXES` in `install_transforms.py`.

#### Close records with no matching open

Documents from before 14:00 UTC on 2026-10-29 with all three of these values are left out (`UNMATCHED_CLOSE_VALUES` and `UNMATCHED_CLOSE_UNTIL` in `install_transforms.py`):

- `dirname1` "unknown directory"
- `filesize` 0
- `protocol` "unknown"

collector2 (xrootd-monitoring-shoveler) writes such a record for a file close whose file ID matches no open it has seen, and whose login it can't find either. It builds the record with filename "unknown" (`createStandaloneCloseRecord` in `collector/correlator.go`).

Before v2.4.0, collector2 also parsed t-stream (trace) packets with the f-stream record layout, and so made up file closes of this kind ([xrootd-monitoring-shoveler#100](https://github.com/opensciencegrid/xrootd-monitoring-shoveler/issues/100)). Their `read`, `readv` and `write` are garbage at every magnitude, from GB to 9.2e18. v2.4.0 was deployed on 2026-10-29 (tiger-osg-config commit 91aa5b227).

- They first appear in Dec 2025. The 18.2B records before it, back to 2020, include no "unknown directory" records at all.
- In Oct 2026 there were 1.30M of them among 1.55B records. They carried 198 PB of the month's 215 PB `read`, 521 PB of 521 PB `readv` and 204 PB of 205 PB `write`.
- The garbage-counter cap was 1 PB at the time, so it caught only the largest ones. That is how the Oct 2026 summary came to show 215 PB read instead of about 16 PB.

Two kinds of "unknown directory" record are kept.

**With a known protocol (`https`, `xroot`).** Here collector2 found the login through the close's user ID or a dict mapping, and these records look real:

- From Dec 2025 to Oct 2026 they carry 0.16–0.99 PB a month, in 0.07–6M records.
- In most months no single record reads more than 0.1 TB.
- A fabricated close can still match a real login, because dict IDs are small sequential numbers. 44 such records carried 16.7 PB between Dec 2025 and Oct 2026. The 100 TB cap below takes out all but 15 of them (53 TB, 43 TB of it in Aug 2026).

**From 14:00 UTC on 2026-10-29 on.** With the t-stream bug fixed, an unmatched close is a real transfer whose open the collector missed, mostly with protocol "unknown":

- 12k–118k a day, carrying 4–27 TB of `read` a day, about 2% of all reads.
- No single read over 0.72 TB, no `readv` over 21 GB, and about 0 `write`.
- Every one with `read` over 0 also has `read_operations` over 0.

Before the cutoff, real unmatched closes without a login are dropped along with the fabricated ones, because nothing tells them apart. At the post-fix rate, that is about 15 TB of real reads a day.

The cutoff comes from an hourly look at Oct 29:

- Fabricated closes arrive through the 12:00 UTC hour, with reads up to 8.2e18.
- From 13:00 on, no record has a counter over 1 TB.
- The 13:00 hour still has a burst of 7.7k records, a few with a nonzero `write`, as the collector restarted.
- From 14:00 on, the largest read is 56 GB.

The date limit works per transform:

- A transform that ends by the cutoff gets the rule as is.
- One that spans the cutoff (`osdf-summary-2026-10`) gets it with an `@timestamp` bound.
- One that starts at or after the cutoff, such as a live transform, doesn't get it at all.

See [Rebuilding after the unmatched-close exclusion](#rebuilding-after-the-unmatched-close-exclusion-nov-2026) for what this changes in each month.

#### Garbage transfer counters

Documents with any of `read`, `readv` or `write` negative or over 100 TB are left out (`TRANSFER_FIELDS` and `MAX_TRANSFER_BYTES` in `install_transforms.py`).

A fabricated close that matched a real login, or the file ID of a real open, picks up a protocol or a real path, so only its counters give it away. From Dec 2025 to Oct 2026, the rule above misses 75 records over 100 TB. Their `read` adds up to 34.8 PB, 22.5 PB of it in Aug 2026, and nearly all of them have `read_operations` 0.

No record before Dec 2025 has a counter over 9.4 TB (the largest, in 2024). The largest in Jan–Nov 2025 is 1.4 TB, and the largest in Nov 2026 is 0.17 TB.

History of this rule:

- **Until Nov 2026, the cap was 1 PB.** It caught 323,597 records from Dec 2025 to Oct 2026, which were rebuilt with it from Oct 30 to Nov 2, 2026. Every month's summed `transform._doc_count` matched the source count afterward.
- Of those 323,597, 99.5% are closes with no matching open, and most come from servers reporting as 127.0.0.1. The worst site was FDP_OSDF_ORIGIN.
- A single one adds up to 9.2 EB to a day's summed bytes, and the negative ones subtract.
- Since 2026-10-29, the xrd-stash logstash pipeline drops records that are negative or over 1 PB before they are indexed.

### Scheduling
- The **live transform** (`osdf-summary-<year>-from-<MM>-<DD>`) runs in **continuous mode** every 1 hour, processing new data as it arrives
- **Monthly** transforms run as **one-shot** jobs that process their month once and then stop (status `finished`, job disabled)
- All transforms process historical data when first created
- **After the year ends**, the live transform still owns its days, and keeps running hourly with nothing new in range. Next year's live transform covers the new year, whether it was installed ahead of time or is installed after Jan 1. To turn the old one's days into one-shots:
  1. Stop and delete the old live transform.
  2. Re-run the installer for that year with `--clean-target --force`. `--force` replaces the partial one-shot of the month the live transform started in with a full-month one.

## Differences from Rollup

1. **Year-based Target Indices**: Each year has its own target index, filled by that year's monthly (or continuous) transforms
2. **Date Range Filtering**: Each transform only processes data from its specific month or year
3. **Calendar Interval**: Buckets are calendar days in UTC
4. **Explicit Aggregations**: Each metric is explicitly named (e.g., `filesize_min`, `filesize_max`)

## Managing Transform Jobs

### Check Transform Status

```bash
curl -X GET "https://your-opensearch-host:9200/_plugins/_transform/osdf-summary-2025-09/_explain" \
  -u admin:password
```

`transform_metadata.status` is `init`, `started`, `finished` or `failed`. A job that is disabled (`enabled: false` on `GET _plugins/_transform/<id>`) but whose status is still `started` is stuck: it will not run again and does not show as failed. This is how the old yearly 2025 transform sat idle from May to Oct 2026. Start it again with `_start`.

A `failed` transform does not retry either. Both live transforms failed on 2026-11-07 with `Failed validation - [Cannot determine that the requested source indices are healthy]`, which means an `xrd-stash*` index was briefly unhealthy. Nothing after that was summarized: as of 2026-11-23 they are still `failed`, with the cluster green. Once `_cluster/health/xrd-stash*` is green again, `_start` brings a failed transform back. Check the live transform's `_explain` after any cluster incident.

### Stop a Transform

```bash
curl -X POST "https://your-opensearch-host:9200/_plugins/_transform/osdf-summary-2025-09/_stop" \
  -u admin:password
```

### Start a Transform

```bash
curl -X POST "https://your-opensearch-host:9200/_plugins/_transform/osdf-summary-2025-09/_start" \
  -u admin:password
```

### Delete a Transform

```bash
curl -X DELETE "https://your-opensearch-host:9200/_plugins/_transform/osdf-summary-2025-09" \
  -u admin:password
```

## Troubleshooting

### View Transform Logs

Check OpenSearch logs for transform-related errors:

```bash
# On the OpenSearch server
tail -f /var/log/opensearch/opensearch.log | grep transform
```

### Check Transform Statistics

```bash
curl -X GET "https://your-opensearch-host:9200/_plugins/_transform/osdf-summary-2025-09/_explain" \
  -u admin:password
```

### Verify Target Index

```bash
curl -X GET "https://your-opensearch-host:9200/osdf-summary-2025/_count" \
  -u admin:password
```

To check a month is complete, compare the sum of `transform._doc_count` in the target for that month with a `_count` of the source using the same query as the transform. They should be equal.

## Notes

- The live transform runs continuously and processes new data every hour
- Historical data is processed when the transform is first created
- Each transform only processes data from its designated month (or, for the live transform, from its start day to year end)
- Target indices are automatically created if they don't exist
