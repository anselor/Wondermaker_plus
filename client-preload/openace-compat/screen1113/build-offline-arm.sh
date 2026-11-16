#!/bin/sh
set -eu
bundle_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
compat_dir=$(CDPATH= cd -- "$bundle_dir/.." && pwd)
image=sha256:86fdcabbf2da48f1023d39362d3edc92495da739c716716b83b973aee91d54a8
# The pinned toolchain must be available; do not silently download/replace it.
docker image inspect "$image" >/dev/null
mkdir -p "$bundle_dir/build-arm"
docker run --rm --network none \
 -v "$bundle_dir/source:/src:ro" \
 -v "$compat_dir:/baseline:ro" \
 -v "$bundle_dir/build-arm:/out" \
 "$image" /bin/sh -c 'set -eu
 aarch64-linux-gnu-gcc -fPIC -O2 -Wall -Wextra -c /baseline/wmp_openace_compat.c -o /out/compat.o
 aarch64-linux-gnu-g++ -std=c++11 -shared -fPIC -O2 -Wall -Wextra -Werror -pthread -Wl,-z,nodelete -I/src/client -I/src/vendor /src/client/native_bootstrap.cpp /out/compat.o -ldl -o /out/libwmp_openace_screen_candidate.so
 aarch64-linux-gnu-readelf -h -d -V /out/libwmp_openace_screen_candidate.so > /out/readelf.txt'
python3 "$bundle_dir/repack-source.py"
