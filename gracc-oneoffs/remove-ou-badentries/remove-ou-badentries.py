#!/usr/bin/python

import elasticsearch
from elasticsearch_dsl import Search, A, Q
#import logging
import sys
import os


#logging.basicConfig(level=logging.WARN)
es = elasticsearch.Elasticsearch(
        ['https://gracc.opensciencegrid.org/q'],
        timeout=300, use_ssl=True, verify_certs=False)

osg_raw_index = 'gracc.osg.raw-*'
osg_summary_index = 'gracc.osg.summary'

s = Search(using=es, index=osg_raw_index)

s = s.query("match", ProbeName="slurm:grid1.oscer.ou.edu")
s = s.query("range", WallDuration={'gte': 345600})
s = s.filter('range', EndTime={'from': 'now-7d', 'to': 'now'})

response = s.execute()

print("Query took {} milliseconds".format(response.took))

print("Query got {} hits".format(response.hits.total))
for hit in s.scan():
    print("WallDuration: {} hours".format(hit['WallDuration'] / 3600))
    es.delete(index=hit.meta.index, doc_type=hit.meta.doc_type, id=hit.meta.id)


s = Search(using=es, index=osg_summary_index)

s = s.query("match", ProbeName="slurm:grid1.oscer.ou.edu")
s = s.filter('range', EndTime={'from': 'now-7d', 'to': 'now'})

response = s.execute()
print("Query took {} milliseconds".format(response.took))

print("Query got {} hits".format(response.hits.total))
for hit in s.scan():
    print("WallDuration: {} hours".format(hit['WallDuration'] / 3600))
    es.delete(index=hit.meta.index, doc_type=hit.meta.doc_type, id=hit.meta.id)