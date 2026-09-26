#!/usr/bin/env python3
"""night/siegel_facts.py — out/siegel_prereg.json の S1〜S4 の材料を作る（読むだけ・採点に不使用）

dy = 直近FYの配当 ÷ 時価総額 ／ shy = (配当+買戻し−発行) ÷ 時価総額 ／ per ／ cagr5
時価総額 = retro_per の as-of 株価（分割を戻した当時の板の値）× 同じ規約の株数（filed 最古・FY末 ≤ Y-03-01）
⚠ CF は三値読み（retro_features2.flow3）: 触れる報告が無い年は0・触れるのに年次が無ければ欠測（0と読まない）
出力: out/siegel_facts.json
"""
import json, os, sys, zipfile
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'out')
sys.path.insert(0, os.path.join(BASE, 'night'))
_argv = sys.argv; sys.argv = [sys.argv[0]]
import retro_per_asof as RP
import retro_features2 as RF
sys.argv = _argv

def main():
    z = zipfile.ZipFile(os.path.join(BASE, 'companyfacts.zip')); have = set(z.namelist())
    res = {}
    for Y in (2013, 2018):
        per = {r['ticker']: r for r in json.load(open(os.path.join(OUT, f'retro_per_{Y}_all.json')))['rows']}
        cf = os.path.join(OUT, f'retro_cohort_{Y}.json')
        if not os.path.exists(cf): cf = os.path.join(OUT, 'retro_cohort_2013.json')
        t2cik = {r['ticker']: r['cik'] for r in json.load(open(cf))['rows'] if r.get('ticker')}
        feat = {r['ticker']: r for r in json.load(open(os.path.join(OUT, f'retro_features2_{Y}.json')))['rows']}
        rows, miss = {}, {}
        deadline, cutoff = f'{Y}-07-01', f'{Y}-03-01'
        for t, p in sorted(per.items()):
            row = {'per': p['per'], 'px': p['px'], 'fy_end': p['fy_end']}
            if feat.get(t, {}).get('cagr5') is not None: row['cagr5'] = feat[t]['cagr5']
            cik = t2cik.get(t); name = f'CIK{cik:010d}.json' if cik else None
            if not name or name not in have:
                miss[t] = 'no_facts'; rows[t] = row; continue
            facts = json.loads(z.read(name)).get('facts', {})
            sh = RP.latest_before(RP.annual_entries(facts, RP.SH_TAGS, ('shares',)), cutoff)
            if not sh or sh[0] != p['fy_end'] or sh[1] <= 0:
                miss[t] = f'shares_fy_mismatch {sh and sh[0]}'; rows[t] = row; continue
            mcap = p['px'] * sh[1]
            g = facts.get('us-gaap', {})
            fy = int(p['fy_end'][:4])
            d3, b3, i3 = (RF.flow3(g, tags, deadline)(fy) for tags in (RF.DIV, RF.BUY, RF.ISS))
            row['mcap'] = round(mcap)
            if d3[0] != 'miss':
                row['dy'] = round(d3[1] / mcap, 5)
            if all(x[0] != 'miss' for x in (d3, b3, i3)):
                row['shy'] = round((d3[1] + b3[1] - i3[1]) / mcap, 5)
            # 帯検問（桁事故）: 配当利回り 0〜25%・純還元 −50〜50% を外れたら欠測へ
            if row.get('dy') is not None and not (0 <= row['dy'] <= .25):
                miss[t] = f"dy_band {row.pop('dy')}"
            if row.get('shy') is not None and not (-.5 <= row['shy'] <= .5):
                miss[t] = f"shy_band {row.pop('shy')}"
            rows[t] = row
        res[Y] = dict(rows=rows, unmeasured=miss,
                      n=dict(per=len(rows), dy=sum('dy' in r for r in rows.values()),
                             shy=sum('shy' in r for r in rows.values()), cagr5=sum('cagr5' in r for r in rows.values())))
        print(Y, res[Y]['n'], '欠測', len(miss))
    json.dump(dict(generated=__import__('datetime').date.today().isoformat(), tool='night/siegel_facts.py',
                   prereg='out/siegel_prereg.json', anchors=res),
              open(os.path.join(OUT, 'siegel_facts.json'), 'w'), ensure_ascii=False, indent=1)

if __name__ == '__main__':
    main()
