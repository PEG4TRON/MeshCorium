# Validation Report

Validation was performed before the archive was packaged.

## Verified conditions

- all 29 substantive articles exist and contain a level-one heading;
- no Markdown file is empty;
- all relative links to local articles, directories, and images resolve;
- all 12 files in `attachments/` are valid parseable SVG/XML;
- every SVG was rendered to PNG for visual inspection after translation;
- no Cyrillic text remains in Markdown or SVG files;
- the shortest substantive article contains more than 850 words;
- file and directory names use portable ASCII characters;
- the archive contains one root directory named `Radio/` and can be extracted directly into a `wiki/` directory.

## What validation does not guarantee

- that a particular frequency, EIRP, or duty cycle is legal in the reader's jurisdiction;
- that every feature is available on every board or in every third-party firmware build;
- that future MeshCore releases will remain compatible with the documented structures;
- that the official project will not change after June 30, 2026.

Version- or build-dependent parameters are identified as such in the articles and should be checked against `ver`, `board`, and the documentation for the installed firmware.
