FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    jq \
    grep \
    gawk \
    coreutils \
    less \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workdir

# Copy the frozen incident telemetry into the agent's working directory.
# NOTE: ground truth (tests/) is NOT copied here — it is injected only at
# verification time, so the agent never sees the answer.
COPY data/ /workdir/data/

CMD ["/bin/bash"]
