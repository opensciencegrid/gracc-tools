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

osg_raw_index = 'gracc.osg.raw-*'

# First, aggregate
a = A('terms', field="LocalJobId", size=1000000)
s = Search(using=es, index=osg_raw_index)
s = s.filter('range', EndTime={'from': 'now-5M', 'to': 'now'})
s = s.query('match', ProbeName="condor:osg-ce.sprace.org.br")

s.aggs.bucket('num_matches', a)

print s.to_dict()
response = s.execute()

print "Query took %i milliseconds" % response.took 

print "Query got %i hits" % response.hits.total

#print response.aggregations.num_matches.to_dict()
counter = 0
for bucket in response.aggregations.num_matches.buckets:
    if bucket['doc_count'] == 2:
        counter +=1
        print bucket['key']
        s = Search(using=es, index=osg_raw_index)
        s = s.query('match', LocalJobId=bucket['key'])
        s = s.filter('range', EndTime={'from': 'now-5M', 'to': 'now'})
        s = s.query('match', ProbeName="condor:osg-ce.sprace.org.br")
        single_response = s.execute()
        # Just delete the first 1 of the repeated jobs
        print single_response
        hit = single_response.hits[0]
        print "Deleting 1 of 2 jobids with jobid = %s" % hit.LocalJobId
        es.delete(index=hit.meta.index, doc_type=hit.meta.doc_type, id=hit.meta.id)
        
print counter