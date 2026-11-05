#!/usr/bin/env bash
# Совместимость: старые инструкции вызывают check-flai.sh.
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/check-llm.sh" "$@"
