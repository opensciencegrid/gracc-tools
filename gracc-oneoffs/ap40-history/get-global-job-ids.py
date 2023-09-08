#!/usr/bin/env python3

# Get the GlobalJobIds for a certain probe within a date range.
# We have some history records that were copied over to a different AP
# (which has a different ProbeName); we want to send the history
# that haven't already been uploaded (using GlobalJobIds as the key).

# Thanks to Derek Weitzel for showing me how to use elasticsearch_dsl  -matyas

import elasticsearch
from elasticsearch_dsl import Search, A, Q
from dateutil import parser
import sys


#import warnings
#warnings.filterwarnings("ignore", message=".*verify_certs=False")
#warnings.filterwarnings("ignore", message=".*Unverified HTTPS request")

es = elasticsearch.Elasticsearch(['https://gracc.opensciencegrid.org/q'],
                                 timeout=300, use_ssl=True,
                                 #verify_certs=False
                                 )

starttime = parser.parse("2023-07-25")
endtime = parser.parse("2023-09-01")

# We want all job records between those two times
s = Search(using=es, index="gracc.osg.raw-*")
s = s.query("match", ProbeName="condor-ap:ap7.chtc.wisc.edu")
s = s.query(Q("range", EndTime={"gte": starttime, "lt": endtime}))
response = s.execute()
print("Got %i hits" % response.hits.total['value'], file=sys.stderr)

for hit in s.scan():
    # Extract the GlobalJobIds from the records.
    # The gratia probe prepends "condor." to the GJI; remove those
    # so they match what's in the job ad.
    try:
        gji = hit.GlobalJobId
        if gji.startswith("condor."):
            gji = gji[len("condor."):]
        print(hit.GlobalJobId)
    except AttributeError:
        pass

