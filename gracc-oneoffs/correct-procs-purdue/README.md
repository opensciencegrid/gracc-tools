Purdue Corrections
==================

Files:

- create-map.py - Onetime script that maps HTCondor-CE jobs -> slurm jobs -> slurm procs.
- make-corrections.py - Mostly done script to correct jobs from the map created from create-map.py.  Right now, just prints out the corrections.
- same-core-corrections.py - Mostly done script to correct all jobs from a probename to a single number of procs.  Right now, just prints out the corrections.


TODO
----

None of the scripts actually make the correction.  The correction will need to be done on the GRACC host itself (firewalled).

Hammer cluster is the only cluster that should be corrected.  The others are not far off correct, and don't contribute much to the total Purdue usage at all.

Still need to determine if we should just a weighted average of number of procs for Hammer.


