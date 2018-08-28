import elasticsearch
from elasticsearch_dsl import Search, Q



es = elasticsearch.Elasticsearch(
        ['https://gracc.opensciencegrid.org/q'],
        timeout=300, use_ssl=True, verify_certs=False)

osg_raw_index = 'gracc.osg.raw-*'


s = Search(using=es, index=osg_raw_index)


s = s.filter('range', CpuDuration={'gte': 30000})
s = s.filter('range', WallDuration={'lte': 600})
s = s.filter('range',  **{'@timestamp': {'gte': 'now-1y', 'lte': 'now'}})

s = s.query(Q('wildcard', GlobalUsername = '*@unl.edu'))


for hit in s.scan():
    print("{},{}".format(hit.meta.id, hit.meta.index))



