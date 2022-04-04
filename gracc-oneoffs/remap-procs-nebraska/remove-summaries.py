#!/usr/bin/python

import elasticsearch
from elasticsearch_dsl import Search, A, Q
#import logging
import sys
import os
import csv
import json


#logging.basicConfig(level=logging.WARN)
es = elasticsearch.Elasticsearch(
        ['https://gracc.opensciencegrid.org/q'],
        timeout=300, use_ssl=True, verify_certs=False)

#es = elasticsearch.Elasticsearch(
#        ['localhost:9200'],
#        timeout=300)

#osg_raw_index = 'gracc.osg.raw-*'
osg_summary_index = 'gracc.osg.summary'

s = Search(using=es, index=osg_summary_index)

# Match the records by ProbeName and processors = 0.
query = (Q('match', ProbeName="htcondor-ce:red.unl.edu") | \
        Q('match', ProbeName="htcondor-ce:red-gw1.unl.edu") | \
        Q('match', ProbeName="htcondor-ce:red-gw2.unl.edu") | \
        Q('match', ProbeName="condor:red.unl.edu") | \
        Q('match', ProbeName="condor:red-gw1.unl.edu") | \
        Q('match', ProbeName="condor:red-gw2.unl.edu") )
#s = s.query("match", ProbeName="htcondor-ce:hosted-ce18.grid.uchicago.edu")
#s = s.query("match", Processors=0)
s = s.query(query)
s = s.filter('range', EndTime={'from': 'now-2M', 'to': 'now'})
print(json.dumps(s.to_dict()))
response = s.execute()

print("Query took %i milliseconds", response.took)

print("Query got %i hits", response.hits.total)
total_hits = 0
update_buffer = []
for hit in s.scan():
    total_hits += 1
    # Calculate the new CoreHours (cores = 1):
    updated_doc = {
        "_index": hit.meta.index,
        "_id": hit.meta.id,
        "_type": hit.meta.doc_type,
        "_op_type": "delete"
    }
    update_buffer.append(updated_doc)
    #print("Update %s" % updated_doc)
    if len(update_buffer) > 200:
        print("Flushing buffer of %i records, of total %i" % (len(update_buffer), total_hits))
        elasticsearch.helpers.bulk(es, update_buffer)
        update_buffer = []

print("Total hits: %i" % total_hits)
elasticsearch.helpers.bulk(es, update_buffer)
    #es.update(index=hit.meta.index, doc_type=hit.meta.doc_type, id=hit.meta.id, body={'doc': updated_doc})
