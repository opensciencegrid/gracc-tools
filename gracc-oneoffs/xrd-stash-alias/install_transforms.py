#!/usr/bin/env python3
"""
install_transforms.py

Install OpenSearch transform jobs for OSDF summary data.

Usage: python install_transforms.py --url https://opensearch:9200 --user admin --password secret [--insecure]
       [--start-year 2019] [--end-year 2025] [--start-month 1] [--end-month 12] [--clean-target] [--dry-run]
       python install_transforms.py --print-config [--start-year ...] [--end-year ...] [--start-month ...] [...]

Every completed month gets a one-shot transform (osdf-summary-<year>-<MM>). The rest of the current year,
from today (UTC) on, gets one continuous "live" transform (osdf-summary-<year>-from-<MM>-<DD>), and the days
of the current month before today get a one-shot that ends where the live transform starts. A future year
gets one live transform from Jan 1 (osdf-summary-<year>-from-01-01), so it can be installed ahead of time.
Once a live transform exists, the days from its start on belong to it. Every transform will:
- Process data from xrd-stash* for its month (or, for a live transform, from its start day to year end)
- Output to osdf-summary-<year>
- Group by day and various dimension fields
- Calculate min, max, sum, avg, and count metrics for filesize, read, readv, and write fields

A transform re-scans every document matched by its query for each page of buckets, so the query is kept
to one month and pages are as large as transforms allow. A continuous transform writes far fewer buckets
per page, so the live transform starts on install day, with almost nothing to summarize in its first pass.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth


# Maximum page size a transform accepts; fewer pages means fewer full scans of the source data.
# A continuous transform re-queries each page of changed buckets with one clause per group per bucket,
# min(page_size, 1024 / (groups + 1)) = 113 buckets here. Lucene counts a range as 2 clauses, so those
# buckets take 113 * 9 = 1017 of Lucene's 1024, leaving too few for the data_selection_query (15 to 20, see
# query_clauses): it fails with too_many_nested_clauses. 100 buckets per page leaves room.
PAGE_SIZE = 10000
CONTINUOUS_PAGE_SIZE = 100

# Lucene's limit on the clauses in one query, counted over the whole query tree (too_many_nested_clauses).
MAX_NESTED_CLAUSES = 1024

# Pseudo-paths such as "/replicate:0000ca0f" (Purdue EOS replication, Sep 2025 - Jan 2026) give every
# request its own dirname1/dirname2 value, and so its own bucket (1.6M buckets on 2025-09-12 alone).
EXCLUDED_DIRNAME1_PREFIXES = ["/replicate:"]

# Close records with no matching open and no known login: collector2 writes a close whose file ID matches no
# open it saw with filename "unknown", so dirname1 "unknown directory", and filesize 0; protocol is "unknown"
# when it cannot find the login either. Before v2.4.0 (deployed 2026-10-29) it also parsed t-stream (trace)
# packets with the f-stream layout (xrootd-monitoring-shoveler issue #100), fabricating such closes with
# read/readv/write garbage at every magnitude, from GB to 9.2e18 (Oct 2026: 1.30M of 1.55B records, carrying
# 198 PB of the 215 PB read). There are none in the 18.2B records before Dec 2025.
# Kept: the same closes with a known protocol (0.16 - 0.99 PB a month, nearly all under 0.1 TB each; the few
# fabricated ones among them are mostly over MAX_TRANSFER_BYTES), and everything from UNMATCHED_CLOSE_UNTIL on.
# The last fabricated closes are in the 12:00 UTC hour of 2026-10-29, as v2.4.0 rolled out; the 13:00 hour still
# has a restart burst. From 14:00 on they are real closes whose open the collector missed (every one with
# read > 0 has read_operations > 0, none reads over 0.72 TB, about 15 TB a day in Nov 2026).
UNMATCHED_CLOSE_VALUES = {"dirname1.keyword": "unknown directory", "filesize": 0, "protocol.keyword": "unknown"}
UNMATCHED_CLOSE_UNTIL = "2026-10-29T14:00:00Z"

# Any other record with a garbage transfer counter: any of these fields negative or over 100 TB. A single one
# swamps a day's summed bytes. A fabricated close that matched a real login or a real open carries a protocol
# or a real path, so only its counter gives it away (Aug 2026: 44 such "unknown directory" records with
# protocol https carried 16.7 PB, and 19 with a real path 7.8 PB). No record before Dec 2025 has a counter
# over 9.4 TB.
TRANSFER_FIELDS = ["read", "readv", "write"]
MAX_TRANSFER_BYTES = 10**14


def month_range(year: int, month: int) -> tuple[str, str]:
    """
    Return the [start, end) @timestamp bounds of a calendar month, in UTC.
    """
    start = f"{year}-{month:02d}-01T00:00:00Z"
    if month == 12:
        end = f"{year + 1}-01-01T00:00:00Z"
    else:
        end = f"{year}-{month + 1:02d}-01T00:00:00Z"
    return start, end


def parse_timestamp(timestamp: str) -> datetime:
    """
    Parse an @timestamp bound such as "2026-10-29T14:00:00Z".
    """
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def unmatched_close_clauses(start: str, end: str) -> list[dict]:
    """
    The must_not clause for close records with no matching open, for a query over [start, end). It applies
    only before UNMATCHED_CLOSE_UNTIL, so a range that straddles that day gets a time bound, and a range
    that starts on or after it gets no clause at all.
    """
    until = parse_timestamp(UNMATCHED_CLOSE_UNTIL)
    if parse_timestamp(start) >= until:
        return []
    match = [{"term": {field: value}} for field, value in UNMATCHED_CLOSE_VALUES.items()]
    if parse_timestamp(end) > until:
        match.append({"range": {"@timestamp": {"lt": UNMATCHED_CLOSE_UNTIL}}})
    return [{"bool": {"filter": match}}]


def build_data_selection_query(start: str, end: str) -> dict:
    """
    Select source documents in [start, end), leaving out the excluded dirname1 prefixes, the close records
    with no matching open from before UNMATCHED_CLOSE_UNTIL, and the records with a garbage transfer counter.
    """
    return {
        "bool": {
            "filter": [
                {"range": {"@timestamp": {"gte": start, "lt": end}}}
            ],
            "must_not": [
                {"prefix": {"dirname1.keyword": prefix}} for prefix in EXCLUDED_DIRNAME1_PREFIXES
            ] + unmatched_close_clauses(start, end) + [
                {"range": {field: bound}} for field in TRANSFER_FIELDS
                for bound in ({"lt": 0}, {"gt": MAX_TRANSFER_BYTES})
            ]
        }
    }


def query_clauses(query: dict) -> int:
    """
    Count the Lucene clauses a query adds toward MAX_NESTED_CLAUSES, as OpenSearch 2.11.1 rewrites it:
    a range on a date or number is an IndexOrDocValuesQuery (2), a term (on a keyword or a long) or a
    prefix is 1, and a bool is the sum of its clauses.
    """
    (kind, body), = query.items()
    if kind == "bool":
        return sum(query_clauses(clause) for occur in ("filter", "must", "must_not", "should")
                   for clause in body.get(occur, []))
    if kind == "range":
        return 2
    if kind in ("term", "prefix"):
        return 1
    raise ValueError(f"no clause count known for a {kind} query; add it to query_clauses")


def continuous_page_clauses(config: dict) -> int:
    """
    Clauses a continuous transform's per-bucket filter takes for one page of changed buckets:
    min(page_size, 1024 / (groups + 1)) buckets, each a range for the day (2) and a term per other group (1).
    """
    transform = config["transform"]
    groups = transform["groups"]
    buckets = min(transform["page_size"], MAX_NESTED_CLAUSES // (len(groups) + 1))
    return buckets * sum(2 if "date_histogram" in group else 1 for group in groups)


def clause_budget(config: dict) -> tuple[int, str]:
    """
    Return (clauses used, description) for a transform configuration. Only a continuous transform adds the
    per-bucket clauses; a one-shot pages with a composite aggregation and uses just its data_selection_query.
    """
    query = query_clauses(config["transform"]["data_selection_query"])
    if not config["transform"]["continuous"]:
        return query, f"data_selection_query {query} of {MAX_NESTED_CLAUSES}"
    page = continuous_page_clauses(config)
    return page + query, f"page {page} + data_selection_query {query} = {page + query} of {MAX_NESTED_CLAUSES}"


def day_start(day: date) -> str:
    """
    Return the @timestamp of the start of a day, in UTC.
    """
    return f"{day.isoformat()}T00:00:00Z"


def live_transform_id(start: date) -> str:
    """
    ID of the continuous transform that covers a year from the given day on.
    """
    return f"osdf-summary-{start.year}-from-{start.month:02d}-{start.day:02d}"


@dataclass(frozen=True)
class Job:
    """
    One transform to install, covering @timestamp in [start, end).
    """
    transform_id: str
    year: int
    start: str
    end: str
    live: bool
    description: str


def month_job(year: int, month: int, live_start: Optional[date] = None) -> Job:
    """
    One-shot transform for a month, ending early if the year's live transform starts within the month.
    """
    start, end = month_range(year, month)
    description = f"OSDF summary transform for {year}-{month:02d}"
    if live_start is not None and (live_start.year, live_start.month) == (year, month):
        end = day_start(live_start)
        description += f" before {live_start.isoformat()}"
    return Job(f"osdf-summary-{year}-{month:02d}", year, start, end, False, description)


def live_job(start: date) -> Job:
    """
    Continuous transform from the given day through the end of its year.
    """
    return Job(live_transform_id(start), start.year, day_start(start), f"{start.year + 1}-01-01T00:00:00Z", True,
               f"OSDF summary transform for {start.isoformat()} through the end of {start.year} (continuous)")


def create_transform_config(job: Job, enabled: bool = True) -> dict:
    """
    Create the transform configuration for a job.

    Args:
        job: The transform to configure
        enabled: Whether the transform starts running as soon as it is created

    Returns:
        The transform configuration
    """
    start, end, description, continuous = job.start, job.end, job.description, job.live

    # Set schedule based on whether transform is continuous
    schedule_period = 1
    schedule_unit = "Hours" if continuous else "Minutes"

    config = {
        "transform": {
            "continuous": continuous,
            "enabled": enabled,
            "schedule": {
                "interval": {
                    "period": schedule_period,
                    "unit": schedule_unit
                }
            },
            "description": description,
            "source_index": "xrd-stash*",
            "target_index": f"osdf-summary-{job.year}",
            "data_selection_query": build_data_selection_query(start, end),
            "page_size": CONTINUOUS_PAGE_SIZE if continuous else PAGE_SIZE,
            "groups": [
                {
                    "date_histogram": {
                        "source_field": "@timestamp",
                        "calendar_interval": "1d",
                        "timezone": "UTC",
                        "target_field": "@timestamp"
                    }
                },
                {
                    "terms": {
                        "source_field": "dirname1.keyword",
                        "target_field": "dirname1"
                    }
                },
                {
                    "terms": {
                        "source_field": "dirname2.keyword",
                        "target_field": "dirname2"
                    }
                },
                {
                    "terms": {
                        "source_field": "logical_dirname.keyword",
                        "target_field": "logical_dirname"
                    }
                },
                {
                    "terms": {
                        "source_field": "server.keyword",
                        "target_field": "server"
                    }
                },
                {
                    "terms": {
                        "source_field": "server_hostname.keyword",
                        "target_field": "server_hostname"
                    }
                },
                {
                    "terms": {
                        "source_field": "site.keyword",
                        "target_field": "site"
                    }
                },
                {
                    "terms": {
                        "source_field": "user_domain.keyword",
                        "target_field": "user_domain"
                    }
                }
            ],
            "aggregations": {}
        }
    }
    
    # Add metrics for each field
    metrics_fields = ["filesize", "read", "readv", "write"]
    for field in metrics_fields:
        for metric in ["min", "max", "sum", "avg"]:
            config["transform"]["aggregations"][f"{field}_{metric}"] = {
                metric: {
                    "field": field
                }
            }
        # Add value_count
        config["transform"]["aggregations"][f"{field}_count"] = {
            "value_count": {
                "field": field
            }
        }

    # Add document count per bucket (equivalent to doc_count)
    config["transform"]["aggregations"]["doc_count"] = {
        "value_count": {
            "field": "@timestamp"
        }
    }
    
    return config


def check_transform_exists(
    base_url: str,
    transform_id: str,
    auth: HTTPBasicAuth,
    verify: bool = True
) -> bool:
    """
    Check if a transform job already exists in OpenSearch.
    
    Args:
        base_url: Base URL of OpenSearch
        transform_id: The transform job ID
        auth: HTTP basic authentication
        verify: Whether to verify TLS certificates
        
    Returns:
        True if the transform exists, False otherwise
    """
    endpoint = base_url.rstrip('/') + '/_plugins/_transform/' + transform_id
    headers = {'Content-Type': 'application/json'}
    try:
        resp = requests.get(endpoint, auth=auth, headers=headers, verify=verify, timeout=30)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def get_transform_details(
    base_url: str,
    transform_id: str,
    auth: HTTPBasicAuth,
    verify: bool = True
) -> Optional[dict]:
    """
    Get the details of a transform job from OpenSearch.
    
    Args:
        base_url: Base URL of OpenSearch
        transform_id: The transform job ID
        auth: HTTP basic authentication
        verify: Whether to verify TLS certificates
        
    Returns:
        The transform details as a dict, or None if not found or error
    """
    endpoint = base_url.rstrip('/') + '/_plugins/_transform/' + transform_id
    headers = {'Content-Type': 'application/json'}
    try:
        resp = requests.get(endpoint, auth=auth, headers=headers, verify=verify, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        return None
    except (requests.RequestException, json.JSONDecodeError):
        return None


def delete_transform(
    base_url: str,
    transform_id: str,
    auth: HTTPBasicAuth,
    verify: bool = True
) -> requests.Response:
    """
    Delete a transform job from OpenSearch.
    
    Args:
        base_url: Base URL of OpenSearch
        transform_id: The transform job ID
        auth: HTTP basic authentication
        verify: Whether to verify TLS certificates
        
    Returns:
        The HTTP response
    """
    endpoint = base_url.rstrip('/') + '/_plugins/_transform/' + transform_id
    headers = {'Content-Type': 'application/json'}
    resp = requests.delete(endpoint, auth=auth, headers=headers, verify=verify, timeout=60)
    return resp


def install_transform(
    base_url: str,
    transform_id: str,
    body: dict,
    auth: HTTPBasicAuth,
    verify: bool = True
) -> requests.Response:
    """
    Install a transform job in OpenSearch.
    
    Args:
        base_url: Base URL of OpenSearch
        transform_id: The transform job ID
        body: The transform configuration
        auth: HTTP basic authentication
        verify: Whether to verify TLS certificates
        
    Returns:
        The HTTP response
    """
    endpoint = base_url.rstrip('/') + '/_plugins/_transform/' + transform_id
    headers = {'Content-Type': 'application/json'}
    resp = requests.put(endpoint, json=body, auth=auth, headers=headers, verify=verify, timeout=60)
    return resp


def start_transform(
    base_url: str,
    transform_id: str,
    auth: HTTPBasicAuth,
    verify: bool = True
) -> requests.Response:
    """
    Start a transform job in OpenSearch.
    
    Args:
        base_url: Base URL of OpenSearch
        transform_id: The transform job ID
        auth: HTTP basic authentication
        verify: Whether to verify TLS certificates
        
    Returns:
        The HTTP response
    """
    endpoint = base_url.rstrip('/') + '/_plugins/_transform/' + transform_id + '/_start'
    headers = {'Content-Type': 'application/json'}
    resp = requests.post(endpoint, auth=auth, headers=headers, verify=verify, timeout=60)
    return resp


def stop_transform(
    base_url: str,
    transform_id: str,
    auth: HTTPBasicAuth,
    verify: bool = True
) -> requests.Response:
    endpoint = base_url.rstrip('/') + '/_plugins/_transform/' + transform_id + '/_stop'
    headers = {'Content-Type': 'application/json'}
    resp = requests.post(endpoint, auth=auth, headers=headers, verify=verify, timeout=60)
    return resp


def find_live_transform_start(
    base_url: str,
    year: int,
    auth: HTTPBasicAuth,
    verify: bool = True
) -> Optional[date]:
    """
    Return the start day of the year's live transform (osdf-summary-<year>-from-<MM>-<DD>), or None.

    Raises:
        requests.RequestException if the transforms cannot be listed
    """
    endpoint = base_url.rstrip('/') + '/_plugins/_transform'
    headers = {'Content-Type': 'application/json'}
    resp = requests.get(endpoint, params={'size': 1000}, auth=auth, headers=headers, verify=verify, timeout=30)
    resp.raise_for_status()
    pattern = re.compile(rf"osdf-summary-{year}-from-(\d\d)-(\d\d)")
    starts = [date(year, int(m[1]), int(m[2])) for t in resp.json().get('transforms', [])
              if (m := pattern.fullmatch(t['_id']))]
    return min(starts) if starts else None


def retire_yearly_transform(
    base_url: str,
    year: int,
    auth: HTTPBasicAuth,
    verify: bool = True
) -> tuple[bool, Optional[str]]:
    """
    Stop and delete the old single-year transform for a year that is moving to monthly transforms.
    Its documents stay in the target index.

    Returns:
        (True, None) if it was removed or never existed, (False, reason) on failure
    """
    transform_id = f"osdf-summary-{year}"
    if not check_transform_exists(base_url, transform_id, auth, verify):
        return True, None

    print(f"Retiring yearly transform {transform_id} (replaced by monthly transforms)...")
    try:
        stop_resp = stop_transform(base_url, transform_id, auth, verify)
        if not 200 <= stop_resp.status_code < 300:
            print(f"⚠ Stop returned {stop_resp.status_code} — proceeding with delete anyway.")
        del_resp = delete_transform(base_url, transform_id, auth, verify)
    except requests.RequestException as e:
        return False, f"request failed: {e}"
    if not 200 <= del_resp.status_code < 300:
        return False, f"delete returned HTTP {del_resp.status_code}: {del_resp.text.strip()}"
    print(f"✓ Deleted yearly transform {transform_id}")
    return True, None


def clean_target_range(
    base_url: str,
    index_name: str,
    start: str,
    end: str,
    auth: HTTPBasicAuth,
    verify: bool = True
) -> tuple[bool, str]:
    """
    Delete summary documents with @timestamp in [start, end) from the target index, and wait for it.

    Target document IDs are derived from the transform ID, so documents written by a different
    transform (e.g. the old yearly one) are not overwritten and would be double counted.

    Returns:
        (True, message) on success, (False, reason) on failure
    """
    headers = {'Content-Type': 'application/json'}
    endpoint = (base_url.rstrip('/') + '/' + index_name +
                '/_delete_by_query?conflicts=proceed&slices=auto&wait_for_completion=false')
    body = {"query": {"range": {"@timestamp": {"gte": start, "lt": end}}}}
    try:
        resp = requests.post(endpoint, json=body, auth=auth, headers=headers, verify=verify, timeout=60)
    except requests.RequestException as e:
        return False, f"delete_by_query request failed: {e}"
    if resp.status_code == 404:
        return True, "target index does not exist yet"
    if not 200 <= resp.status_code < 300:
        return False, f"delete_by_query returned HTTP {resp.status_code}: {resp.text.strip()}"

    task_id = resp.json()["task"]
    task_endpoint = base_url.rstrip('/') + '/_tasks/' + task_id
    while True:
        time.sleep(5)
        try:
            task = requests.get(task_endpoint, auth=auth, headers=headers, verify=verify, timeout=30).json()
        except (requests.RequestException, json.JSONDecodeError):
            continue
        if not task.get("completed"):
            continue
        result = task.get("response", {})
        if task.get("error") or result.get("failures"):
            return False, f"delete_by_query failed: {json.dumps(task.get('error') or result.get('failures'))}"
        return True, f"deleted {result.get('deleted', 0)} documents"


def ensure_target_index(base_url: str, index_name: str, auth: HTTPBasicAuth, verify: bool = True) -> tuple[bool, Optional[str]]:
    """
    Ensure the target index exists and has @timestamp mapped as a date.
    Returns (True, None) on success, (False, reason) on failure.
    """
    endpoint = base_url.rstrip('/') + '/' + index_name
    headers = {'Content-Type': 'application/json'}
    try:
        head = requests.head(endpoint, auth=auth, headers=headers, verify=verify, timeout=10)
    except requests.RequestException as e:
        return False, f"HEAD request failed: {e}"

    if head.status_code == 200:
        # Index exists, do not modify mappings
        return True, None

    # Create index with minimal mapping that defines @timestamp as date so index-pattern can detect it
    mapping_body = {
        "mappings": {
            "properties": {
                "@timestamp": {"type": "date"},
                # keep common group fields as keywords so they appear correctly in the target index
                "dirname1": {"type": "keyword"},
                "dirname2": {"type": "keyword"},
                "logical_dirname": {"type": "keyword"},
                "server": {"type": "keyword"},
                "server_hostname": {"type": "keyword"},
                "site": {"type": "keyword"},
                "user_domain": {"type": "keyword"},
                # Aggregated metric fields - use double for better precision
                "filesize_min": {"type": "double"},
                "filesize_max": {"type": "double"},
                "filesize_sum": {"type": "double"},
                "filesize_avg": {"type": "double"},
                "read_min": {"type": "double"},
                "read_max": {"type": "double"},
                "read_sum": {"type": "double"},
                "read_avg": {"type": "double"},
                "readv_min": {"type": "double"},
                "readv_max": {"type": "double"},
                "readv_sum": {"type": "double"},
                "readv_avg": {"type": "double"},
                "write_min": {"type": "double"},
                "write_max": {"type": "double"},
                "write_sum": {"type": "double"},
                "write_avg": {"type": "double"}
            }
        }
    }

    try:
        put = requests.put(endpoint, json=mapping_body, auth=auth, headers=headers, verify=verify, timeout=30)
    except requests.RequestException as e:
        return False, f"PUT request failed: {e}"

    if put.status_code in (200, 201):
        return True, None

    # return failure with response text if available
    reason = f"HTTP {put.status_code} {put.reason}"
    try:
        body = put.text.strip()
        if body:
            reason += f": {body}"
    except Exception:
        pass
    return False, reason


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Install OpenSearch transform jobs for OSDF summary data.')
    p.add_argument('--url', '-u', help='Base URL of OpenSearch (e.g. https://opensearch.example:9200); '
                                       'required unless --print-config')
    p.add_argument('--user', help='Username for basic auth; required unless --print-config')
    p.add_argument('--password', default=os.environ.get('OPENSEARCH_PASSWORD'),
                   help='Password for basic auth (default: $OPENSEARCH_PASSWORD)')
    p.add_argument('--start-year', type=int, default=2019, help='Start year (default: 2019)')
    p.add_argument('--end-year', type=int, default=2025, help='End year (default: 2025)')
    p.add_argument('--start-month', type=int, default=1, help='First month to install in each year (default: 1)')
    p.add_argument('--end-month', type=int, default=12, help='Last month to install in each year (default: 12)')
    p.add_argument('--insecure', action='store_true', help='Do not verify TLS certificates')
    p.add_argument('--no-start', action='store_true', help='Create the transforms disabled, without starting them')
    p.add_argument('--force', action='store_true', help='Delete and recreate transforms that already exist')
    p.add_argument('--clean-target', action='store_true',
                   help='Before creating each transform, delete the existing documents in its date range from '
                        'the target index (required when the range was summarized by a different transform)')
    p.add_argument('--dry-run', action='store_true',
                   help='Only print which transforms would be installed; change nothing')
    p.add_argument('--print-config', action='store_true',
                   help='Print the configuration of each transform that would be installed, as JSON on stdout, '
                        'and its clause count on stderr, without contacting OpenSearch. With no OpenSearch to '
                        'ask, it plans as if no live transform existed yet.')
    return p.parse_args()


def plan_jobs(args: argparse.Namespace, today: date, existing_live_start) -> list[Job]:
    """
    List the transforms to install. existing_live_start(year) returns the start day of the year's live
    transform, or None if it has none.

    Completed months are one-shots; the current year from today on is one live transform, and the current
    month's days before today are a one-shot that ends where it starts. A future year is one live transform
    from Jan 1. Days at or after an existing live transform's start belong to it, so they get no one-shot.
    """
    jobs = []
    for year in range(args.start_year, args.end_year + 1):
        live_start = existing_live_start(year)
        if live_start is not None:
            print(f"ℹ {year}: {live_start.isoformat()} on belongs to live transform {live_transform_id(live_start)}")
        elif year >= today.year:
            live_start = max(today, date(year, 1, 1))
            if args.start_month <= live_start.month <= args.end_month:
                jobs.append(live_job(live_start))
        if live_start is None:
            last_one_shot = args.end_month
        else:
            # The live transform's first month keeps a one-shot for its days before the live start
            last_one_shot = min(args.end_month, live_start.month if live_start.day > 1 else live_start.month - 1)
        jobs.extend(month_job(year, month, live_start) for month in range(args.start_month, last_one_shot + 1))
    jobs.sort(key=lambda job: job.start)
    return jobs


def print_configs(jobs: list[Job], enabled: bool) -> int:
    """
    Print each job's transform configuration as one JSON object on stdout, keyed by transform ID, and each
    one's clause count on stderr. Returns 1 if any is over MAX_NESTED_CLAUSES.
    """
    configs = {}
    over = False
    for job in jobs:
        config = create_transform_config(job, enabled=enabled)
        used, description = clause_budget(config)
        over |= used > MAX_NESTED_CLAUSES
        print(f"{job.transform_id}  [{job.start}, {job.end}){'  continuous' if job.live else ''}  "
              f"clauses: {description}{'  OVER THE LIMIT' if used > MAX_NESTED_CLAUSES else ''}", file=sys.stderr)
        configs[job.transform_id] = config
    print(json.dumps(configs, indent=2))
    return 1 if over else 0


def main() -> int:
    args = parse_args()

    if args.start_year > args.end_year:
        print(f"Error: start-year ({args.start_year}) must be <= end-year ({args.end_year})", file=sys.stderr)
        return 1
    if not 1 <= args.start_month <= args.end_month <= 12:
        print(f"Error: need 1 <= start-month ({args.start_month}) <= end-month ({args.end_month}) <= 12",
              file=sys.stderr)
        return 1

    today = datetime.now(timezone.utc).date()

    if args.print_config:
        return print_configs(plan_jobs(args, today, lambda year: None), enabled=not args.no_start)

    if not args.url or not args.user:
        print("Error: --url and --user are required", file=sys.stderr)
        return 1
    if not args.password:
        print("Error: --password or $OPENSEARCH_PASSWORD is required", file=sys.stderr)
        return 1

    auth = HTTPBasicAuth(args.user, args.password)
    verify = not args.insecure

    try:
        jobs = plan_jobs(args, today, lambda year: find_live_transform_start(args.url, year, auth, verify))
    except requests.RequestException as e:
        print(f"Error: could not list transforms: {e}", file=sys.stderr)
        return 1

    # A transform over the clause limit installs fine and fails on its first search that has data
    for job in jobs:
        used, description = clause_budget(create_transform_config(job))
        if used > MAX_NESTED_CLAUSES:
            print(f"Error: {job.transform_id} would use too many Lucene clauses ({description}); "
                  f"lower CONTINUOUS_PAGE_SIZE or simplify the data_selection_query", file=sys.stderr)
            return 1

    print(f"Installing {len(jobs)} transform jobs for years {args.start_year}-{args.end_year}")
    print(f"Today: {today.isoformat()} (completed months and this month's earlier days are one-shot, "
          f"the rest is continuous)")

    failed_jobs = []
    retired_years = {}

    for job in jobs:
        config = create_transform_config(job, enabled=not args.no_start)
        transform_id, year, start, end = job.transform_id, job.year, job.start, job.end
        target_index = config["transform"]["target_index"]

        print(f"\n{'='*60}")
        print(f"Installing transform job: {transform_id}  [{start}, {end}){'  continuous' if job.live else ''}")
        print(f"{'='*60}")

        if args.dry_run:
            print("(dry run: nothing changed)")
            continue

        # A year moving to monthly transforms must not keep its old yearly transform running
        if year not in retired_years:
            retired_years[year] = retire_yearly_transform(args.url, year, auth, verify)
        ok, reason = retired_years[year]
        if not ok:
            print(f"✗ Could not retire yearly transform for {year}: {reason}", file=sys.stderr)
            failed_jobs.append((transform_id, f"Yearly transform not retired: {reason}"))
            continue

        # Check if transform already exists
        if check_transform_exists(args.url, transform_id, auth, verify):
            should_delete = args.force

            if should_delete:
                print(f"Stopping transform {transform_id} before deletion...")
                try:
                    stop_resp = stop_transform(args.url, transform_id, auth, verify)
                    if 200 <= stop_resp.status_code < 300:
                        print(f"✓ Transform {transform_id} stopped.")
                    else:
                        print(f"⚠ Stop returned {stop_resp.status_code} — proceeding with delete anyway.")
                except requests.RequestException as e:
                    print(f"⚠ Stop request failed ({e}) — proceeding with delete anyway.")

                print(f"Deleting existing transform {transform_id}...")
                try:
                    del_resp = delete_transform(args.url, transform_id, auth, verify)
                    print(f"Delete response: {del_resp.status_code} {del_resp.reason}")
                    if 200 <= del_resp.status_code < 300:
                        print(f"✓ Successfully deleted transform {transform_id}")
                    else:
                        print(f"✗ Failed to delete transform {transform_id}", file=sys.stderr)
                        failed_jobs.append((transform_id, "Failed to delete existing transform"))
                        continue
                except requests.RequestException as e:
                    print(f"Failed to delete transform: {e}", file=sys.stderr)
                    failed_jobs.append((transform_id, "Delete request failed"))
                    continue
            else:
                print(f"ℹ Transform job {transform_id} already exists. Skipping installation (use --force to overwrite).")
                continue

        # Ensure target index exists with @timestamp mapping so index-pattern can detect the time field
        ok, reason = ensure_target_index(args.url, target_index, auth, verify)
        if not ok:
            print(f"✗ Failed to create/ensure target index {target_index}: {reason}", file=sys.stderr)
            failed_jobs.append((transform_id, f"Target index error: {reason}"))
            continue

        # Clean before creating: an enabled transform starts running as soon as it exists
        if args.clean_target:
            print(f"Deleting existing {target_index} documents in [{start}, {end})...")
            ok, message = clean_target_range(args.url, target_index, start, end, auth, verify)
            if not ok:
                print(f"✗ {message}", file=sys.stderr)
                failed_jobs.append((transform_id, f"Target cleanup failed: {message}"))
                continue
            print(f"✓ {message}")

        try:
            resp = install_transform(args.url, transform_id, config, auth, verify)
        except requests.RequestException as e:
            print(f"HTTP request failed: {e}", file=sys.stderr)
            failed_jobs.append((transform_id, "Request failed"))
            continue
        
        print(f"Response: {resp.status_code} {resp.reason}")
        content = resp.text.strip()
        if content:
            try:
                print(json.dumps(json.loads(content), indent=2))
            except json.JSONDecodeError:
                print(content)
        
        if 200 <= resp.status_code < 300:
            print(f"✓ Transform job {transform_id} installed successfully.")
            
            # Start the transform if requested
            if not args.no_start:
                print(f"Starting transform job {transform_id}...")
                try:
                    start_resp = start_transform(args.url, transform_id, auth, verify)
                    print(f"Start response: {start_resp.status_code} {start_resp.reason}")
                    start_content = start_resp.text.strip()
                    if start_content:
                        try:
                            print(json.dumps(json.loads(start_content), indent=2))
                        except json.JSONDecodeError:
                            print(start_content)
                    
                    if 200 <= start_resp.status_code < 300:
                        print(f"✓ Transform job {transform_id} started successfully.")
                    else:
                        print(f"⚠ Failed to start transform job {transform_id}", file=sys.stderr)
                        failed_jobs.append((transform_id, "Failed to start"))
                except requests.RequestException as e:
                    print(f"Failed to start transform: {e}", file=sys.stderr)
                    failed_jobs.append((transform_id, "Start request failed"))
        else:
            print(f"✗ Failed to install transform job {transform_id}", file=sys.stderr)
            failed_jobs.append((transform_id, "Failed to install"))
    
    if args.dry_run:
        print(f"\nDry run: {len(jobs)} transform jobs would be installed.")
        return 0

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    total = len(jobs)
    success = total - len(failed_jobs)
    print(f"Successfully installed: {success}/{total}")
    
    if failed_jobs:
        print(f"\nFailed jobs:")
        for job_id, reason in failed_jobs:
            print(f"  - {job_id}: {reason}")
        return 2
    
    print("\n✓ All transform jobs installed successfully!")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
