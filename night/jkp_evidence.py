#!/usr/bin/env python3
"""night/jkp_evidence.py — JKP（Jensen・Kelly・Pedersen 2023『Is There a Replication Crisis in Finance?』）の
公開データで、門の考え方に当たる因子が『長い歴史・日本・世界』で報われたかを見る（読むだけ・採点に不使用）

データ: https://jkpfactors.com（153因子×93か国・月次・時価加重の上限つき vw_cap・無料）
因子の符号は原論文の予言の向き（正＝予言どおり報われた）。⚠ 売りの側を含む・小型株込み・費用前。
出力: out/jkp_evidence.json
"""
import csv, io, json, math, os, statistics as S, urllib.request, zipfile, datetime
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S3 = 'https://jkpfactors-data.s3.amazonaws.com/public/%5B{r}%5D_%5B{k}%5D_%5Bmonthly%5D_%5Bvw_cap%5D.zip'
REG = {'usa': '米国', 'jpn': '日本', 'world': '世界', 'developed': '先進国', 'emerging': '新興国'}
# 門（とシーゲル）に当たる因子。名前は JKP の短縮名
GATE = {
 'div12m_me': ('配当利回り', 'シーゲル D'), 'eqnpo_me': ('純還元利回り（配当＋買戻し−発行）', '門 shy・シーゲル D の拡張'),
 'ni_me': ('益回り（低PER）', 'シーゲル V'), 'sale_gr3': ('3年売上成長が低い', 'シーゲル 成長の罠'),
 'gp_at': ('粗利÷総資産', '門 GP/A'), 'ope_be': ('営業利益÷自己資本', '門 ROIC の近似'),
 'ebit_sale': ('営業利益率', '門 opm'), 'qmj': ('質（総合）', '門Ω 全体'), 'qmj_prof': ('質・収益性', '門 ROIC・opm'),
 'qmj_growth': ('質・成長', '門 cagr'), 'qmj_safety': ('質・安全性', '門 財務キル'), 'z_score': ('Altman Z', '門 Z'),
 'f_score': ('Piotroski F', '（門に無い）'), 'earnings_variability': ('利益の変動が小さい', '門 p1（ROICの安定）'),
 'at_gr1': ('総資産の伸びが小さい', '門 acqS5 控えめ'), 'netdebt_me': ('純負債÷時価が小さい', '門 nde キル'),
 'debt_gr3': ('負債の伸びが小さい', '門 財務'), 'chcsho_12m': ('株数の増加が小さい', '門 dilNet'),
 'oaccruals_at': ('発生主義の利益が小さい', '門 accr'), 'age': ('上場が新しい（向き−1＝若いほど良いの逆を検定）', '門は歴史を要求'),
 'market_equity': ('小型', '門は規模を問わない'), 'ret_12_1': ('勢い（12-1ヶ月）', '門は株価を見ない'),
 'betabab_1260d': ('低ベータ', '（門に無い）'), 'rd_sale': ('研究開発÷売上', '（門に無い）'),
}

def fetch(r, k):
    z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(S3.format(r=r, k=k), timeout=120).read()))
    rows = csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode()))
    d = {}
    for x in rows:
        m = int(x['date'][:4]) * 100 + int(x['date'][5:7])
        d.setdefault(x['name'], {})[m] = float(x['ret'])
    return d

def summ(s, a=0, b=999999):
    x = [v for m, v in sorted(s.items()) if a <= m <= b]
    if len(x) < 36: return None
    mu, sd, n = S.mean(x) * 12, S.stdev(x) * math.sqrt(12), len(x) / 12
    return {'年数': round(n, 1), '年平均%': round(mu * 100, 2), 't': round(mu / (sd / math.sqrt(n)), 2)}

def three(s):
    return {'始まり': min(s), '全期間': summ(s), '〜2006': summ(s, 0, 200612), '2007〜': summ(s, 200701)}

def main():
    out = {'generated': datetime.date.today().isoformat(), 'source': 'jkpfactors.com（vw_cap・月次）', 'themes': {}, 'factors': {}, 'census': {}}
    for r, lab in REG.items():
        th = fetch(r, 'all_themes')
        out['themes'][lab] = {k: three(s) for k, s in th.items()}
        fa = fetch(r, 'all_factors')
        out['factors'][lab] = {k: dict(three(fa[k]), 意味=GATE[k][0], 門=GATE[k][1]) for k in GATE if k in fa}
        # 153因子の棚卸し: 2006年までに t≥2 だった因子は、2007年以降も正か
        pre = {k: summ(s, 0, 200612) for k, s in fa.items()}; post = {k: summ(s, 200701) for k, s in fa.items()}
        sig = [k for k, v in pre.items() if v and v['t'] >= 2]
        out['census'][lab] = {'因子数': len(fa), '〜2006でt≥2': len(sig),
                              'そのうち2007〜も正': sum(1 for k in sig if post.get(k) and post[k]['年平均%'] > 0),
                              'そのうち2007〜もt≥2': sum(1 for k in sig if post.get(k) and post[k]['t'] >= 2),
                              '2007〜の平均の縮み率(中央)': round(S.median(post[k]['年平均%'] / pre[k]['年平均%'] for k in sig if post.get(k)), 2) if sig else None}
        print(lab, out['census'][lab])
    json.dump(out, open(os.path.join(BASE, 'out', 'jkp_evidence.json'), 'w'), ensure_ascii=False, indent=1)
    f = lambda v: '   —     ' if not v else f"{v['年平均%']:+5.1f}({v['t']:+4.1f})"
    print('\n■ テーマ（年平均%(t)）  全期間 / 〜2006 / 2007〜')
    for lab, ts in out['themes'].items():
        print(' ', lab)
        for k, v in ts.items(): print(f"    {k:22} {v['始まり']//100}〜 {f(v['全期間'])} {f(v['〜2006'])} {f(v['2007〜'])}")
    print('\n■ 門に当たる因子')
    for k in GATE:
        print(f"  {GATE[k][0]}〔{GATE[k][1]}〕")
        for lab in ('米国', '日本', '世界'):
            v = out['factors'][lab].get(k)
            if v: print(f"     {lab:4} {v['始まり']//100}〜 全 {f(v['全期間'])}  〜2006 {f(v['〜2006'])}  2007〜 {f(v['2007〜'])}")

if __name__ == '__main__':
    main()
