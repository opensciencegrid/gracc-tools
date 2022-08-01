#!/usr/bin/env python3

"""
Query the ES index for all the jobs that have a specific probe name
and send updates to gracc correcting the number of cores & CoreHours

Has to be run on gracc host (hcc-gracc.unl.edu)

Arguments:
- probe_name: The name of the probe to look up
- cores: The number of cores to set the job to
"""
import json
import sys
import elasticsearch
from elasticsearch_dsl import Search, A, Q

es = elasticsearch.Elasticsearch(
        ['http://localhost:9200'], timeout=300, use_ssl=False)

osg_raw_index = 'gracc.osg.raw-*'

def main():
    
    #a = A('terms', field="LocalJobId", size=1000000)
    # Grab all the jobs from a specific probe
    probe_name = sys.argv[1]
    s = Search(using=es, index=osg_raw_index).extra(from_=0, size=10000)
    s = s.filter('range', EndTime={'from': '2022-06-22', 'to': 'now'})
    s = s.filter('match', Processors=1)
    s = s.query('match', ProbeName=probe_name)
    response = s.execute()
    print(response.success())
    print(response.took)
    print(response.hits.total.value)
    print(len(response.hits.hits))

    cores = int(sys.argv[2])
    gain_in_coreHours = 0.0

    # update each job with fixed Processors and recalculated CoreHours
    for h in response.hits.hits:
        d = h.to_dict()
        job = d['_source']
        job['Processors'] = cores
        job['CoreHours'] = cores * (job['WallDuration'] / 3600)

        r = es.update(index=d['_index'], id=d['_id'], body={'doc': job})

        if r['result'] not in ['updated', 'noop']:
            print('Error updating correction. Response: %s' % r)
        else:
            print('Correction %s updated.' % d['_id'])


if __name__ == "__main__":
    main()

