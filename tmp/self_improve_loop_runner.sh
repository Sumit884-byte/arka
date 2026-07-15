#!/usr/bin/env bash
cd /Users/sumitmishra/dev/arka
while true; do
  ./venv-arka/bin/arka self improve 2>&1
  sleep 60
done
