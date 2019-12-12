# gracc-reprocess-hostedce

This is modified for fixing some hosted-ce records.  Not the original gracc-reprocess

Ran with this command:

```
./gracc-reprocess "gracc.osg.raw3-quarantine" http://gratia-osg-prod.opensciencegrid.org --query 'ProbeName:"htcondor-ce:hosted-ce13.grid.uchicago.edu"' --es_url "https://gracc.opensciencegrid.org/q"
```

# Original README.md below

Read raw records from Elasticsearch and send them to
a GRACC Collector. Expects that records have a `RawXML` 
field with the original XML record.

## Installation

`gracc-reprocess` requires Python 2.7 and the following packages:

* elasticsearch (> 5.0)
* requests
* progressbar2

Clone the `gracc-tools` repo or [download the zip archive](https://github.com/opensciencegrid/gracc-tools/archive/master.zip).
To install the requirements with `pip`:

```
pip install -r requirements.txt
```

## Usage

```
$ ./gracc-reprocess -h
usage: gracc-reprocess [-h] [--size SIZE] [--timeout TIMEOUT] [--debug] [-q]
                       [-p] [--close] [--query QUERY] [--alias]
                       [--alias_regex ALIAS_REGEX] [--new_ver NEW_VER]
                       index url

Reprocess GRACC records through collector

positional arguments:
  index                 source index pattern
  url                   GRACC collector URL

optional arguments:
  -h, --help            show this help message and exit
  --size SIZE           Record batch size (default 500)
  --timeout TIMEOUT     Elasticsearch timeout (default 300)
  --debug               Enable debug logging
  -q, --quiet           Disable most logging (ignored if --debug specified)
  -p, --progress        Display progressbar
  --close               Close index when done processing
  --query QUERY         Limit reporecessed records by query_string
  --alias               Move alias when done processing
  --alias_regex ALIAS_REGEX
                        RE to extract index prefix and date (for alias)
  --new_ver NEW_VER     Version of new indices (for alias)
```

See the alias example below for more information on usage of those arguments.

## Examples

### Reprocess a single index

```
$./gracc-reprocess -pq --size 100 gracc.osg.raw3-2017.06 http://localhost:8888/gracc
2017-06-17 13:46:23,951 [UBER __main__] Processing index gracc.osg.raw3-2017.06
2017-06-17 13:46:23,973 [UBER __main__] Processing 15500 records
100% (15500 of 15500) |########################| Elapsed Time: 0:01:31 ETA:  0:00:00
2017-06-17 13:47:55,818 [UBER __main__] Processing complete. Sent 15500/15500 records
```

### Reprocess and close when done

```
$ curl 'localhost:9200/_cat/indices?v'
health status index                      uuid                   pri rep docs.count docs.deleted store.size pri.store.size
yellow open   gracc.test.raw3-2006.06    mQlg3nAQSGGwJZC3H5g91A   3   1        174            0    286.5kb        286.5kb

$ ./gracc-reprocess --close  gracc.test.raw3-2006.06 http://localhost:8888/gracc
2017-06-17 13:51:14,654 [INFO requests.packages.urllib3.connectionpool] Starting new HTTP connection (1): localhost
2017-06-17 13:51:14,659 [INFO elasticsearch] GET http://localhost:9200/gracc.test.raw3-2006.06/_settings [status:200 request:0.018s]
2017-06-17 13:51:14,659 [UBER __main__] Processing index gracc.test.raw3-2006.06
2017-06-17 13:51:14,676 [INFO elasticsearch] GET http://localhost:9200/gracc.test.raw3-2006.06/_search?size=500&scroll=5m&_source=RawXML [status:200 request:0.015s]
2017-06-17 13:51:14,679 [UBER __main__] Processing 174 records
2017-06-17 13:51:14,845 [INFO requests.packages.urllib3.connectionpool] Starting new HTTP connection (1): localhost
2017-06-17 13:51:15,606 [INFO __main__] sent 174/174 records
2017-06-17 13:51:15,634 [INFO elasticsearch] GET http://localhost:9200/_search/scroll?scroll=5m [status:200 request:0.028s]
2017-06-17 13:51:15,634 [UBER __main__] Processing complete. Sent 174/174 records
2017-06-17 13:51:15,634 [UBER __main__] Closing index gracc.test.raw3-2006.06
2017-06-17 13:51:17,645 [INFO elasticsearch] POST http://localhost:9200/gracc.test.raw3-2006.06/_close [status:200 request:2.010s]


$ curl 'localhost:9200/_cat/indices?v'
health status index                      uuid                   pri rep docs.count docs.deleted store.size pri.store.size
       close  gracc.test.raw3-2006.06    mQlg3nAQSGGwJZC3H5g91A                                                          
```

### Reprocess records matching query

```
$ ./gracc-reprocess -pq --size 100 --query 'ProbeName:"condor:fifebatch1.fnal.gov"' 'gracc.osg.raw3-*' http://localhost:8888/gracc
2017-06-17 13:54:14,796 [UBER __main__] Processing index gracc.osg.raw3-2017.06
2017-06-17 13:54:14,876 [UBER __main__] Processing 2279 records
100% (2279 of 2279) |##########################| Elapsed Time: 0:00:14 ETA:  0:00:00
2017-06-17 13:54:30,190 [UBER __main__] Processing complete. Sent 2279/2279 records
```

### Reprocess and update alias

The `--alias` option is intended for migrating raw data to a new schema/checksum.

`alias_regex` needs to match the index pattern and have two capture groups. The
first is index & alias prefix, the second is the date component. The default is 
`'(.*)\d-(\d\d\d\d\.\d\d)'`, which will work for GRACC monthly indices.

`--new_ver` is the schema version number, e.g. `gracc.osg.raw3-*` is schema version 3.
This is set by the `gracc-stash-raw` agent.

```
$ curl 'localhost:9200/_cat/aliases?v'
alias                  index                   filter routing.index routing.search
gracc.test.raw-2017.06 gracc.test.raw2-2017.06 -      -             -

$ ./gracc-reprocess --size 100 -pq --close --alias --new_ver 3 gracc.test.raw2-2017.06 http://localhost:8888/gracc
2017-06-17 14:06:50,536 [UBER __main__] Processing index gracc.test.raw2-2017.06
2017-06-17 14:06:50,562 [UBER __main__] Processing 2500 records
100% (2500 of 2500) |##########################| Elapsed Time: 0:00:14 ETA:  0:00:00
2017-06-17 14:07:06,346 [UBER __main__] Processing complete. Sent 2500/2500 records
2017-06-17 14:07:06,346 [UBER __main__] moving alias gracc.test.raw-2017.06 from gracc.test.raw2-2017.06 to gracc.test.raw3-2017.06
2017-06-17 14:07:06,876 [UBER __main__] Closing index gracc.test.raw2-2017.06

$ curl 'localhost:9200/_cat/aliases?v'
alias                  index                   filter routing.index routing.search
gracc.test.raw-2017.06 gracc.test.raw3-2017.06 -      -             -
```
