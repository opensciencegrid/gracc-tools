#!/usr/bin/env python3

import opensearchpy
from opensearchpy.helpers.query import Match

# HTTP debug logging
# import http.client as http_client
# http_client.HTTPConnection.debuglevel = 1

client = opensearchpy.OpenSearch(
    ["https://gracc.opensciencegrid.org/q"],
    timeout=300,
    use_ssl=True,
    verify_certs=True,
)

OSG_RAW_INDEX = "gracc.osg.raw3-*"
# OSG_RAW_INDEX = "gracc.osg.raw3-2026.05"

s = opensearchpy.Search(using=client, index=OSG_RAW_INDEX)

s = s.query(Match(ProbeName="coffea.casa"))
s = s.filter("range", CpuDuration={"gte": 30000})
s = s.filter("range", WallDuration={"lte": 600})
s = s.filter("range", **{"@timestamp": {"gte": "now-90d", "lte": "now"}})

s = s.query(Q("wildcard", GlobalUsername="*@unl.edu"))

s = s.params(clear_scroll=False)

for hit in s.scan():
    print("{},{}".format(hit.meta.id, hit.meta.index))
