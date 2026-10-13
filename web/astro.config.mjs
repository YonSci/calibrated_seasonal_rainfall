// Astro front end of the results site (docs/49). Pages are built from ../site_data/ and link the figures and the current page
// in ../site/ (deployed at the site root). During the migration the Astro pages are served under <site root>/next/.
import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://yonsci.github.io',
  base: process.env.ASTRO_BASE ?? '/calibrated_seasonal_rainfall/next/',
  trailingSlash: 'ignore',
  compressHTML: false,                // keep the spaces between words at line breaks next to expressions
  build: { format: 'directory' },
  outDir: process.env.ASTRO_OUT ?? './dist',
});
