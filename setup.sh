#!/bin/sh
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# setup.sh

set -e
# The arcade network comes from acid-arcade-db's setup.sh, without it docker run below fails after the old container is gone
if [ -n "$ARCADE_URL" ] && ! docker network inspect arcade >/dev/null 2>&1; then
	echo 'ARCADE_URL is set but the arcade docker network does not exist, run acid-arcade-db setup.sh first' >&2
	exit 1
fi
docker build -t acidchess .
docker run --rm --user root -v acidchess_data:/data acidchess chown -R app:app /data # data made by older root containers
docker rm -f acidchess 2>/dev/null || true
# With ARCADE_URL set, accounts come from acid-arcade-db on the arcade network
set --
if [ -n "$ARCADE_URL" ]; then
	set -- --network arcade -e ARCADE_URL -e ARCADE_PUBLIC_URL=${ARCADE_PUBLIC_URL:-https://arcade.\{domain\}} -e ARCADE_GAME=chess -e ARCADE_KEY
fi
# The one address crawlers and share cards use, when the site answers on several
if [ -n "$ACIDCHESS_PUBLIC_URL" ]; then
	set -- "$@" -e ACIDCHESS_PUBLIC_URL
fi
docker run -d \
	--name acidchess \
	--restart unless-stopped \
	-p 127.0.0.1:20001:20001 \
	-v acidchess_data:/data \
	"$@" \
	acidchess
