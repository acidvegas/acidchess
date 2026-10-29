# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# Dockerfile

# Build Fairy-Stockfish for the computer opponent
FROM alpine:3.20 AS engine
ARG FSF_COMMIT=9f778da
ARG ARCH=x86-64-modern
RUN apk add --no-cache git make g++
RUN git clone https://github.com/fairy-stockfish/Fairy-Stockfish.git /fsf && cd /fsf && git checkout $FSF_COMMIT
RUN cd /fsf/src && make -j$(nproc) build ARCH=$ARCH largeboards=yes all=yes && strip stockfish

FROM python:3.12-alpine

WORKDIR /app

COPY requirements.txt .

# zope.interface (a gevent dependency) has no musl wheel, so build its pure-python version
RUN python3 -m pip install --upgrade pip && PURE_PYTHON=1 python3 -m pip install --no-cache-dir --only-binary :all: --no-binary zope.interface -r requirements.txt && rm requirements.txt

# The engine is C++, so it needs the C++ runtime
RUN apk add --no-cache libstdc++

COPY --from=engine /fsf/src/stockfish /engines/fairy-stockfish
COPY acidchess/ .

ENV ACIDCHESS_DATA_DIR=/data
ENV ACIDCHESS_ENGINE=/engines/fairy-stockfish
ENV PYTHONUNBUFFERED=1
RUN mkdir -p /data

EXPOSE 20001

# Room state lives in process memory, so run a single gevent worker
CMD ["gunicorn", "--worker-class", "gevent", "--workers", "1", "--worker-connections", "1000", "--graceful-timeout", "5", "--bind", "0.0.0.0:20001", "app:app"]
