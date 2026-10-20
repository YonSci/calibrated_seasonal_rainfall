// After `astro build`: figures through <picture> with their WebP copies (scripts/pictures.mjs), then the site-search index
// (Pagefind), written into the build output as pagefind/. Only page content marked data-pagefind-body (the main content of
// every page) is indexed.
import * as pagefind from 'pagefind';
import path from 'node:path';
import { pictures } from './pictures.mjs';

const out = path.resolve(process.env.ASTRO_OUT ?? 'dist');
const pic = pictures(out);
console.log(`Pictures: ${pic.figs} figures with WebP copies on ${pic.pages} pages`);
const { index, errors } = await pagefind.createIndex({});
if (errors?.length) throw new Error(errors.join('; '));
const added = await index.addDirectory({ path: out });
if (added.errors?.length) throw new Error(added.errors.join('; '));
const written = await index.writeFiles({ outputPath: path.join(out, 'pagefind') });
if (written.errors?.length) throw new Error(written.errors.join('; '));
console.log(`Search index: ${added.page_count} pages → ${path.join(out, 'pagefind')}`);
await pagefind.close();
