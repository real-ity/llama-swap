# Alternative chat and image models

Run [this YAML](alternative-models.yaml) **instead of** the [Flash/Mini
example](flash-next-nemotron-mini.md). Stop the other controller first if it
uses the same GPU. This example loads one heavy model at a time. A request for
a different model unloads the previous one before starting the next. This does
not guarantee that any one model fits in memory.

## Local prerequisites

Set the five path macros in the YAML to absolute local paths. The launch
commands do not download weights. Use builds that support your GPU and driver.

- **Halogen Qwen3.8 27B:** On a supported Linux AMD Strix Halo host, pull
  `ghcr.io/peonist-ai/halogen:0.1.4` with Docker. Set `HALOGEN_WEIGHTS` to the
  directory containing [`qwen3.8-27b-p1w4d-d2.hgn` and its `tokenizer/`
  directory][halogen-weights]. This is the 27B Halogen release, not Halogen
  Flash. The container uses the [vendor's GPU flags][halogen], including host
  IPC and disabled seccomp filtering. Only the API port is published, on
  loopback.
- **Hermes 4.3 36B:** Put [`llama-server`][llama] on `PATH`. Set `HERMES_GGUF`
  to [`NousResearch_Hermes-4.3-36B-Q4_K_M.gguf`][hermes], the Bartowski
  conversion. It uses the GGUF's chat template, one slot and an 8,192-token
  context.
- **FLUX.2 Klein 9B:** Put [`sd-server` from stable-diffusion.cpp][sd] on `PATH`.
  Set `KLEIN_WEIGHTS` to [`flux-2-klein-9b.safetensors`][klein], the distilled
  9B model, not Base, 4B or FP8. The publisher requires accepting its
  non-commercial model license. Set `KLEIN_ENCODER` and `KLEIN_VAE` to `qwen_3_8b.safetensors` and
  `flux2-vae.safetensors` from the [split component files][components]. The
  public encoder filename differs from the starter's local `qwen3-8b.safetensors`.
  The example uses four sampling steps and CFG 1.0. ComfyUI is a workflow
  service and is not needed to run this model.

From this directory:

```sh
llama-swap -validate -config alternative-models.yaml
llama-swap -listen 127.0.0.1:8080 -config alternative-models.yaml
```

On unload or shutdown, llama-swap runs `docker stop` for Halogen and sends
SIGTERM to the native `llama-server` and `sd-server` processes.

## Routing

Use `halogen-qwen3.8-27b` or `hermes-4.3-36b` as `model` in
`POST /v1/chat/completions`. Both backends use `/health` for readiness.

For images, llama-swap selects `flux2-klein-9b` and sends sd-server its
advertised name, `sd-cpp-local`. It checks `/v1/models` for readiness. An
OpenAI-style request returns base64 image data in `data[0].b64_json`:

```sh
curl http://127.0.0.1:8080/v1/images/generations -H 'Content-Type: application/json' \
  -d '{"model":"flux2-klein-9b","prompt":"A blue teapot","size":"512x512"}'
```

For the [WebUI-style API][sd-api], select the model in the URL instead of
adding an OpenAI `model` field. The response contains `images[0]`:

```sh
curl http://127.0.0.1:8080/upstream/flux2-klein-9b/sdapi/v1/txt2img \
  -H 'Content-Type: application/json' -d '{"prompt":"A blue teapot","width":512,"height":512}'
```

The config and routes were checked without loading models. GPU fit, startup
and generation on hardware are not verified.

[halogen]: https://github.com/peonist-ai/halogen-server/tree/v0.1.4
[halogen-weights]: https://huggingface.co/peonist-ai/halogen-qwen3.8-27b
[llama]: https://github.com/ggml-org/llama.cpp/releases/tag/b12359
[hermes]: https://huggingface.co/bartowski/NousResearch_Hermes-4.3-36B-GGUF
[sd]: https://github.com/leejet/stable-diffusion.cpp/releases/tag/master-1106-532d2c1
[klein]: https://huggingface.co/black-forest-labs/FLUX.2-klein-9B
[components]: https://huggingface.co/Comfy-Org/Flux-2-Klein-9B/tree/main/split_files
[sd-api]: https://github.com/leejet/stable-diffusion.cpp/blob/532d2c15c430a785a712b2d94281f04e733008a4/examples/server/api.md
