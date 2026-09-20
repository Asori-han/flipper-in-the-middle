FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    build-essential \
    ca-certificates \
    ffmpeg \
    file \
    git \
    gnuplot \
    graphviz \
    openjdk-17-jre-headless \
    libffi-dev \
    libimage-exiftool-perl \
    libyaml-dev \
    make \
    python3 \
    python3-dev \
    python3-pip \
    qpdf \
    ruby-dev \
    ruby-full \
    tshark \
    && rm -rf /var/lib/apt/lists/*

RUN gem install bundler --version 2.4.22 --no-document

WORKDIR /opt/flipper-in-the-middle
COPY Gemfile Gemfile.lock ./
RUN bundle _2.4.22_ config set path /opt/bundle \
    && bundle _2.4.22_ install

COPY requirements/lab.txt requirements/demo.txt ./requirements/
RUN python3 -m pip install --no-cache-dir \
    -r requirements/lab.txt \
    -r requirements/demo.txt

RUN useradd --create-home --shell /bin/bash builder

ENV BUNDLE_PATH=/opt/bundle \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/workspace/build/cache/matplotlib \
    PYTHONPYCACHEPREFIX=/workspace/build/cache/pycache

USER builder
WORKDIR /workspace
CMD ["bash"]
