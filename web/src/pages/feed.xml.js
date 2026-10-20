// Atom feed of the site's releases (site_data/site.json): one entry per release with what changed, so readers and
// partner sites can follow new outlooks, verifications and method evidence. Served at <base>/feed.xml.
import { SITE, ROOT } from '../lib/data.js';

const SITE_NAME = 'Seasonal Rainfall Outlook Platform';
const xml = (s) => String(s ?? '').replace(/[<>&'"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', "'": '&apos;', '"': '&quot;' }[c]));

export function GET({ site }) {
  const origin = (site ?? new URL('https://yonsci.github.io')).origin;
  const base = origin + ROOT;
  const TYPES = SITE.change_types ?? {};
  const releases = [...SITE.releases].reverse().slice(0, 40);
  const stamp = (r, i) => (i === 0 && SITE.built_utc ? SITE.built_utc.replace(' UTC', '').replace(' ', 'T') + ':00Z' : `${r.date}T12:00:00Z`);
  const entries = releases.map((r, i) => {
    const link = `${base}releases/#release-${r.id}`;
    const body = `<p>${xml(r.title)}</p><ul>${(r.changes ?? []).map((c) => `<li><strong>${xml(TYPES[c.type] ?? c.type)}:</strong> ${xml(c.text)}</li>`).join('')}</ul>` +
      (r.cycles ? `<p>Cycles: ${xml(r.cycles.join(', '))}</p>` : '');
    return `  <entry>
    <title>${xml(`Release ${r.id}: ${r.title}`)}</title>
    <id>tag:yonsci.github.io,${r.date}:calibrated_seasonal_rainfall/release/${xml(r.id)}</id>
    <link rel="alternate" type="text/html" href="${xml(link)}"/>
    <updated>${stamp(r, i)}</updated>
    ${(r.changes ?? []).map((c) => `<category term="${xml(c.type)}" label="${xml(TYPES[c.type] ?? c.type)}"/>`).join('')}
    <content type="html">${xml(body)}</content>
  </entry>`;
  });
  const out = `<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>${SITE_NAME}: releases</title>
  <subtitle>Calibrated ECMWF SEAS5 seasonal rainfall outlooks for Ethiopia: new outlooks, verifications and method evidence. Research reconstructions; not official EMI or ICPAC forecasts.</subtitle>
  <id>tag:yonsci.github.io,2026:calibrated_seasonal_rainfall/feed</id>
  <link rel="self" type="application/atom+xml" href="${base}feed.xml"/>
  <link rel="alternate" type="text/html" href="${base}"/>
  <updated>${releases.length ? stamp(releases[0], 0) : new Date().toISOString()}</updated>
  <author><name>${SITE_NAME}</name></author>
${entries.join('\n')}
</feed>
`;
  return new Response(out, { headers: { 'Content-Type': 'application/atom+xml; charset=utf-8' } });
}
