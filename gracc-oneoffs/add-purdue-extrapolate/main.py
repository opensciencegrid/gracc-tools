
import pika
import elasticsearch
from elasticsearch_dsl import Search, A, Q
import dateutil.parser as parser
import datetime
import json

es = elasticsearch.Elasticsearch(
        ['https://gracc.opensciencegrid.org/q'],
        timeout=300, use_ssl=True, verify_certs=False)


def getGoodRecords():
    starttime = parser.parse("2021-01-31")
    endtime = parser.parse("2021-01-31 10:00:00")
    s = Search(using=es, index='gracc.osg.summary')
    s = s.query("match", ProbeName="slurm:hammer-osg.rcac.purdue.edu")
    s = s.query(Q("range", EndTime={"gte": starttime, "lt": endtime}))
    response = s.execute()
    print("Query took %i milliseconds" % response.took)

    print("Query got %i hits" % response.hits.total.value)
    return [hit.to_dict() for hit in response.hits]


def sendRecords(newEndtime: datetime.datetime, records: list):
    """
    Send the record with a new Endtime
    """
    # Update the end time in the records
    for record in records:
        print("Before EndTime:", record['EndTime'])
        record['EndTime'] = newEndtime.isoformat(timespec="milliseconds") + "Z"
        print("After EndTime:", record['EndTime'])
        print(json.dumps(record, indent=2))
    
    # Start the blocking connection to the message bus
    parameters = pika.URLParameters("amqps://getyourcredentials")
    connection = pika.BlockingConnection(parameters)

    channel = connection.channel()

    for record in records:
        channel.basic_publish('gracc2.osg.summary',
                              "",
                              json.dumps(record),
                              pika.BasicProperties(content_type='text/plain',
                                                   delivery_mode=1))

    connection.close()


def main():
    # Query to get the previous good day from the gap (summary only)
    hits = getGoodRecords()
    # Alter the record dates
    for hit in hits:
        # Remove checksum, @timestamp
        del hit['checksum']
        del hit['@timestamp']

    # Send the records to the summary exchange.
    sendRecords(parser.parse("2021-02-01"), hits)
    sendRecords(parser.parse("2021-02-02"), hits)
    sendRecords(parser.parse("2021-02-03"), hits)



if __name__ == "__main__":
    main()


