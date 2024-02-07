#!/usr/bin/env python

import elasticsearch
from elasticsearch_dsl import Search, A, Q
#import logging
import operator
import sys
import os


#logging.basicConfig(level=logging.WARN)
es = elasticsearch.Elasticsearch(
        ['https://gracc.opensciencegrid.org/q'],
        timeout=300, use_ssl=True, verify_certs=False)

#es = elasticsearch.Elasticsearch(['localhost:9200'], timeout=300)

#osg_raw_index = 'gracc.osg.raw-*'
osg_summary_index = 'gracc.osg.summary'

s = Search(using=es, index=osg_summary_index)
s = s.filter('range', EndTime={'from': 'now-1y', 'to': 'now'})


print(s.to_dict())
#response = s.execute()
#response = s.delete()

print(f"Query took {response.took} milliseconds")

print(f"Query got {response.hits.total} hits")


