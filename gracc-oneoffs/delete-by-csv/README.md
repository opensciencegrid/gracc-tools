# Delete by CSV file

The `run.py` script will delete records from GRACC, given a CSV file.  The CSV file format is required to be:

    <id>,<index>

For example:

    bbb699c2c88883d8e4b1043ae898b3de,gracc.osg.raw3-2018.04
    f89dd46983ec7713d02cbb4d55b52ab5,gracc.osg.raw3-2017.09
    631961d38855a101667d3463c864a5aa,gracc.osg.raw3-2018.06
    b589c996ceaa07927cba99c65ac6d9c5,gracc.osg.raw3-2018.05

An example query.py script is provided that can generate the csv above.  It will need to be customized
each time it is used for the specific query required.

