import elasticsearch
from elasticsearch_dsl import Search, A, Q
#import logging
import sys
import os
import csv
import json
import dateutil.parser as dparser


#logging.basicConfig(level=logging.WARN)
es = elasticsearch.Elasticsearch(
        ['https://gracc.opensciencegrid.org/q'],
        timeout=300, use_ssl=True, verify_certs=False)

osg_summary_index = 'gracc.osg.summary'

s = Search(using=es, index=osg_summary_index)

#s = s.filter('range', CoreHours={'gt': '1'})

beginning_year = dparser.parse("2022-04-01T00:00:00Z")
may_one = dparser.parse("2022-05-01T00:00:00Z")


s = s.filter('range', EndTime={'from': beginning_year, 'to': may_one})
a = A('terms', field = 'ProbeName', size = 2**30)
a.metric('CoreHours', 'sum', field = 'CoreHours')
s.aggs.bucket('probes', a)

s.to_dict()
response = s.execute()

#print(response.aggregations.to_dict())
before_may_probes = []
for probe in response.aggregations.probes.buckets:
    before_may_probes.append(probe['key'])

s = Search(using=es, index=osg_summary_index)
s = s.filter('range', EndTime={'from': may_one, 'to': 'now'})
a = A('terms', field = 'ProbeName', size = 2**30)
a.metric('CoreHours', 'sum', field = 'CoreHours')
s.aggs.bucket('probes', a)

response = s.execute()

after_may_probes = []
for probe in response.aggregations.probes.buckets:
    after_may_probes.append(probe['key'])

print("Before May: %i" % len(before_may_probes))
print("After May: %i" % len(after_may_probes))

print(set(before_may_probes) - set(after_may_probes))
print("Number of probes that stopped reporting: %i" % (len(set(before_may_probes) - set(after_may_probes))))
