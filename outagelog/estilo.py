"""Estilo do relatório (paleta e layout herdados do OutageLog original)."""

CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#6f6d68;--grid:#e1e0d9;--axis:#c3c2b7;
--online:#dcdbd3;--border:rgba(11,11,11,.10);--provider:#2a78d6;--yours:#eb6834;--dns:#1baf7a;--unknown:#eda100}
@media screen and (prefers-color-scheme:dark){:root{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#9a988f;
--grid:#2c2c2a;--axis:#383835;--online:#3a3a37;--border:rgba(255,255,255,.10);--provider:#3987e5;--yours:#d95926;--dns:#199e70;--unknown:#c98500}}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.5 system-ui,-apple-system,'Segoe UI',Ubuntu,sans-serif}
main{max-width:980px;margin:0 auto;padding:32px 16px 48px}
header{margin-bottom:24px}
.eyebrow{margin:0;color:var(--ink2);font-size:13px;letter-spacing:.04em;text-transform:uppercase}
h1{margin:4px 0 6px;font-size:26px;line-height:1.25;font-weight:650}
h2{font-size:17px;margin:0 0 12px;font-weight:650}
.sub,.note,.muted{color:var(--ink2)}
.note{font-size:13px;margin:10px 0 0}
section{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:20px;margin:0 0 16px}
.summary{display:grid;grid-template-columns:minmax(180px,240px) 1fr;gap:20px;align-items:center}
.hero-value{font-size:52px;font-weight:650;line-height:1.05}
.hero-label{color:var(--ink2)}
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.tile{border-left:1px solid var(--grid);padding:2px 0 2px 12px}
.tile-label{color:var(--ink2);font-size:13px}
.tile-value{font-size:20px;font-weight:600}
.tile-note{color:var(--muted);font-size:12px}
.bars{display:grid;gap:10px}
.bar-row{display:grid;grid-template-columns:minmax(200px,300px) 1fr;gap:12px;align-items:center}
.bar-track{display:flex;align-items:center;gap:8px}
.bar{height:20px;border-radius:0 4px 4px 0;min-width:3px}
.bar-value{font-variant-numeric:tabular-nums;white-space:nowrap}
.key{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.s-provider{background:var(--provider);fill:var(--provider)}
.s-yours{background:var(--yours);fill:var(--yours)}
.s-dns{background:var(--dns);fill:var(--dns)}
.s-unknown{background:var(--unknown);fill:var(--unknown)}
.online{background:var(--online);fill:var(--online)}
.nodata{background:var(--surface);box-shadow:inset 0 0 0 1px var(--axis)}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--ink2);margin-bottom:12px}
.timeline{display:grid;gap:6px}
.tl-row{display:grid;grid-template-columns:92px 1fr 120px;gap:10px;align-items:center}
.tl-day{font-size:13px;color:var(--ink2);white-space:nowrap}
.tl-sum{font-size:13px;color:var(--ink2);font-variant-numeric:tabular-nums;white-space:nowrap}
.tl{width:100%;height:20px;display:block}
.tl-bg{fill:var(--surface);stroke:var(--axis);stroke-width:1;vector-effect:non-scaling-stroke}
.tl-ticks{position:relative;height:16px;font-size:11px;color:var(--muted)}
.tl-ticks span{position:absolute;transform:translateX(-50%)}
.tl-ticks span:first-child{transform:none}.tl-ticks span:last-child{transform:translateX(-100%)}
.table-wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:14px}
th{text-align:left;color:var(--ink2);font-weight:600;font-size:13px;border-bottom:1px solid var(--axis);padding:6px 10px 6px 0}
td{border-bottom:1px solid var(--grid);padding:8px 10px 8px 0;vertical-align:top}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.when{white-space:nowrap}
.verdicts{margin:14px 0 0;font-size:13px;color:var(--ink2);display:grid;grid-template-columns:max-content 1fr;gap:6px 14px}
.verdicts dt{color:var(--ink);font-weight:600;white-space:nowrap}.verdicts dd{margin:0}
.method ul{margin:0;padding-left:20px;color:var(--ink2)}.method li{margin:4px 0}
.empty{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:20px}
a{color:var(--provider)}
footer{color:var(--muted);font-size:13px;margin-top:20px}
@media (max-width:640px){.summary{grid-template-columns:1fr}.tiles{grid-template-columns:repeat(2,1fr)}
.bar-row{grid-template-columns:1fr}.tl-row{grid-template-columns:64px 1fr}.tl-sum{display:none}.tl-ticks .minor{display:none}
.idx{display:none}.when span{display:block}.verdicts{grid-template-columns:1fr}.verdicts dd{margin-bottom:6px}h1{font-size:22px}.hero-value{font-size:44px}}
@media print{:root{--page:#fff;--surface:#fff}section{break-inside:avoid;border-color:#ccc}
.s-provider,.s-yours,.s-dns,.s-unknown,.online{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""
