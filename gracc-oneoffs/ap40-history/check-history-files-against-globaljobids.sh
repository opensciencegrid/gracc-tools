#!/bin/bash
# Loops over a directory of history files, checking the GlobalJobId
# of each one against a list of global job ids
# If a history file has a GJI that's in the list, then the history
# file is moved to a "sent/" subdirectory.  Otherwise it is moved to
# an "unsent/" subdirectory.

# thanks Carl Edquist for the bash advice

fail () { echo >&2 "$*"; exit 1; }

linecount () { wc -l "$1" | awk '{print $1}'; }

dir=${1?Need directory of history files and global job ids file}
gjifile=${2?Need global job ids file}

gjifile=$(readlink -f "$gjifile")  # get absolute path
                                   # XXX doesn't work on mac
[[ -f $gjifile ]] || fail "GlobalJobIds file $gjifile doesn't exist or is not a file"
cd "$dir" || fail "Couldn't cd into $dir"

set -eu

mkdir -p sent unsent
rm -f sent-list.txt unsent-list.txt
touch sent-list.txt unsent-list.txt
for file in history.*; do
    gji=$(grep '^GlobalJobId  =' "$file" | tr -d '"' | awk '{print $3}') || :
    if grep -Fqx "$gji" "$gjifile"; then
        echo "$file" >> sent-list.txt
    else
        echo "$file" >> unsent-list.txt
    fi
done

printf "%s records not sent; %s records already sent.\n" "$(linecount unsent-list.txt)" "$(linecount sent-list.txt)"

# XXX xargs -a also doesn't work on mac
xargs -a sent-list.txt mv -t sent/
xargs -a unsent-list.txt mv -t unsent/

set +e
PER_JOB_HISTORY_DIR=$(condor_config_val PER_JOB_HISTORY_DIR)

if [[ ! $PER_JOB_HISTORY_DIR ]]; then
    echo "PER_JOB_HISTORY_DIR unknown... can't give you instructions..."
else
    echo "Verify that everything is OK, then do"
    echo "      cd \"$dir/unsent\""
    # `mv * $PER_JOB_HISTORY_DIR` would result in too long of a command line to call an external command with.
    # printf is a builtin so that's fine. `mv -t` treats the first argument as the destination directory.
    echo "      printf '%s\0' history.* | xargs -0 mv -t \"$PER_JOB_HISTORY_DIR/\""
fi

