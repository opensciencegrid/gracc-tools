"""
Query the ES index for all the jobs that have a specific probe name
and return the job ids.

Arguments:
- probe_name: The name of the probe to look up
- correction json: JSON with the job to core count corrections

"""
import json
import sys
import elasticsearch
from elasticsearch_dsl import Search, A, Q

es = elasticsearch.Elasticsearch(
        ['https://gracc.opensciencegrid.org/q'],
        timeout=300, use_ssl=True, verify_certs=False)

osg_raw_index = 'gracc.osg.raw-*'

def main():
    
    #a = A('terms', field="LocalJobId", size=1000000)
    # Grab all the jobs from a specific probe
    probe_name = sys.argv[1]
    s = Search(using=es, index=osg_raw_index)
    s = s.filter('range', EndTime={'from': '2022-06-22', 'to': 'now'})
    s = s.query('match', ProbeName=probe_name)
    response = s.execute()
    print(response.success())
    print(response.took)
    print(response.hits.total.value)

    jobs = {}
    with open(sys.argv[2], 'r') as f:
        jobs = json.load(f)

    print(len(jobs))
    failed_lookups = 0
    successful_lookups = 0
    # Get the job ids
    for job in s.scan():
        print(job.meta.id)
        print(job)
        print(job['LocalJobId'])
        if job['LocalJobId'] not in jobs:
            print("Job not in jobs list: {}".format(job['LocalJobId']))
            failed_lookups += 1
        else:
            successful_lookups += 1

    print("Failed lookups: {}".format(failed_lookups))
    print("Successful lookups: {}".format(successful_lookups))



if __name__ == "__main__":
    main()