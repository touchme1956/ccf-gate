#!/usr/bin/env python3
"""night/nx_jst_data.py — 角度 nx_jst（1870年からの百五十年で国・資産の選び方）のデータを取って揃えるだけの道具（成績は計算しない）

事前登録: out/nx_jst_prereg.json（測る前に書いた）。この道具は
  - Jordà-Schularick-Taylor Macrohistory Database R6（年次・18か国・1870〜2020）を取得（キャッシュ out/_nx_cache/・gitignore）
  - {iso: {年: {列: 値}}} へ揃えて out/_nx_cache/nx_jst_series.json に置く（測る道具 night/nx_jst.py が読む）
  - 形だけを表示する: 列ごとの始まり・終わり・年数・途中の欠け・補間の印・ちょうど0の数・恒等式の食い違いの件数・原本の sha1
平均・t・シャープ・累積・勝率は**計算しない・表示しない**（事前登録の約束）。
欠測は None のまま（0 で埋めない＝絶対のルール7）。

出典: https://www.macrohistory.net/app/download/9834512569/JSTdatasetR6.xlsx
文書: JST_documentationR6.pdf（変数の定義）・JST_RORE_Documentation_R6.pdf（2016〜2020 の延長）・RORE_documentation.pdf（株・国債の出典表）
"""
import sys, os, io, json, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N

URL = 'https://www.macrohistory.net/app/download/9834512569/JSTdatasetR6.xlsx'
OUT = os.path.join(N.CACHE, 'nx_jst_series.json')
COLS = ['eq_tr', 'eq_dp', 'eq_capgain', 'eq_div_rtn', 'eq_tr_interp', 'eq_dp_interp', 'eq_capgain_interp',
        'bond_tr', 'bond_rate', 'bill_rate', 'ltrate', 'stir', 'cpi', 'xrusd', 'gdp', 'pop', 'rgdpmad',
        'tloans', 'tmort', 'thh', 'tbus', 'hpnom', 'housing_tr', 'housing_capgain_ipolated',
        'crisisJST', 'debtgdp', 'ca', 'lev', 'ltd', 'noncore', 'peg', 'safe_tr', 'risky_tr']
# 事前登録の C5 の独立の単位（地域）。測る前に決めた。株のある16か国
UNIVERSE = ['AUS', 'BEL', 'CHE', 'DEU', 'DNK', 'ESP', 'FIN', 'FRA', 'GBR', 'ITA', 'JPN', 'NLD', 'NOR', 'PRT', 'SWE', 'USA']
REGIONS = {'R1_core_europe': ['BEL', 'CHE', 'DEU', 'ESP', 'FRA', 'ITA', 'NLD', 'PRT'],
           'R2_nordic': ['DNK', 'FIN', 'NOR', 'SWE'],
           'R3_anglo_japan': ['AUS', 'GBR', 'JPN', 'USA']}  # CAN・IRL は R6 に株の列が無い


def load():
    import openpyxl
    b = N.get(URL, name='jst_R6.xlsx', max_age_days=3650)
    wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
    rows = wb['Sheet1'].iter_rows(values_only=True)
    head = [str(c) for c in next(rows)]
    ix = {c: i for i, c in enumerate(head)}
    data = {}
    for r in rows:
        if r[ix['year']] is None:
            continue
        iso, y = str(r[ix['iso']]), int(r[ix['year']])
        rec = {}
        for c in COLS:
            v = r[ix[c]] if c in ix else None
            if isinstance(v, str):
                v = v.strip()
                if v in ('', 'NA', '.'):
                    v = None
                else:
                    try:
                        v = float(v)
                    except ValueError:
                        pass  # peg_type 等の文字列はそのまま（COLS には数値列だけを入れている）
            elif v is not None:
                v = float(v)
            rec[c] = v
        data.setdefault(iso, {})[y] = rec
    return b, head, data


def span(d, col):
    ys = sorted(y for y, r in d.items() if isinstance(r.get(col), float))
    if not ys:
        return None
    gaps = [y for y in range(ys[0], ys[-1] + 1) if y not in ys]
    return {'first': ys[0], 'last': ys[-1], 'n': len(ys), 'gaps_inside': gaps}


def main():
    b, head, data = load()
    sha = hashlib.sha1(b).hexdigest()
    json.dump({'source': URL, 'sha1': sha, 'columns_all': head, 'columns_kept': COLS, 'regions': REGIONS, 'universe': UNIVERSE,
               'data': {iso: {str(y): r for y, r in d.items()} for iso, d in data.items()}},
              open(OUT, 'w'), ensure_ascii=False)
    print('JST R6 sha1', sha, 'bytes', len(b), '国', len(data), '→', OUT)
    key = ['eq_tr', 'eq_dp', 'eq_capgain', 'bill_rate', 'bond_tr', 'ltrate', 'cpi', 'xrusd', 'gdp', 'tloans', 'hpnom']
    for iso in sorted(data):
        d = data[iso]
        print(f'\n== {iso}  年 {min(d)}〜{max(d)}')
        for c in key:
            s = span(d, c)
            print(f'  {c:11s}', 'なし' if s is None else f"{s['first']}〜{s['last']} n={s['n']} 途中の欠け={s['gaps_inside']}")
        interp = {c: sorted(y for y, r in d.items() if r.get(c) == 1.0) for c in ('eq_tr_interp', 'eq_dp_interp', 'eq_capgain_interp')}
        print('  補間の印', {k: v for k, v in interp.items() if v})
        zeros = {c: sum(1 for r in d.values() if r.get(c) == 0.0) for c in ('eq_tr', 'eq_dp', 'bill_rate', 'bond_tr')}
        print('  ちょうど0の数', zeros)
        # 恒等式 eq_tr = eq_capgain + eq_div_rtn の食い違い（>0.5pt）の件数だけ（データの整合の確認・成績ではない）
        bad = [y for y, r in d.items() if all(isinstance(r.get(c), float) for c in ('eq_tr', 'eq_capgain', 'eq_div_rtn'))
               and abs(r['eq_tr'] - r['eq_capgain'] - r['eq_div_rtn']) > 0.005]
        print('  恒等式の食い違い(>0.5pt)の年', sorted(bad)[:20], '件数', len(bad))
    # 年ごとの選べる国の数（信号 = 年 t の eq_dp と eq_tr・bill_rate がそろい、翌年 t+1 の eq_tr と bill_rate がある国）
    print('\n== 年ごとの「選べる国」の数（配当利回りの規則の形。成績ではない）')
    line = []
    for y in range(1870, 2020):
        n = 0
        for iso, d in data.items():
            a, z = d.get(y, {}), d.get(y + 1, {})
            if all(isinstance(a.get(c), float) for c in ('eq_dp', 'eq_tr', 'bill_rate')) and all(isinstance(z.get(c), float) for c in ('eq_tr', 'bill_rate')):
                n += 1
        line.append(f'{y}:{n}')
    for i in range(0, len(line), 15):
        print('  ' + ' '.join(line[i:i + 15]))
    print('\n== 年ごとの信用の信号がそろう国の数（tloans と gdp が t−4〜t−1 にそろう・成績ではない）')
    line = []
    for y in range(1870, 2020):
        n = sum(1 for d in data.values() if all(isinstance(d.get(yy, {}).get('tloans'), float) and isinstance(d.get(yy, {}).get('gdp'), float) for yy in range(y - 4, y)))
        line.append(f'{y}:{n}')
    for i in range(0, len(line), 15):
        print('  ' + ' '.join(line[i:i + 15]))


if __name__ == '__main__':
    main()
