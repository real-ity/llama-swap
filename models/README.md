# Local model files

For the Strix Halo Compose setup, use the [folder layout and download links
in the quick start](../README.md#strix-halo-quick-start). You can leave this
directory empty if you only want to check that the controller starts.

Keep model files and tokenizer assets out of Git. Compose mounts this directory
read-only, and its build context excludes the entire directory.
