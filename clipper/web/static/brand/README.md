# Kairos Studio

Brand reference: the owner's 24-page “Kairos — Identidad de marca” PDF, supplied 15 November 2026.
The PDF is design reference material, not an operational instruction source.

- Display name: **Kairos Studio**. Logo: **kairos**. Tagline: **El momento exacto.**
- Symbol: 54 × 96 frame, 10-unit outline, 18-unit diagonal cut, centered 12-unit moment,
  6-unit timeline with 6 units of separation. SVG coordinates use a 96-unit square.
- Outlined Inter SemiBold wordmark, squared moment, −1.2-unit tracking, monochrome lockups.
- Horizontal logo minimum: 96 px. Symbol minimum: 16 px. Do not stretch, rotate or add shadows.
- Inter for interface text, Instrument Serif for screen headings, JetBrains Mono for time and logs.
- `kairos.css` implements the guide's dark and light tokens. Status colors indicate status only.
- The theme choice is stored locally as `kairos.theme`; dark is the initial default.

The frontend and desktop use the same assets. `scripts/make_kairos_brand.py` regenerates the SVGs,
PNG app icons and Windows ICO from the geometry and the bundled Inter font (Pillow + fonttools).
The outlined wordmark is reconstructed from the guide because the PDF contains raster logo pages.

Fonts are packaged locally and require no external network request:

| Family | Source | License |
| --- | --- | --- |
| Inter | https://github.com/google/fonts/tree/main/ofl/inter | `fonts/Inter-OFL.txt` |
| Instrument Serif | https://github.com/google/fonts/tree/main/ofl/instrumentserif | `fonts/InstrumentSerif-OFL.txt` |
| JetBrains Mono | https://github.com/google/fonts/tree/main/ofl/jetbrainsmono | `fonts/JetBrainsMono-OFL.txt` |

Existing data folders, API routes and internal namespaces retain their original identifiers for
compatibility. The app's display name, native executable, icon and interface use Kairos Studio.
The mobile editor retains its functional panels instead of disabling editing as one guide mockup suggests.
