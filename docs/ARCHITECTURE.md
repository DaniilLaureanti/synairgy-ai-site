# SynAirgy site architecture

The project intentionally stays buildless: GitHub Pages serves semantic HTML, layered CSS and native ES modules.

## Layers

- `assets/css/tokens.css` — brand tokens and reusable design values.
- `assets/css/base.css` — reset, accessibility, responsive media and reduced-motion rules.
- `assets/css/components.css` — shared navigation and reusable UI behavior.
- `brand-system.css` — the existing SynAirgy visual language for home, Film & Visual and AI pages.
- `assets/css/pages/` — page-specific exceptions only.
- `assets/js/config.js` — the single source for routes, contacts and social links.
- `assets/js/core.js` — shared progressive enhancement.
- `assets/js/project-builder.js` — reusable project-builder component.
- `assets/js/visual.js` and `assets/js/automation.js` — page composition roots.
- `synairgy-*.css/js` — isolated legacy Sound Lab feature modules; kept separate because its calculator is a self-contained application.

## Adding a page

1. Start from semantic HTML and keep primary copy and fallback links in the document.
2. Load `tokens.css`, `base.css`, `components.css`, then the relevant shared/page styles.
3. Load `core.js` as a module. Add a small page entry module only when the page has behavior.
4. Add reusable routes, social accounts or contact details to `assets/js/config.js`.
5. Use `data-link="group.key"` on centrally configured links. A `null` value becomes an accessible disabled placeholder automatically.

## Constraints

- No framework or build step is required.
- Page URLs and existing content remain stable.
- HTML remains useful without JavaScript; JavaScript only enhances it.
