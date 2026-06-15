#!/usr/bin/env python3

import csv
import sys
import opensearchpy

client = opensearchpy.OpenSearch(
    ["https://opensearch-test1.gracc-dev.svc.cluster.local:9200/"],
    timeout=300,
    use_ssl=True,
    verify_certs=True,
    ca_certs="/certs/test1/ca.crt",
    client_cert="/certs/test1/tls.crt",
    client_key="/certs/test1/tls.key",
)


def action_generator(csv_filename):

    with open(csv_filename, "r") as csv_file:
        reader = csv.reader(csv_file, delimiter=",")
        # Create the bulk action
        for line in reader:
            # Delete all of the records by id
            yield {
                "_op_type": "delete",
                "_id": line[0],
                "_index": line[1],
                "_type": "JobUsageRecord",
            }


# First argument is the csv file to read in
csv_filename = sys.argv[1]

results = opensearchpy.helpers.bulk(client, action_generator(csv_filename))

print(results)
