#!/bin/sh
# Container entrypoint: makes /app/data writable for an unprivileged user, then drops root.
#
# A volume created by an earlier image that ran as root holds root-owned files, so they are
# handed to the "app" user before the server starts. When /app/data is a host folder that a
# regular user owns (a bind mount on Linux), the server runs as that user instead, so files
# on the host keep their owner.
set -eu

data_dir=/app/data

if [ "$(id -u)" != "0" ]; then
    # Started with --user: there is nothing to fix and no privilege to drop.
    exec "$@"
fi

mkdir -p "$data_dir/inbox" "$data_dir/state"
app_uid="$(id -u app)"
owner_uid="$(stat -c %u "$data_dir")"

if [ "$owner_uid" != "0" ] && [ "$owner_uid" != "$app_uid" ]; then
    run_uid="$owner_uid"
    run_gid="$(stat -c %g "$data_dir")"
else
    find "$data_dir" \( ! -user app -o ! -group app \) -exec chown app:app {} +
    run_uid="$app_uid"
    run_gid="$(id -g app)"
fi

exec setpriv --reuid="$run_uid" --regid="$run_gid" --clear-groups -- "$@"
