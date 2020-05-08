Remove Bad OU entries
=====================

Date: 2020-05-08

From Horst:

> This nonsensical data was most likely
> caused by the SLURM upgrade on Tuesday. The OSCER admins mentioned that
> there were some issues during the upgrade, that they lost all submitted
> (and held) jobs, and that they had to migrate the database, so I
> wouldn't be surprised if in the process of updating/migrating the
> database these nonsensical jobs were introduced.


Remove the entries with really large walltime (larger than 4 days) that was submitted by the OU gratia probe.
