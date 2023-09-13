#!/bin/bash

# Usage: split-history.sh <history file> <dest directory> <prefix number>

# Splits a single condor history file into one file per job, so the gratia
# condor probe can process it. The files will have names like "history.${prefixnum}.23"
# because that is the pattern that the gratia probe looks for.
# The prefix number is required to avoid colliding with existing files.

# (Normally the jobs in PER_JOB_HISTORY_DIR have names like "history.$ClusterId.$ProcId"
# but the gratia condor probe only cares that the file names match a pattern,
# not the actual numbers.)

# thanks to Greg Thain for telling me about csplit  -matyas

histfile=${1?Need history file and destination directory and prefix number}
destdir=${2?Need destination directory and prefix number}
prefixnum=${3?Need prefix number e.g. 0000}

fail () { echo >&2 "fail: $*"; exit 1; }

[[ $prefixnum =~ ^[0-9]+$ ]] || fail "Prefix number $prefixnum isn't a number"
[[ -f $histfile ]] || fail "History file $histfile doesn't exist"
mkdir -p "$destdir"
[[ -d $destdir ]] || fail "Couldn't make dest dir $destdir"

csplit --quiet --prefix "${destdir}/history.${prefixnum}." "${histfile}" '/^\*\*\*.*$/' '{*}'

