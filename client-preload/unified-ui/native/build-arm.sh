#!/bin/sh
# Separate native candidate; does not reseal or replace the installed bundle.
set -eu
native_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$native_dir/../../.." && pwd)
image=sha256:86fdcabbf2da48f1023d39362d3edc92495da739c716716b83b973aee91d54a8
output_dir="$repo_dir/analysis/unified-ui-native"
mkdir -p "$output_dir"
build_id=$(python3 "$native_dir/build_id.py" "$repo_dir")
docker image inspect "$image" >/dev/null
docker run --rm --network none \
 -e WMP_UI_BUILD_ID="$build_id" \
 --user "$(id -u):$(id -g)" \
 -v "$repo_dir/client-preload:/src:ro" \
 -v "$output_dir:/out" \
 "$image" /bin/sh -c 'set -eu
 aarch64-linux-gnu-gcc -DWMP_UNIFIED_FILAMENT -fPIC -O2 -Wall -Wextra -c /src/openace-compat/wmp_openace_compat.c -o /out/compat.o
 aarch64-linux-gnu-g++ -DWMP_UI_BUILD_ID=\"$WMP_UI_BUILD_ID\" -std=c++11 -shared -fPIC -O2 -Wall -Wextra -Werror -pthread -Wl,-z,nodelete \
 -I/src/unified-ui/native -I/src/openace-compat/screen1113/source/client -I/src/openace-compat/screen1113/source/vendor \
 /src/unified-ui/native/bootstrap.cpp /out/compat.o -ldl -o /out/libwmp_unified_screen_candidate.so
 aarch64-linux-gnu-readelf -h -d -V /out/libwmp_unified_screen_candidate.so > /out/readelf.txt'
python3 "$native_dir/manifest.py" "$repo_dir" "$output_dir" "$image"
