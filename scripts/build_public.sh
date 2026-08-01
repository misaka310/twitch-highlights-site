#!/usr/bin/env sh
set -eu

PYTHON_BIN="${PYTHON_BIN:-python}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  else
    echo "error: python runtime is required for build_public.sh"
    exit 2
  fi
fi

if ! command -v node >/dev/null 2>&1; then
  echo "error: Node.js 20 or later is required for build_public.sh"
  exit 2
fi

copy_json_without_bom() {
  src_path="$1"
  dest_path="$2"
  "${PYTHON_BIN}" - "$src_path" "$dest_path" <<'PY'
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
text = src.read_text(encoding="utf-8-sig")
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(text, encoding="utf-8")
PY
}

rm -rf public
mkdir -p public/data public/js

cp site/index.html public/
cp site/styles.css public/
cp site/favicon.svg public/
if [ -f site/bg-desktop.png ]; then
  cp site/bg-desktop.png public/
fi
if [ -f site/bg-mobile.png ]; then
  cp site/bg-mobile.png public/
fi
if [ -d site/assets ]; then
  mkdir -p public/assets
  cp -R site/assets/. public/assets/
fi

copy_json_without_bom data/vods.json public/data/vods.json
if [ -f data/vod_index.json ]; then
  copy_json_without_bom data/vod_index.json public/data/vod_index.json
fi
if [ -d data/vods ]; then
  mkdir -p public/data/vods
  find data/vods -maxdepth 1 -type f -name "*.json" | while IFS= read -r src_json; do
    [ -n "$src_json" ] || continue
    copy_json_without_bom "$src_json" "public/data/vods/$(basename "$src_json")"
  done
fi
if [ -d data/segment-thumbnails ]; then
  mkdir -p public/data/segment-thumbnails
  cp -R data/segment-thumbnails/. public/data/segment-thumbnails/
fi

for js_file in site/js/*.js; do
  cp "$js_file" public/js/
done

node scripts/export-site-config.mjs public/site-config.json
