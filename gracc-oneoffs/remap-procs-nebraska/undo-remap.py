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

osg_raw_index = 'gracc.osg.raw-*'

s = Search(using=es, index=osg_raw_index)

# Match the records by ProbeName and processors = 0.
query = (Q('match', ProbeName="htcondor-ce:red.unl.edu") | \
        Q('match', ProbeName="htcondor-ce:red-gw1.unl.edu") | \
        Q('match', ProbeName="htcondor-ce:red-gw2.unl.edu") | \
        Q('match', ProbeName="condor:red.unl.edu") | \
        Q('match', ProbeName="condor:red-gw1.unl.edu") | \
        Q('match', ProbeName="condor:red-gw2.unl.edu") ) & \
        Q('match', Processors=1) & \
        Q('match', Corrected="Nebraska-Node-Proc-Fix") & \
        ~Q('match', LocalUserId="lcgadmin")
#s = s.query("match", ProbeName="htcondor-ce:hosted-ce18.grid.uchicago.edu")
#s = s.query("match", Processors=0)
s = s.query(query)
s = s.filter('range', EndTime={'from': 'now-2M', 'to': 'now-1M'})
print(json.dumps(s.to_dict()))
response = s.execute()

print("Query took %i milliseconds", response.took)

print("Query got %i hits", response.hits.total)

# Map is <node>:<cores>
node_map = {}

with open('Red-Cores.csv', 'r') as csvfile:
    reader = csv.reader(csvfile, delimiter=',')
    for row in reader:
        node_map[row[0]] = row[1]

print(node_map)





#update_id = "8c5816978fee6fc17718bcf81350d1f4"
#print "About to update record with id: %s" % update_id
#es.update(index="gracc.osg.raw3-2017.07", doc_type='JobUsageRecord', id=update_id, body={'doc': {'VOName': 'UserSchool2017'}}) 
update_buffer = []
no_host = 0
host_not_in_map = 0
total_hits = 0
for hit in s.scan():
    total_hits += 1
    # Calculate the new CoreHours (cores = 1):
    if 'Host' not in hit:
        no_host += 1
        continue
    if hit['Host'] not in node_map:
        print("Host not in node_map:", hit['Host'])
        host_not_in_map += 1
        continue
    real_cores = 1
    core_hours = (hit.WallDuration / 3600.0) * float(real_cores)
    updated_doc = {
        "doc": {
            "CoreHours": core_hours,
            "Processors": real_cores,
            "Corrected": "Nebraska-Node-Proc-Fix-2",
        },
        "_index": hit.meta.index,
        "_id": hit.meta.id,
        "_type": hit.meta.doc_type,
        "_op_type": "update"
    }
    update_buffer.append(updated_doc)
    #print("Update %s" % updated_doc)
    if len(update_buffer) > 200:
        elasticsearch.helpers.bulk(es, update_buffer)
        update_buffer = []

print("No Host: %i" % no_host)
print("Host not in map: %i" % host_not_in_map)
print("Total hits: %i" % total_hits)
elasticsearch.helpers.bulk(es, update_buffer)
    #es.update(index=hit.meta.index, doc_type=hit.meta.doc_type, id=hit.meta.id, body={'doc': updated_doc})
