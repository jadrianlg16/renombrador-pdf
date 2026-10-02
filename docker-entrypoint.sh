#!/bin/sh
# Container entrypoint: makes /app/data writable for an unprivileged user, then drops root.
#
# The server runs as whoever owns /app/data: the "app" user for a named volume, or the host
# user when a folder they own is bind-mounted (on Linux), so the files on the host keep their
# owner. A root-owned /app/data, such as a volume written by an earlier image that ran as
# root, is handed to "app". Anything inside that belongs to someone else, for example files
# such an image created, is then given to the same user so the server can rename and delete it.
set -eu

data_dir=/app/data

if [ "$(id -u)" != "0" ]; then
    # Started with --user: there is nothing to fix and no privilege to drop.
    exec "$@"
fi

mkdir -p "$data_dir/inbox" "$data_dir/state"

if [ "$(stat -c %u "$data_dir")" = "0" ]; then
    chown app:app "$data_dir" 2>/dev/null || true
fi
run_uid="$(stat -c %u "$data_dir")"
run_gid="$(stat -c %g "$data_dir")"

if [ "$run_uid" = "0" ]; then
    # Some network filesystems refuse chown. Keep working as earlier images did.
    echo "docker-entrypoint: cannot change the owner of $data_dir; running as root" >&2
    exec "$@"
fi

find "$data_dir" \( ! -user "$run_uid" -o ! -group "$run_gid" \) -exec chown "$run_uid:$run_gid" {} +

exec setpriv --reuid="$run_uid" --regid="$run_gid" --clear-groups -- "$@"
