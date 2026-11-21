package config

import (
	"path/filepath"
	"slices"
	"testing"
)

func TestConfig_StrixHaloComposeModelWindows(t *testing.T) {
	cfg, err := LoadConfig(filepath.Join("..", "..", "docker", "strix-halo.yaml"))
	if err != nil {
		t.Fatal(err)
	}

	for _, tc := range []struct {
		model, launcher string
		flags           map[string]string
		switches        []string
	}{
		{
			model: "nemotron-mini", launcher: "llama",
			flags:    map[string]string{"--ctx-size": "8192", "--parallel": "2", "--n-gpu-layers": "99"},
			switches: []string{"--no-kv-unified"},
		},
		{
			model: "halogen-qwen3.8-flash-next", launcher: "flash",
			flags: map[string]string{
				"--context": "262144", "--kv-pool": "262144", "--slots": "1",
				"--prefill": "16384", "--reply-tokens": "16384",
			},
		},
	} {
		t.Run(tc.model, func(t *testing.T) {
			model, ok := cfg.Models[tc.model]
			if !ok {
				t.Fatalf("no model %s", tc.model)
			}
			args, err := model.SanitizedCommand()
			if err != nil {
				t.Fatal(err)
			}
			if len(args) < 2 || args[0] != "strix-launch" || args[1] != tc.launcher {
				t.Fatalf("bad launcher: %v", args)
			}
			for flag, want := range tc.flags {
				i := slices.Index(args, flag)
				if i < 0 || i+1 >= len(args) || args[i+1] != want {
					t.Errorf("want %s %s: %v", flag, want, args)
				}
			}
			for _, flag := range tc.switches {
				if !slices.Contains(args, flag) {
					t.Errorf("missing %s: %v", flag, args)
				}
			}
		})
	}

	mini := cfg.Groups["titles"]
	heavy := cfg.Groups["heavy"]
	if mini.Swap || mini.Exclusive || !mini.Persistent || !slices.Equal(mini.Members, []string{"nemotron-mini"}) ||
		!heavy.Swap || !heavy.Exclusive || !slices.Contains(heavy.Members, "halogen-qwen3.8-flash-next") {
		t.Fatalf("unexpected Mini/Flash swap policy: titles=%+v heavy=%+v", mini, heavy)
	}
}

func TestConfig_StrixHaloFluxIsImageModel(t *testing.T) {
	for _, file := range []string{
		filepath.Join("docker", "strix-halo.yaml"),
		filepath.Join("docs", "examples", "alternative-models.yaml"),
	} {
		t.Run(file, func(t *testing.T) {
			cfg, err := LoadConfig(filepath.Join("..", "..", file))
			if err != nil {
				t.Fatal(err)
			}
			model, ok := cfg.Models["flux2-klein-9b"]
			if !ok || !slices.Equal(model.Capabilities.In, []string{"text"}) ||
				!slices.Equal(model.Capabilities.Out, []string{"image"}) || model.UseModelName != "sd-cpp-local" {
				t.Fatalf("unexpected FLUX image route: model present=%v, capabilities=%+v, upstream=%q", ok, model.Capabilities, model.UseModelName)
			}
		})
	}
}
