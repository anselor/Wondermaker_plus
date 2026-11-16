# Reconstructed from the recorded compiler image history. This recipe is not
# asserted to regenerate the exact frozen image ID: base/apt state may change.
FROM debian:bullseye
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      crossbuild-essential-arm64 \
      binutils-aarch64-linux-gnu \
 && rm -rf /var/lib/apt/lists/*
