#!/bin/sh
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# setup.sh

set -e
docker build -t acidchess .
docker rm -f acidchess 2>/dev/null || true
docker run -d \
	--name acidchess \
	--restart unless-stopped \
	-p 127.0.0.1:20001:20001 \
	-v acidchess_data:/data \
	acidchess
