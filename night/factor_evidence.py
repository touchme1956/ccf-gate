#!/usr/bin/env python3
"""night/factor_evidence.py — 公開の因子データで「門の考え方は長い歴史・他の国で報われたか」を見る（読むだけ）

データ（どれも無料・公開）:
  Kenneth R. French Data Library … 米国（1926/1963〜）・日本・米国外先進国・欧州・アジア太平洋・新興国（1990〜）
  AQR 'Quality Minus Junk' … 質（収益性・成長・安全性・還元）の因子・24か国（米国は1957〜）
出す数字: 年平均の差・年ごとのぶれ・t値（偶然と区別できるか＝|t|≥2 が目安）・2006年までと2007年以降・
          t=2 に要る年数（(2×ぶれ÷差)²）。⚠ 因子は『良い群を買い・悪い群を売る』の差で、売りの側も含む
出力: out/factor_evidence.json
"""
import io, json, math, os, statistics as S, urllib.request, zipfile, datetime
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FR = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{}_CSV.zip'
QMJ = 'https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Quality-Minus-Junk-Factors-Monthly.xlsx'
UA = {'User-Agent': 'Mozilla/5.0'}
GATE = {'HML': '割安（低PBR）＝シーゲルの低PER。門Ωは価格を見ない',
        'RMW': '収益性（営業利益÷自己資本）＝門の ROIC 柱',
        'CMA': '投資の控えめ（総資産の伸びが小さい）＝acqS5「控えめ」・のれんの罰',
        'SMB': '小型株。門は規模を採点に使わない',
        'Mom': '勢い（過去12ヶ月の値上がり）。門は株価を採点に使わない',
        'QMJ': '質（収益性・成長・安全性・還元）＝門Ω全体にいちばん近い'}

def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()

def french(name):
    z = zipfile.ZipFile(io.BytesIO(get(FR.format(name))))
    L = z.read(z.namelist()[0]).decode('latin-1').split('\n')
    i = next(k for k, l in enumerate(L) if l.strip().startswith(',') and len(l.split(',')) > 1)
    hdr = [h.strip() for h in L[i].split(',')]; d = {}
    for l in L[i + 1:]:
        p = [x.strip() for x in l.split(',')]
        if len(p) < 2 or not (p[0].isdigit() and len(p[0]) == 6): break
        for h, v in zip(hdr[1:], p[1:]):
            if float(v) > -99: d.setdefault(h, {})[int(p[0])] = float(v) / 100
    return d

def qmj():
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(get(QMJ)), read_only=True)
    rows = list(wb['QMJ Factors'].iter_rows(values_only=True))
    h = next(k for k, r in enumerate(rows) if r and r[0] == 'DATE')
    cols = rows[h]; d = {}
    for r in rows[h + 1:]:
        if not r or not r[0]: continue
        m = int(r[0][6:10]) * 100 + int(r[0][0:2])
        for c, v in zip(cols[1:], r[1:]):
            if c and v is not None: d.setdefault(c, {})[m] = float(v)
    return d

def summ(s, a=0, b=999999):
    x = [v for m, v in sorted(s.items()) if a <= m <= b]
    if len(x) < 36: return None
    mu, sd, n = S.mean(x) * 12, S.stdev(x) * math.sqrt(12), len(x) / 12
    return {'年数': round(n, 1), '年平均の差%': round(mu * 100, 2), 'ぶれ%': round(sd * 100, 1),
            't': round(mu / (sd / math.sqrt(n)), 2), 't2に要る年数': round((2 * sd / mu) ** 2) if mu > 0 else None}

def main():
    out = {'generated': datetime.date.today().isoformat(), 'gate_mapping': GATE, 'french': {}, 'qmj': {}}
    sets = [('米国', 'F-F_Research_Data_5_Factors_2x3', 'F-F_Momentum_Factor'), ('日本', 'Japan_5_Factors', 'Japan_MOM_Factor'),
            ('米国外先進国', 'Developed_ex_US_5_Factors', 'Developed_ex_US_MOM_Factor'), ('欧州', 'Europe_5_Factors', None),
            ('アジア太平洋(日本除く)', 'Asia_Pacific_ex_Japan_5_Factors', None), ('新興国', 'Emerging_5_Factors', 'Emerging_MOM_Factor')]
    for reg, f5, fm in sets:
        d = french(f5)
        if fm:
            m = french(fm); d['Mom'] = m.get('Mom') or m.get('WML') or next(iter(m.values()))
        out['french'][reg] = {}
        for k in ('HML', 'RMW', 'CMA', 'SMB', 'Mom'):
            if k not in d: continue
            out['french'][reg][k] = {'全期間': summ(d[k]), '〜2006': summ(d[k], 0, 200612), '2007〜': summ(d[k], 200701),
                                     '始まり': min(d[k])}
    # 米国の長い系列（HML・Mom は 1926〜）
    ff3 = french('F-F_Research_Data_Factors')
    mom = french('F-F_Momentum_Factor'); mom = mom.get('Mom') or next(iter(mom.values()))
    out['french']['米国(1926〜)'] = {k: {'全期間': summ(s), '〜2006': summ(s, 0, 200612), '2007〜': summ(s, 200701), '始まり': min(s)}
                                  for k, s in (('HML', ff3['HML']), ('SMB', ff3['SMB']), ('Mom', mom))}
    q = qmj()
    for c, s in q.items():
        out['qmj'][c] = {'全期間': summ(s), '〜2006': summ(s, 0, 200612), '2007〜': summ(s, 200701), '始まり': min(s)}
    cty = [c for c in q if len(c) == 3 and c.isupper()]
    out['qmj_countries'] = {'国の数': len(cty), '全期間で正': sum(1 for c in cty if (out['qmj'][c]['全期間'] or {}).get('年平均の差%', 0) > 0),
                            '2007〜で正': sum(1 for c in cty if (out['qmj'][c]['2007〜'] or {}).get('年平均の差%', 0) > 0)}
    json.dump(out, open(os.path.join(BASE, 'out', 'factor_evidence.json'), 'w'), ensure_ascii=False, indent=1)
    f = lambda r: '—' if not r else f"{r['年平均の差%']:+5.1f} t{r['t']:+5.1f}"
    for reg, ks in out['french'].items():
        print(f'■ {reg}')
        for k, r in ks.items(): print(f"   {k:4} {r['始まり']}〜  全 {f(r['全期間'])}  〜2006 {f(r['〜2006'])}  2007〜 {f(r['2007〜'])}  t2に要る年数 {(r['全期間'] or {}).get('t2に要る年数')}")
    print('■ QMJ（質）')
    for c in ('USA', 'JPN', 'Global', 'Global Ex USA', 'Europe', 'Pacific'):
        r = out['qmj'].get(c)
        if r: print(f"   {c:14} {r['始まり']}〜  全 {f(r['全期間'])}  〜2006 {f(r['〜2006'])}  2007〜 {f(r['2007〜'])}")
    print('  ', out['qmj_countries'])

if __name__ == '__main__':
    main()
