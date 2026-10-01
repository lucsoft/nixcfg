// One-off importer for the shaders in sources.nix. Not shipped in the package,
// not loaded by the extension — it runs in a browser, once.
//
// Shadertoy sits behind a Cloudflare managed challenge: every path answers 403
// to a plain HTTP client, including /api/v1/ and the front page, because the
// challenge is in front of the application. An API key does not help, because
// the block happens before the request reaches Shadertoy at all. It has to come
// from a browser that has solved the challenge.
//
// No key is needed, though. Run from a shadertoy.com tab, this uses the same
// internal endpoint the site itself uses, same-origin, with the clearance
// cookie the browser already holds.
//
// How to use:
//   1. Open any shadertoy.com page
//   2. Open the browser console
//   3. Paste this file, hit enter
//   4. A shaders.json downloads with every pass of every shader
//
// To automate it instead, start the browser with --remote-debugging-port and
// drive the same expression over CDP — that is how this set was imported.

(async () => {
    const IDS = [
        'Dds3WB', '4ldGDB', '4slXW7', '33cGDj', 'XdVGWt', 'MtSBDc', 'Mt3GWs',
        '4s2yW1', 'llS3RK', 'lslGWr', 'wtfBDf', 'lsBfDz', 'Ndc3zl', 'mds3DX',
        'MdyGzR', '4sK3RD', 'MdKXzc', '4ttGWM', 'XtGGRt', 'XsyGWV', '4sXGRM',
        'lt3XDM', 'MdGfzh', 'XXtBRr', 'MsjSW3', 'XdBSzd', 'MtcGDH', '4tByz3',
        'Xl2XRW', 'lstSRS', '4dcGW2', 'wlVGWd', 'XtdGR7', 'MdBGzG', 'MdlGW7',
        'XlfGRj', 'ftt3R7', 'XsX3RB', 'lsl3RH', 'ltffzl', '3l23Rh', 'mtyGWy',
        'ld3Gz2', 'tdG3Rd',
    ];

    const res = await fetch('/shadertoy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 's=' + encodeURIComponent(JSON.stringify({ shaders: IDS })) +
              '&nt=1&nl=1&np=1',
    });

    if (!res.ok) {
        console.error(`HTTP ${res.status} — run this from a shadertoy.com tab`);
        return;
    }

    const data = await res.json();
    console.log(`${data.length}/${IDS.length} shaders`);

    // Every pass is kept, not just the image one. A shader with a buffer pass
    // or an iChannel input cannot run as a single ClutterShaderEffect, and that
    // has to be visible here rather than at the point where it fails to render.
    for (const s of data) {
        const kinds = s.renderpass.map(p => p.type).join('+');
        console.log(`  ${s.info.id}  ${s.info.name} — ${s.info.username}  [${kinds}]`);
    }

    const url = URL.createObjectURL(
        new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'shaders.json';
    a.click();
    URL.revokeObjectURL(url);
})();
