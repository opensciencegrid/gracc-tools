#!/usr/bin/python

import elasticsearch
from elasticsearch_dsl import Search, A, Q
#import logging
import sys
import os


#logging.basicConfig(level=logging.WARN)
#es = elasticsearch.Elasticsearch(
#        ['https://gracc.opensciencegrid.org/q'],
#        timeout=300, use_ssl=True, verify_certs=False)

es = elasticsearch.Elasticsearch(
        ['localhost:9200'],
        timeout=300)

osg_raw_index = 'gracc.osg.raw-*'

s = Search(using=es, index=osg_raw_index)

# Match the records by ProbeName and processors = 0.
s = s.query("match", ProbeName="htcondor-ce:hosted-ce18.grid.uchicago.edu")
s = s.query("match", Processors=0)
s = s.filter('range', EndTime={'from': 'now-12M', 'to': 'now'})
response = s.execute()

print "Query took %i milliseconds" % response.took 

print "Query got %i hits" % response.hits.total

#update_id = "8c5816978fee6fc17718bcf81350d1f4"
#print "About to update record with id: %s" % update_id
#es.update(index="gracc.osg.raw3-2017.07", doc_type='JobUsageRecord', id=update_id, body={'doc': {'VOName': 'UserSchool2017'}}) 
update_buffer = []
for hit in s.scan():
    # Calculate the new CoreHours (cores = 1):
    core_hours = hit.WallDuration / 3600.0
    updated_doc = {
        "doc": {
            "CoreHours": core_hours,
            "Processors": 1
        },
        "_index": hit.meta.index,
        "_id": hit.meta.id,
        "_type": hit.meta.doc_type,
        "_op_type": "update"
    }
    update_buffer.append(updated_doc)
    print "Update %s" % updated_doc
    if len(update_buffer) > 200:
        elasticsearch.helpers.bulk(es, update_buffer)
        update_buffer = []

elasticsearch.helpers.bulk(es, update_buffer)
    #es.update(index=hit.meta.index, doc_type=hit.meta.doc_type, id=hit.meta.id, body={'doc': updated_doc})
