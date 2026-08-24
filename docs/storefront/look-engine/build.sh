#!/bin/bash
# @ledger writes | ./build.sh | Concatenates parts/ into looks-engine.html, then regenerates the contact sheet and this ledger.
set -euo pipefail
out=looks-engine.html
{
  cat parts/01-head.html
  cat parts/06-switches.css
  cat parts/02-body.html
  echo '<script>'
  # DATA: the same file the mini-CMS will edit. Exports stripped so it inlines.
  echo 'const DATA = (() => {'
  sed 's/^export const /const /' data.js
  sed 's/^export const /const /' subjects.js
  echo 'return { SITE, PACKS, CATEGORIES, DOCS, KILL_CAUSES, SUBJECTS, CHECKS, PACK_DETAIL, PUBLISHER }; })();'
  # The palette generator comes before the looks that seed it and the engine that
  # calls it: one <script>, so a `const` used before its line is a dead page.
  cat parts/08-palette.js
  cat parts/03-looks.js
  cat parts/04-plates.js
  cat parts/07-treatments.js
  cat parts/09-roll.js
  cat parts/05-engine.js
  echo '</script>'
} > "$out"
echo "$out: $(wc -c < "$out") bytes"

# The contact sheet is generated from the disk, so it is rebuilt with the
# engine rather than maintained. See gallery.mjs.
bash runlog.sh node gallery.mjs

# The automation ledger: every tool, its own description, and the whole of its last log.
# Generated for the same reason as the contact sheet — a written list of tools is a claim
# about the directory, and the directory moves. See tools.mjs.
# Through runlog too, so the ledger does not list its own generators as NOT RUN while they are
# running. tools.mjs cannot log the run that writes this page — its own log is closed after the
# page is written — so what appears there is the PREVIOUS build, and its timestamp says so.
bash runlog.sh node tools.mjs
