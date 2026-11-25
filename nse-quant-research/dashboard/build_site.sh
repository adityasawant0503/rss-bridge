#!/usr/bin/env bash
# Wrap index.html (written as a page fragment) in a full HTML document and copy
# the script and data next to it, ready for GitHub Pages or any static host.
set -euo pipefail
out=${1:-_site}
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$out/data"
{
  printf '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
  printf '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
  printf '<style>body{margin:0}</style>\n</head>\n<body>\n'
  cat "$here/index.html"
  printf '\n</body>\n</html>\n'
} > "$out/index.html"
cp "$here/lib.js" "$out/"
cp "$here"/data/*.json "$out/data/"
echo "site assembled in $out"
