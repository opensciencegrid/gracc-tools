"""
Create the mapping from the HTCondor-CE job to the number of procs allocated
"""

import re
import json
import csv
import sys
import pandas as pd

def main():
    # First argument is the HTCondor-CE job file
    # Second argument is the slurm
    # Third argument is the output file

    # Slurm jobs is a dictionary of the form:
    # {job_id: {'procs': procs}}
    slurm_jobs = {}

    reader = pd.read_csv(sys.argv[2], delim_whitespace=True)
    for index, row in reader.iterrows():
        if row['JobID'].startswith('-------'):
            continue
        slurm_jobs[row['JobID']] = {'procs': row['AllocCPUS']}
    #with open(sys.argv[2]) as f:
    #print(slurm_jobs)

    # proper line will look like
    # batch slurm bell-osg.rcac.purdue.edu_9619_bell-osg.rcac.purdue.edu_5823845.0_1658189899 slurm/20220718/18789607
    htcondor_jobs = {}
    search_re = re.compile("batch\sslurm\s[\w\-\.]+_([\d]+)\.0_.*\sslurm/\d+/(\d+)$")
    missing_jobs = []
    with open(sys.argv[1]) as f:
        for line in f:
            matched = search_re.match(line)
            if matched:
                if matched.group(2) not in slurm_jobs:
                    print("Job {} not found in slurm".format(matched.group(2)))
                    missing_jobs.append(matched.group(2))
                    continue
                condor_job_id = matched.group(1)
                htcondor_jobs[condor_job_id] = slurm_jobs[matched.group(2)]
            
    print("Missing jobs: {}".format(missing_jobs))
    print("Found {} jobs".format(len(htcondor_jobs)))
    print("Writing to {}".format(sys.argv[3]))

    with open(sys.argv[3], 'w') as f:
        json.dump(htcondor_jobs, f)


if __name__ == "__main__":
    main()

