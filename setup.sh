#!/bin/sh
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# setup.sh

set -e
docker build -t acidchess .
docker rm -f acidchess 2>/dev/null || true
# With ARCADE_URL set, accounts come from acid-arcade-db on the arcade network
set --
if [ -n "$ARCADE_URL" ]; then
	set -- --network arcade -e ARCADE_URL -e ARCADE_PUBLIC_URL=${ARCADE_PUBLIC_URL:-https://arcade.\{domain\}} -e ARCADE_GAME=chess
fi
docker run -d \
	--name acidchess \
	--restart unless-stopped \
	-p 127.0.0.1:20001:20001 \
	-v acidchess_data:/data \
	"$@" \
	acidchess
