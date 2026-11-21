# Flash Next chat with Nemotron Mini for titles

Use [this YAML](flash-next-nemotron-mini.yaml) with llama-swap on a Linux AMD
Strix Halo host supported by [Halogen Flash Server][flash-start]. Install
Docker with AMD GPU device access and put [`llama-server` from llama.cpp][llama-release]
on `PATH`. Mini runs on the CPU in this example, leaving GPU allocations to
Flash.

1. Run `docker pull ghcr.io/peonist-ai/halogen-flash-server:0.20.7`. Download the
   [Flash Next v2 weights][flash-weights] into one directory:
   `qwen38-flash-next-v2.hgn`, `qwen38-flash-next-ngram.hgn` and the `tokenizer/`
   directory. The matching draft head, `qwen38-flash-next-drafter-r2-ht4.hgn`, is
   optional. The example mounts the directory read-only and does not download
   weights at launch.
2. Download `Nemotron-Mini-4B-Instruct-Q4_K_M.gguf` from [Bartowski's GGUF
   conversion][mini-gguf] of the [NVIDIA model][mini-model]. Set `FLASH_WEIGHTS`
   and `NEMOTRON_GGUF` in the YAML to the absolute local directory and file
   paths, respectively.
3. From this directory, run:

   ```sh
   llama-swap -validate -config flash-next-nemotron-mini.yaml
   llama-swap -listen 127.0.0.1:8080 -config flash-next-nemotron-mini.yaml
   ```

Point your OpenAI-compatible client at `http://127.0.0.1:8080/v1`. In
`/v1/chat/completions`, use `halogen-qwen3.8-flash-next` for main chat and
`nemotron-mini` for titles or other short text. The models start on demand.
Both are in the same `swap: false` group, so requesting one does not unload the
other. This is not a memory reservation.

Flash uses one slot, its [native 262,144-token context][flash-native] per request
and a separate KV pool of exactly 262,144 positions. Its default reply budget
is 16,384 tokens, including reasoning, leaving up to 245,760 tokens for the
**rendered** input when that full budget is reserved. The 16,384-token prefill
chunk is a separate scratch-memory setting, not a prompt limit. See Halogen's
[engine flags][flash-flags] and [token budgets][flash-budget]. Mini splits a
2,048-token total context into [two llama.cpp slots][llama-flags], each with
1,024 tokens for prompt and reply combined.

**Hardware status:** A 4,096-token Flash and one-slot Mini trial qualified titles
only. A memory-pressure watchdog stopped the full-size Flash load before the
API was ready. Full-length retrieval and co-residency with two Mini slots
remain unverified. Before relying on this setup, check Flash's `/health`,
`/slots` and `/cache` and Mini's `/props` at their assigned loopback ports, then
test your workload while both models are loaded.

[flash-start]: https://github.com/peonist-ai/halogen-flash-server/blob/8cc4b8e0a0ef4269f18f8a47dd1ed28aa0cf5b6c/docs/getting-started.md
[flash-flags]: https://github.com/peonist-ai/halogen-flash-server/blob/8cc4b8e0a0ef4269f18f8a47dd1ed28aa0cf5b6c/docs/FLAGS.md
[flash-budget]: https://github.com/peonist-ai/halogen-flash-server/blob/8cc4b8e0a0ef4269f18f8a47dd1ed28aa0cf5b6c/docs/token-budgets.md
[flash-native]: https://huggingface.co/Qwen/Qwen3.8-Flash-Next/blob/main/config.json
[flash-weights]: https://huggingface.co/peonist-ai/halogen-qwen3.8-flash-next
[llama-release]: https://github.com/ggml-org/llama.cpp/releases/tag/b12359
[llama-flags]: https://github.com/ggml-org/llama.cpp/blob/b12359/tools/server/README.md
[mini-gguf]: https://huggingface.co/bartowski/Nemotron-Mini-4B-Instruct-GGUF
[mini-model]: https://huggingface.co/nvidia/Nemotron-Mini-4B-Instruct
