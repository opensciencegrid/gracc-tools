"""
Query the ES index for all the jobs that have a specific probe name
and return the job ids.

Arguments:
- probe_name: The name of the probe to look up
- cores: The number of cores to set the job to
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
    s = s.filter('match', Processors=1)
    s = s.query('match', ProbeName=probe_name)
    response = s.execute()
    print(response.success())
    print(response.took)
    print(response.hits.total.value)

    cores = int(sys.argv[2])
    gain_in_coreHours = 0.0
    # Get the job ids
    jobs = 0
    for job in s.scan():
        jobs += 1
        # Correct the core count, and CoreHours
        print("Job: {}, updating Processors from {} to {}, CoreHours from {} to {}".format(
            job['LocalJobId'],
            job['Processors'],
            cores,
            job['CoreHours'],
            cores * (job['WallDuration'] / 3600)))
        job['Processors'] = cores
        gain_in_coreHours += (cores * (job['WallDuration'] / 3600)) - job['CoreHours']

        job['CoreHours'] = cores * (job['WallDuration'] / 3600)

    print("Gain in core hours: {} for {} jobs".format(gain_in_coreHours, jobs))

if __name__ == "__main__":
    main()