#!/usr/bin/python


import elasticsearch.helpers
import csv
import sys

es = elasticsearch.Elasticsearch(
        ['127.0.0.1:9200'],
        timeout=300)

osg_raw_index = 'gracc.osg.raw-*'


def action_generator(csv_filename):

    with open(csv_filename, 'r') as csv_file:
        reader = csv.reader(csv_file, delimiter=',')
        # Create the bulk action
        for line in reader:
            # Delete all of the records by id
            yield { 
                '_op_type': 'delete',
                '_id': line[0],
                '_index': line[1],
                '_type': 'JobUsageRecord'
            }
    

# First argument is the csv file to read in
csv_filename = sys.argv[1]
    
results = elasticsearch.helpers.bulk(es, action_generator(csv_filename))

print results
