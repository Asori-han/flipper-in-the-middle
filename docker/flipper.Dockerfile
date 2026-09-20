FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    ccache \
    curl \
    file \
    git \
    make \
    python3 \
    tar \
    unzip \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash builder

USER builder
WORKDIR /workspace
RUN git config --global --add safe.directory /workspace/third_party/flipperzero-firmware
CMD ["bash"]
