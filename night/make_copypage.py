import json, glob, os
packs={json.load(open(f))['nm']:json.load(open(f)) for f in glob.glob('out/*_gate_pack.json')}
q=json.load(open('gate1_queue.json')); order=[r['ticker'] for r in q]
qb={r['ticker']:r.get('byomei','') for r in q}
names=sorted(packs, key=lambda n: order.index(n) if n in order else 999)

def warn(p):
    a=[]
    if p.get('eq')=='neg': a.append('⚑')
    if p.get('p4') is not None and p['p4']<=50: a.append('誠')
    if p.get('erosion')=='active': a.append('蝕')
    if p.get('expiry')=='yes': a.append('限')
    if isinstance(p.get('geopol'),int) and p['geopol']>=3: a.append('集')
    return a

batches=[]
for i in range(0,len(names),5):
    grp=names[i:i+5]
    arr=[packs[t] for t in grp]
    jtxt=json.dumps(arr,ensure_ascii=False,separators=(',',':'))
    chips=[]
    for t in grp:
        p=packs[t]; w=warn(p)
        chips.append({'t':t,'b':qb.get(t,''),'w':''.join(w)})
    batches.append({'n':len(batches)+1,'chips':chips,'json':jtxt})

# JSはbatchesをそのまま埋め込む
data_js=json.dumps([{'n':b['n'],'json':b['json']} for b in batches],ensure_ascii=False)

def chip_html(c):
    wt=(' <span class="w">'+c['w']+'</span>') if c['w'] else ''
    bm=(' <span class="bm">'+c['b']+'</span>') if c['b'] else ''
    return f'<span class="chip">{c["t"]}{wt}{bm}</span>'

rows=[]
for b in batches:
    chips=''.join(chip_html(c) for c in b['chips'])
    rows.append(f'''<div class="row">
  <div class="num">batch<b>{b['n']:02d}</b></div>
  <div class="chips">{chips}</div>
  <button class="copy" data-n="{b['n']}">コピー</button>
</div>''')

html=f'''<title>CCF Ω 門2審査パック — 5社ずつ取り込み</title>
<style>
:root{{
 --bg:#f4f0e6; --panel:#fbf8f1; --ink:#2b2720; --muted:#7c7566; --gold:#9a7b2e;
 --line:rgba(40,34,24,.12); --good:#3f7d5a; --warn:#b5772f;
 --serif:"Hiragino Mincho ProN","Yu Mincho",Georgia,serif;
 --mono:ui-monospace,"SF Mono",Menlo,monospace;
}}
@media (prefers-color-scheme:dark){{:root{{
 --bg:#14120d; --panel:#1c1913; --ink:#ded7c6; --muted:#8a8272; --gold:#c9a64a;
 --line:rgba(255,255,255,.09); --good:#6fbf8f; --warn:#d99a4e;
}}}}
:root[data-theme="dark"]{{
 --bg:#14120d; --panel:#1c1913; --ink:#ded7c6; --muted:#8a8272; --gold:#c9a64a;
 --line:rgba(255,255,255,.09); --good:#6fbf8f; --warn:#d99a4e;
}}
:root[data-theme="light"]{{
 --bg:#f4f0e6; --panel:#fbf8f1; --ink:#2b2720; --muted:#7c7566; --gold:#9a7b2e;
 --line:rgba(40,34,24,.12); --good:#3f7d5a; --warn:#b5772f;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,sans-serif;line-height:1.5;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:860px;margin:0 auto;padding:32px 20px 80px}}
header h1{{font-family:var(--serif);font-weight:600;font-size:26px;margin:0 0 6px;letter-spacing:.02em}}
header .sub{{color:var(--muted);font-size:13.5px;margin:0 0 4px}}
header .gold{{color:var(--gold)}}
.howto{{margin:18px 0 22px;padding:12px 16px;background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--gold);border-radius:8px;font-size:13px;color:var(--muted)}}
.howto b{{color:var(--ink)}}
.legend{{font-size:11.5px;color:var(--muted);margin:10px 2px 20px;display:flex;gap:14px;flex-wrap:wrap}}
.legend span b{{color:var(--gold);font-family:var(--mono)}}
.row{{display:flex;align-items:center;gap:14px;padding:12px 14px;background:var(--panel);border:1px solid var(--line);border-radius:10px;margin-bottom:9px}}
.num{{font-family:var(--serif);font-size:12px;color:var(--muted);min-width:64px}}
.num b{{display:block;font-size:20px;color:var(--gold);font-variant-numeric:tabular-nums}}
.chips{{flex:1;display:flex;flex-wrap:wrap;gap:6px;min-width:0}}
.chip{{font-family:var(--mono);font-size:12.5px;font-weight:600;padding:3px 8px;background:rgba(201,166,74,.09);border:1px solid var(--line);border-radius:6px;white-space:nowrap}}
.chip .w{{color:var(--warn);font-family:var(--serif);font-weight:400;font-size:11px}}
.chip .bm{{color:var(--muted);font-weight:400;font-size:10.5px}}
button.copy{{font-family:system-ui,sans-serif;font-size:13px;font-weight:600;color:var(--gold);background:linear-gradient(180deg,rgba(201,166,74,.16),rgba(201,166,74,.06));border:1px solid var(--gold);border-radius:8px;padding:9px 18px;cursor:pointer;white-space:nowrap;transition:all .15s}}
button.copy:hover{{background:rgba(201,166,74,.2)}}
button.copy:focus-visible{{outline:2px solid var(--gold);outline-offset:2px}}
button.copy.done{{color:var(--good);border-color:var(--good);background:rgba(111,191,143,.12)}}
.foot{{margin-top:26px;font-size:12px;color:var(--muted);text-align:center}}
@media (max-width:560px){{.row{{flex-wrap:wrap}}.num{{min-width:auto}}.chips{{order:3;flex-basis:100%}}}}
</style>
<div class="wrap">
<header>
 <h1>壊れない複利の門 <span class="gold">·</span> 門2審査パック</h1>
 <p class="sub">完成パック <b class="gold">{len(names)}社</b> を <b class="gold">5社ずつ</b>の一括取込ブロックに。各行の<b class="gold">コピー</b>を押すとJSON配列がクリップボードへ入ります。</p>
</header>
<div class="howto"><b>使い方：</b>行の「コピー」→ 門のⅢ採点機「＋取り込む」に貼る → 次の行へ。5社ずつ台帳に入ります（定性まで充填済み）。市場データ(beta/per/px等)は取込後に手入力。</div>
<div class="legend">
 <span>記号 <b>⚑</b>負資本</span><span><b>限</b>期限独占</span><span><b>蝕</b>侵食active</span><span><b>誠</b>会計p4≤50</span><span><b>集</b>地政学3</span>
</div>
{''.join(rows)}
<div class="foot">CCF Ω · gate2 完成パック · 待ち行列順 · 検死済み（各社の根拠は_meta参照）</div>
</div>
<script>
const B={data_js};
const map=Object.fromEntries(B.map(x=>[x.n,x.json]));
document.querySelectorAll('button.copy').forEach(btn=>{{
  btn.addEventListener('click',async()=>{{
    const n=+btn.dataset.n; const txt=map[n];
    try{{await navigator.clipboard.writeText(txt);}}
    catch(e){{const ta=document.createElement('textarea');ta.value=txt;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();}}
    const o=btn.textContent; btn.textContent='コピー済 ✓'; btn.classList.add('done');
    setTimeout(()=>{{btn.textContent=o;btn.classList.remove('done');}},1600);
  }});
}});
</script>'''
open('out/copy_packs.html','w',encoding='utf-8').write(html)
print('生成: out/copy_packs.html', os.path.getsize('out/copy_packs.html')//1000,'KB /',len(batches),'ブロック')
