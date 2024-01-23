from elasticsearch7 import Elasticsearch

def sizeof_fmt(num, suffix="B"):
    for unit in ("", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"):
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Yi{suffix}"

es = Elasticsearch(
        ['127.0.0.1:9200'],
        timeout=300)

# Query for all the indexes that match ps-* or shrink-*-ps-*
ps_indices = es.indices.get("ps_*")

print("Done with search")

#print(ps_indices["ps_trace_2021-07"])
#ps_stats = es.indices.get("ps_*")
#print("All stats:")
#print(ps_stats)


#ps_stats = es.indices.stats("ps_trace_2021-07")
#ps_stats = es.indices.stats("ps_*")
#print("ps_trace_2021-07 stats:")
#print(sizeof_fmt(ps_stats['_all']['total']['store']['size_in_bytes']))
#print(ps_indices.keys())
for index in ps_indices.keys():
    # Get the size of the index
    ps_stats = es.indices.stats(index)
    # Now print out the index name and the size of the index
    print(index + ": " + sizeof_fmt(ps_stats['_all']['total']['store']['size_in_bytes']))
    #es.indices.delete(index)
    #print(index)


