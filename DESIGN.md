# DESIGN.md — WinCrate

> The shared source of interface values. Read this whole file before UI work.
> Use values by role/token name. Add a missing role here and in code tokens together.
> Do not introduce undocumented interface values.

Updated: 2026-11-14

## Direction

- **Deal:** `deal 16364338 · app`, material 2/3 `linen-press`, rank #3 of 7 (road not taken, #1: dark slate command utility with Inter and electric blue accent)
- **Scene:** A PC builder at their desk migrating installed desktop software to another Windows machine, inspecting folder footprints, toggling AppData configs, and pressing standalone `.exe` setup files.
- **Concept:** A shipping-crate manifest and press ledger printed on unbleached linen stock with charcoal ink and oxidized rust-orange press marks.
- **Qualities:** Utilitarian, ruled, scannable.
- **Avoid:** Neon dark-mode developer dashboards, promotional hero banners inside a working tool, decorative icon tiles.
- **Structure:** Shell command board (queues as columns) opening directly on the work and leading with any compatibility exception that needs a decision before building.
- **Motion:** Mechanical press lever — crisp 80ms downward compression (`--ui-press-down`), damped spring release (`--ui-spring-pop`, 520ms), sliding filter indicator (`--ui-spring-snap`), and determinate press-stage progress bar. No idle pulsing or floating decoration.
- **Signature details:** Ruled footprint ledger table with tabular byte counts and live PE-overlay `.exe` press readout; optional pool effects: none.

## Code tokens

| Platform | File | Naming |
| --- | --- | --- |
| Desktop WebView2 (CSS) | `ui/tokens.css` | `--color-text`, `--space-4`, `--radius-control` |

Units: CSS px at 1x logical DPI (scales natively with Windows display scaling in WebView2).

## Fonts

| Role | Family | Fallback | Weights | Loading | Notes |
| --- | --- | --- | --- | --- | --- |
| UI / text | `Hanken Grotesk` | `Segoe UI Variable Text, Segoe UI, sans-serif` | `400, 500, 600, 700` | Google Fonts stylesheet with immediate system fallback | Sentence case labels, crisp dense rows |
| Mono / numerals | `IBM Plex Mono` | `Cascadia Mono, Consolas, monospace` | `400, 500` | Google Fonts stylesheet with immediate system fallback | `font-variant-numeric: tabular-nums` for byte sizes, file paths, hashes |

No other families. Use tabular numerals for all byte sizes, counts, and percentages.

## Type scale

| Role | Token | Size | Line height | Weight | Tracking | Usage |
| --- | --- | --- | --- | --- | --- | --- |
| h1 | `--type-h1` | `20px` | `1.25` | `600` | `-0.01em` | Selected software title in workbench |
| h2 | `--type-h2` | `15px` | `1.3` | `600` | `0` | Column headers and ledger section titles |
| body | `--type-body` | `14px` | `1.45` | `400` | `0` | Primary list titles, option labels, paths |
| body-small | `--type-small` | `13px` | `1.4` | `400` | `0` | Secondary metadata, publisher, consequences |
| label | `--type-label` | `13px` | `1.2` | `500` | `0` | Buttons, segmented controls, field labels |
| caption | `--type-caption` | `12px` | `1.35` | `400` | `0` | Status tags, tabular byte counts, versions |

## Color

| Role | Token | Value | Usage |
| --- | --- | --- | --- |
| canvas | `--color-canvas` | `#ECEAE4` | App window ground (unbleached linen grey) |
| surface | `--color-surface` | `#F7F6F2` | Primary work panels and sheets |
| surface-raised | `--color-surface-raised` | `#FFFFFF` | Active selected row, inputs, dialog sheet |
| surface-sunken | `--color-surface-sunken` | `#E3E0D8` | Segmented track, progress track, drop zone rest |
| text | `--color-text` | `#191917` | Primary charcoal ink |
| text-muted | `--color-text-muted` | `#53514B` | Publisher, paths, secondary facts |
| border | `--color-border` | `#D2CEC4` | Ruled ledger hairlines and panel dividers |
| border-strong | `--color-border-strong` | `#7D7A71` | Input outlines, checkbox border, drop zone active dash |
| action | `--color-action` | `#B53E19` | Primary rust-orange press button, active selection bar |
| action-subtle | `--color-action-subtle` | `#F6E6DF` | Selected row tint and drag-over highlight |
| on-action | `--color-on-action` | `#FFFFFF` | Label ink on `--color-action` |
| focus | `--color-focus` | `#B53E19` | Focus-visible ring |
| ready-bg | `--color-ready-bg` | `#E3F1E8` | Packable status chip background |
| ready-ink | `--color-ready-ink` | `#1A5432` | Packable status chip text and icon |
| warning-bg | `--color-warning-bg` | `#F8ECD8` | Service/driver warning banner and chip background |
| warning-ink | `--color-warning-ink` | `#6E4208` | Warning banner and chip text and icon |
| danger | `--color-danger` | `#A62424` | Error state text and icon |
| danger-bg | `--color-danger-bg` | `#F9E4E4` | Error banner background |

Measured contrast pairs:

| Pair | Theme | Ratio | Requirement |
| --- | --- | --- | --- |
| `text / canvas` (`#191917` / `#ECEAE4`) | Linen light | `14.63:1` | 4.5:1 |
| `text / surface` (`#191917` / `#F7F6F2`) | Linen light | `16.28:1` | 4.5:1 |
| `text-muted / canvas` (`#53514B` / `#ECEAE4`) | Linen light | `6.60:1` | 4.5:1 |
| `text-muted / surface` (`#53514B` / `#F7F6F2`) | Linen light | `7.34:1` | 4.5:1 |
| `on-action / action` (`#FFFFFF` / `#B53E19`) | Linen light | `5.73:1` | 4.5:1 |
| `action / surface` (`#B53E19` / `#F7F6F2`) | Linen light | `5.29:1` | 4.5:1 |
| `focus / canvas` (`#B53E19` / `#ECEAE4`) | Linen light | `4.76:1` | 3.0:1 (non-text) |
| `border-strong / surface` (`#7D7A71` / `#F7F6F2`) | Linen light | `3.97:1` | 3.0:1 (control boundary) |
| `warning-ink / warning-bg` (`#6E4208` / `#F8ECD8`) | Linen light | `7.35:1` | 4.5:1 |
| `ready-ink / ready-bg` (`#1A5432` / `#E3F1E8`) | Linen light | `7.64:1` | 4.5:1 |
| `danger / surface` (`#A62424` / `#F7F6F2`) | Linen light | `6.70:1` | 4.5:1 |

State never relies on color alone: every status badge pairs text (`Packable`, `Service warning`, `Manual folder`) with a distinct inline SVG glyph.

## Spacing

Scale: `0, 4, 8, 12, 16, 20, 24, 32`.
Tokens: `--space-1: 4px`, `--space-2: 8px`, `--space-3: 12px`, `--space-4: 16px`, `--space-5: 20px`, `--space-6: 24px`, `--space-8: 32px`.

- Inside a control (icon to label, label to value): `8px` (`--space-2`)
- Between items in a group (rows, checkboxes, toolbar buttons): `8px` or `12px` (`--space-2` / `--space-3`)
- Between groups/sections in the workbench: `16px` (`--space-4`)
- Panel container padding: `16px` (`--space-4`) across panel headers, software queue, workbench body, press bar, and crate rail so vertical start/end keylines align across every region; never smaller than internal gaps.
- Siblings of one kind use one gap token inside CSS Flex/Grid containers.

## Alignment and keylines

- Top command bar controls share a single horizontal center line (`height: 36px` controls).
- Software queue rows align icons on keyline `16px`, text column on `56px`, and right-aligned tabular sizes on `right: 16px`.
- Workbench ledger rows use a two-column grid: labels start on the left keyline, values/controls align cleanly on the second column or end edge.
- Buttons in a set share identical height (`36px` md, `42px` lg primary build action).

## Radii

| Role | Token | Value | Usage |
| --- | --- | --- | --- |
| control | `--radius-control` | `6px` | Buttons, inputs, select fields, checkboxes |
| container | `--radius-container` | `10px` | Work panels, exception banners, drop zone |
| overlay | `--radius-overlay` | `12px` | Modal dialogs |
| pill | `--radius-pill` | `9999px` | Switch track, segmented control, status chips |

## Borders and depth

- Hairline: `1px solid var(--color-border)` for ruled panels and ledger rows.
- Interactive fields & checkboxes: `1px solid var(--color-border-strong)` (`3.97:1` contrast).
- Elevation: Flat ruled sheets on canvas; subtle shadow (`0 8px 24px rgb(25 25 23 / 0.12)`) reserved strictly for modal overlays.

## Icons

- Set: Inline Lucide-compatible stroke icons (`stroke-width: 1.75`, `16px` in dense lists/chips/small buttons, `18px` in primary actions). Plus real extracted Windows application icons (`32x32` PNG).
- Never place decorative icons inside colored tiles above headings.

## Components

### Button

| Size | Height | Horizontal padding | Type | Icon | Radius |
| --- | --- | --- | --- | --- | --- |
| sm | `32px` | `12px` | `--type-label` | `16px` | `--radius-control` |
| md | `36px` | `14px` | `--type-label` | `16px` | `--radius-control` |
| lg | `42px` | `20px` | `--type-body` (weight 600) | `18px` | `--radius-control` |

Variants: `primary` (`--color-action`), `secondary` (`--color-surface-raised` + `--color-border-strong`), `ghost`. One primary button (`Build standalone .exe`) on the screen.

### Input & Select

Height `36px`, horizontal padding `12px`, `1px solid var(--color-border-strong)`, `--radius-control`. Persistent visible label above in `--type-label`.

### Switch & Checkbox

Uses `better-design` interaction kit (`.ui-switch` scaled cleanly to `44x26px` and `.ui-check` `20x20px`) mapped to `--color-action` when checked and `--color-border-strong` at rest.

## Layout

- Desktop window default: `1220 × 780`, minimum `960 × 620`.
- Responsive breakpoints:
  - `≥ 1024px`: 3-region shell command board (`360px` Installed Software Queue | `1fr` Package Workbench | `280px` Built `.exe` Crate Rail, collapsible on narrower widths).
  - `768px – 1023px`: 2-column (`320px` Queue | `1fr` Workbench with Built `.exe` section stacked below).
  - `< 768px`: Single-column stacked flow for narrow snapped windows or 150%+ zoom.

## Motion

| Role | Token | Value |
| --- | --- | --- |
| press | `--ui-press-down` / `--ui-release` | `80ms` down / `520ms` `--ui-spring-pop` release |
| micro | `--ui-hover` / `--ui-focus` | `180ms` / `150ms` |
| state | `--ui-state` | `240ms` |
| ease-out | `--ui-ease-out` | `cubic-bezier(0.2, 0, 0, 1)` |

Reduced motion (`prefers-reduced-motion: reduce`) disables scale/translate springs while preserving immediate color/opacity/focus feedback.

## Voice and copy

- Direct workshop labels: "Build standalone .exe", "Include AppData & settings", "Exclude cache & temp folders", "Open output folder".
- Zero page narration, zero marketing slogans, zero paraphrased toggle subtitles. Helper text appears only where it communicates a real technical consequence (e.g., exact AppData byte size added or why Windows services may need original installers).

## Prohibited in this project

- `slop:marketing-in-tool`, `slop:icon-tile`, `slop:cardocalypse`, `slop:ai-palette`, `slop:lazy-cool`, `slop:tracked-caps-label`, `slop:page-narration`, `slop:label-paraphrase`, `slop:pulsing-status-dot`.
