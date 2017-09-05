#!/usr/bin/python

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
osg_summary_index = 'gracc.osg.summary'

s = Search(using=es, index=osg_raw_index)

s = s.query("match", ProjectName="UserSchool2017")
response = s.execute()

print "Query took %i milliseconds" % response.took 

print "Query got %i hits" % response.hits.total

#update_id = "8c5816978fee6fc17718bcf81350d1f4"
#print "About to update record with id: %s" % update_id
#es.update(index="gracc.osg.raw3-2017.07", doc_type='JobUsageRecord', id=update_id, body={'doc': {'VOName': 'UserSchool2017'}}) 

for hit in s.scan():
    
    if hit.ProjectName != hit.VOName:
        print "Updating %s with VOName = %s to VOName = %s" % (hit.meta.id, hit.VOName, hit.ProjectName)
        es.update(index=hit.meta.index, doc_type=hit.meta.doc_type, id=hit.meta.id, body={'doc': {'VOName': hit.ProjectName}})
        
# Also, in the summary, we want to delete records that match:
# - ProjectName: UserSchool2017
# - VOName != ProjectName
s = Search(using=es, index=osg_summary_index)
s = s.query("match", ProjectName="UserSchool2017")
response = s.execute()
print "Query took %i milliseconds" % response.took 

print "Query got %i hits" % response.hits.total

for hit in s.scan():
    if hit.ProjectName != hit.VOName:
        print "Deleting id = %s, with ProjectName = %s and VOName = %s" % (hit.meta.id, hit.ProjectName, hit.VOName)
        es.delete(index=hit.meta.index, doc_type=hit.meta.doc_type, id=hit.meta.id)

