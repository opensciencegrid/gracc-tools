Syracuse Facilities Fix
=======================

Syracuse submitted "Payload" type records with Host_description set to the hostname of the worker node.  We need to set the host description to the Syracuse machine instead, which is Syracuse.

 AS-124CARN-20-S3-its-c6-osg-20160824
https://gracc.opensciencegrid.org/kibana/app/kibana#/doc/gracc.osg.summary/gratia.osg.summary2-oim/JobUsageRecordSummary?id=992946121&_g=(refreshInterval:(display:Off,pause:!f,value:0),time:(from:now-1y,mode:quick,to:now))

```
AS*
AAF*
ARCH*
BFAS*
```

The CRUSH-OSG looks like a different problem.  It looks like those records are coming from regular jobs through a CE, but the ResourceType is being reported as "Payload" rather than "Batch"

CRUSH-OSG*

