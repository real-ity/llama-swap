#!/usr/bin/env bash
# Build the native HIP server and CLI at the pinned upstream revision.
set -euo pipefail

sd=984eb0686cbf5b7fc4f0063d9e0b1fb38d5c4f82
ggml=ccb88f810be05bccc9621e706354611ccc2462c7
src=/tmp/sd-source
mkdir "$src"
git -C "$src" init -q
git -C "$src" fetch --depth 1 https://github.com/leejet/stable-diffusion.cpp.git "$sd"
git -C "$src" checkout --detach FETCH_HEAD
test "$(git -C "$src" rev-parse HEAD:ggml)" = "$ggml"
git -C "$src" submodule update --init --depth 1 ggml
test "$(git -C "$src/ggml" rev-parse HEAD)" = "$ggml"

cmake -S "$src" -B "$src/build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ \
    -DCMAKE_PREFIX_PATH=/opt/rocm/core -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DSD_HIPBLAS=ON -DGPU_TARGETS=gfx1151 -DAMDGPU_TARGETS=gfx1151 \
    -DCMAKE_HIP_ARCHITECTURES=gfx1151 \
    -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF -DGGML_BACKEND_DL=OFF \
    -DSD_BUILD_SHARED_LIBS=OFF -DSD_BUILD_SHARED_GGML_LIB=OFF \
    -DSD_BUILD_EXAMPLES=ON -DSD_SERVER_BUILD_FRONTEND=OFF -DSD_WEBM=OFF -DSD_WEBP=OFF
cmake --build "$src/build" --parallel "$1" --target sd-server sd-cli
install -D "$src/build/bin/sd-server" /install/bin/sd-server
install -D "$src/build/bin/sd-cli" /install/bin/sd-cli
mkdir -p /install/licenses
cd "$src"
find . -name .git -prune -o -path ./build -prune -o \
    -type f \( -name 'LICENSE*' -o -name 'COPYING*' -o -name 'NOTICE*' \) \
    -exec cp --parents '{}' /install/licenses/ \;
rm -rf "$src"
