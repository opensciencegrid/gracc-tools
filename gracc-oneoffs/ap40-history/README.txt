These scripts deal with an issue where we moved the /var/lib/condor
(including job history) to a new AP, had permissions issues with
PER_JOB_HISTORY_DIR, and wanted to upload records out of the
/var/lib/condor/spool/history* files, making sure we don't upload something
/that had already been uploaded from the old AP.

First we copied the history files out of spool into a separate directory. 
We ran get-global-job-ids.py to get GlobalJobIds from GRACC from the time
range we were interested in.

We ran split-history.sh on each history file to turn the big history file
into individual files for each ad.

Then we ran check-history-files-against-globaljobids.sh to sort the
individual history files into "sent" and "unsent" directory based on whether
GRACC has already seen a record with that GlobalJobId.

Then we moved the history files from the "unsent" directory to
PER_JOB_HISTORY_DIR and let the gratia condor probe handle the upload.