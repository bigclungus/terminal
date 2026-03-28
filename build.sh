#!/usr/bin/env bash
# Build TypeScript sources to browser JS
set -euo pipefail
cd "$(dirname "$0")"
bun build src/gamecube-sounds.ts --outdir . --target browser --format iife
echo "terminal: build complete"
