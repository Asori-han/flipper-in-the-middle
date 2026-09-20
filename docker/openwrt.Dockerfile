FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    bc \
    bison \
    build-essential \
    ca-certificates \
    ccache \
    clang \
    cpio \
    curl \
    file \
    flex \
    g++ \
    gawk \
    gcc-multilib \
    gettext \
    git \
    libelf-dev \
    libncurses5-dev \
    libssl-dev \
    make \
    patch \
    python3 \
    python3-distutils \
    rsync \
    subversion \
    swig \
    tar \
    time \
    unzip \
    wget \
    xz-utils \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash builder \
    && mkdir -p /build-cache \
    && chown builder:builder /build-cache

USER builder
WORKDIR /workspace
RUN git config --global --add safe.directory /workspace/third_party/openwrt
CMD ["bash"]
