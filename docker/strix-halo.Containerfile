# syntax=docker/dockerfile:1
# Local build only. Keep vendor notices and do not publish the assembled image.
ARG TOOLBOX=docker.io/kyuz0/amd-strix-halo-toolboxes@sha256:5893ef15c436f15bee2378c2b5ecfdf0f6c2c45a07f401a5dd2e3ce4a38edcf4
ARG COMFY=docker.io/kyuz0/amd-strix-halo-comfyui@sha256:384aa1fecef6a841832e0d5552949977330308d8c25e212a94f5e8dfcc061cae
ARG HALOGEN=ghcr.io/peonist-ai/halogen@sha256:dc0a39a0016d6cfc58a197978febaafdf8d28403f724ded6111d98b5fb7ac0ea
ARG FLASH=ghcr.io/peonist-ai/halogen-flash-server@sha256:273714ccb64dabb7fac0418ee1b6dd83eb57d2fd44cf286eb68a7c694a27c203
ARG GO_IMAGE=docker.io/library/golang@sha256:e482b31b5d30c31f9e495f4b8cbdf41429b2d74955dfbcd9c0a904483d738390
ARG NODE_IMAGE=docker.io/library/node@sha256:9f0dde62d10e7ff7a310ecaebd66225f6b46c17e6cb778449a77b05d3541bea2

FROM ${TOOLBOX} AS toolbox
FROM toolbox AS sd-build
USER root
RUN microdnf -y --nodocs --setopt=install_weak_deps=0 install \
    gcc gcc-c++ cmake ninja-build git-core findutils amdrocm-core-devel10.0-gfx1151 \
    && microdnf clean all
COPY docker/strix-halo/build-sd.sh /tmp/build-sd.sh
ARG SD_BUILD_JOBS=2
RUN bash /tmp/build-sd.sh "$SD_BUILD_JOBS"

FROM ${HALOGEN} AS halogen
COPY docker/strix-halo/donor-defaults.py /tmp/donor-defaults.py
RUN python3 /tmp/donor-defaults.py > /defaults.json
FROM ${FLASH} AS flash
COPY docker/strix-halo/donor-defaults.py /tmp/donor-defaults.py
RUN python3 /tmp/donor-defaults.py > /defaults.json

FROM ${NODE_IMAGE} AS ui
WORKDIR /src/ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui/ ./
RUN npm run build

FROM ${GO_IMAGE} AS controller
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
COPY --from=ui /src/internal/server/ui_dist/ internal/server/ui_dist/
RUN make src && CGO_ENABLED=0 go build -trimpath -tags embed_ui,embed_src -o /out/llama-swap .

FROM ${COMFY} AS runtime
# Keep the ComfyUI venv intact. The other engines use their own ELF loaders
# and library paths rather than replacing ComfyUI's glibc or ROCm libraries.
COPY --from=toolbox /usr/local/ /opt/strix-engines/llama/usr/local/
COPY --from=toolbox /usr/lib64/ /opt/strix-engines/llama/usr/lib64/
COPY --from=toolbox /opt/rocm/ /opt/strix-engines/llama/opt/rocm/
COPY --from=toolbox /etc/alternatives/ /opt/strix-engines/llama/etc/alternatives/
COPY --from=toolbox /usr/share/licenses/ /opt/strix-engines/llama/licenses/
COPY --from=halogen /usr/local/ /opt/strix-engines/halogen/usr/local/
COPY --from=halogen /lib/x86_64-linux-gnu/ /opt/strix-engines/halogen/lib/x86_64-linux-gnu/
COPY --from=halogen /halogen/ /opt/strix-engines/halogen/halogen/
COPY --from=halogen /licenses/ /opt/strix-engines/halogen/licenses/
COPY --from=halogen /usr/share/doc/ /opt/strix-engines/halogen/licenses/packages/
COPY --from=halogen /defaults.json /opt/strix-engines/halogen/defaults.json
COPY --from=flash /usr/local/ /opt/strix-engines/flash/usr/local/
COPY --from=flash /lib/x86_64-linux-gnu/ /opt/strix-engines/flash/lib/x86_64-linux-gnu/
COPY --from=flash /halogen/ /opt/strix-engines/flash/halogen/
COPY --from=flash /opt/halogen/ /opt/strix-engines/flash/opt/halogen/
COPY --from=flash /licenses/ /opt/strix-engines/flash/licenses/
COPY --from=flash /usr/share/doc/ /opt/strix-engines/flash/licenses/packages/
COPY --from=flash /defaults.json /opt/strix-engines/flash/defaults.json
COPY --from=sd-build /install/ /opt/strix-engines/sd/
COPY --from=controller /out/llama-swap /usr/local/bin/llama-swap
COPY LICENSE.md /usr/local/share/licenses/llama-swap/LICENSE.md
COPY --chmod=755 docker/strix-halo/launch.py /usr/local/bin/strix-launch
COPY docker/strix-halo/verify-runtime.py /opt/strix-engines/verify-runtime.py
COPY docker/strix-halo/comfy-models.yaml /etc/llama-swap/comfy-models.yaml
COPY docker/strix-halo.yaml /etc/llama-swap/config.yaml

ENV HOME=/tmp
WORKDIR /tmp
# Model-free checks. The build fails if a split runtime cannot start its help
# or resolve its libraries. Do not pass GPU devices or model paths here.
RUN --network=none /opt/venv/bin/python /opt/strix-engines/verify-runtime.py \
    && llama-swap -validate -config /etc/llama-swap/config.yaml

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s CMD curl -fsS http://127.0.0.1:8080/health || exit 1
ENTRYPOINT ["/usr/local/bin/llama-swap"]
CMD ["-config", "/etc/llama-swap/config.yaml", "-listen", "0.0.0.0:8080"]
