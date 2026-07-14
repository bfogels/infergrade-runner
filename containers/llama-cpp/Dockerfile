FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG LLAMA_CPP_REPO=https://github.com/ggml-org/llama.cpp.git
ARG LLAMA_CPP_REF=14d3ba45f

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    cmake \
    git \
    python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

RUN git clone ${LLAMA_CPP_REPO} llama.cpp \
    && cd llama.cpp \
    && git checkout ${LLAMA_CPP_REF} \
    && cmake -B build -DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_TESTS=OFF \
    && cmake --build build --config Release -j"$(nproc)" \
    && ln -s /opt/llama.cpp/build/bin/llama-cli /usr/local/bin/llama-cli \
    && ln -s /opt/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server

WORKDIR /workspace

ENTRYPOINT ["llama-cli"]
