#!/usr/bin/python

import elasticsearch
from elasticsearch_dsl import Search, A, Q
#import logging
import operator
import sys
import os
import dateutil.parser as parser

#logging.basicConfig(level=logging.WARN)
es = elasticsearch.Elasticsearch(
        ['https://gracc.opensciencegrid.org/q'],
        timeout=300, use_ssl=True, verify_certs=False)
#es = elasticsearch.Elasticsearch()

osg_raw_index = 'gracc.osg.raw-*'
osg_summary_index = 'gracc.osg.summary'

starttime = parser.parse("2021-06-20")
endtime = parser.parse("2021-06-27")

s = Search(using=es, index=osg_raw_index)

#s = s.query("match", Grid="Local")
s = s.query("match", ProbeName="condor:cmsgrid02.hep.wisc.edu")
s = s.query(Q("range", EndTime={"gte": starttime, "lt": endtime}))
#s = s.query(~Q("exists", field="VOName"))
s = s.query(Q("match", VOName="/cms/Role=pilot/Capability=NULL"))
s = s.query(Q("range", CoreHours={"gte": 500, "lt": 10000000}))
response = s.execute()

print("Query took %i milliseconds" % response.took)

print("Query got %i hits" % response.hits.total.value)
#s.delete()


s = Search(using=es, index=osg_summary_index)
#s = s.query("match", Grid="Local")
s = s.query("match", ProbeName="condor:cmsgrid02.hep.wisc.edu")
s = s.query(Q("range", EndTime={"gte": starttime, "lt": endtime}))
#s = s.query("match", VOName="N/A")

response = s.execute()
print("Query took %i milliseconds" % response.took)

print("Query got %i hits" % response.hits.total.value)
#s.delete()

