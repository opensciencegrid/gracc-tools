#!/usr/bin/env python3

import re
import sys
import json
import time
import datetime
import statistics
import collections
import elasticsearch
from elasticsearch_dsl import Search, A, Q


gracc_url = 'https://gracc.opensciencegrid.org/q'

jobs_raw_index = 'gracc.osg.raw-*'
jobs_summary_index = 'gracc.osg.summary'


def query_ncpus_counts():
    es = elasticsearch.Elasticsearch([gracc_url])

    starttime = datetime.datetime(2022, 5, 15)
    endtime   = datetime.datetime(2022, 6, 15)
    filters = (
            Q('range', EndTime={'gte': starttime, 'lt': endtime })
        &   Q('term', ResourceType='Batch')
        &   Q('term', OIM_FQDN='hammer-osg.rcac.purdue.edu')
    )

    s = Search(using=es, index=jobs_summary_index)

    s = s.query('bool', filter=[filters])
    s.aggs.bucket('ncpus', 'terms', field='Processors', size=1000) \
          .bucket('sumCount', 'sum', field='Count')

    resp = s.execute()
    aggs = resp.aggregations

    #d    = aggs.to_dict()
    #print(json.dumps(d, indent=2, sort_keys=1))

    n_c = sorted( (b.key, int(b.sumCount.value)) for b in aggs.ncpus.buckets )

    # [(1, 11), (2, 1712), (20, 2318), (40, 1156), (48, 865), (256, 329)]

    return n_c


def get_median_ncpus(n_c):
    listo = ( [ncpus] * count for ncpus, count in n_c if ncpus > 1 )

    median = statistics.median(sum(listo, []))

    # 20

    return median



def main():
    n_c = query_ncpus_counts()
    median = get_median_ncpus(n_c)
    print(median)


if __name__ == '__main__':
    main()

