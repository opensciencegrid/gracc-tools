#!/usr/bin/python

import elasticsearch
from elasticsearch_dsl import Search, A, Q
import dateutil.parser as parser

#logging.basicConfig(level=logging.WARN)
es = elasticsearch.Elasticsearch(
        ['https://gracc.opensciencegrid.org/q'],
        timeout=300, use_ssl=True, verify_certs=False)
osg_summary_index = 'gracc.osg.summary'


s = Search(using=es, index=osg_summary_index)

s = s.query("match", OIM_FQDN="osg.alice.ornl.gov")
s = s.query(Q("range", EndTime={"gte": "now-1M", "lt": "now"}))
s.aggs.bucket('jobs_per_day', 'date_histogram', field='EndTime', interval='day')\
    .metric('njobs', 'sum', field='Njobs')
response = s.execute()
print(response)

for tag in response.aggregations.jobs_per_day:
    print(tag.key, tag.njobs.value)
