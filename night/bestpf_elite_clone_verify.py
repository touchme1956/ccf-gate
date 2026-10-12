#!/usr/bin/env python3
"""night/bestpf_elite_clone_verify.py — R2 elite_clone の検算（読むだけ）

本体（night/bestpf_elite_clone.py）とは別の書き方で『各運用者の写し（O・費用前）』を作り直し、月ごとのリターンを突き合わせる。
  - 13F の行は本体の clean_rows を使わずに自分で読む（SH・プット/コールでない・題名に優先株/社債/ワラントの語が無い・名前に ETF/投信の語が無い）
  - 訂正（13F-HR/A）は使わない（原本だけ）＝本体との差の一部はここから来る
  - 会社のまとめ（同じ会社の別の種類株）はしない（CUSIP ごと）
  - 株価は Yahoo の JSON を自分で読む（adjclose の月末どうしの比）。記号は本体と同じ resolved.json（照合の道具は共有）
  - 持ち方: 提出日の翌月から次の提出が効く前の月まで買って持つ（比重は漂う）。価格の欠けた株は外して按分（O）
出力: out/_bestpf_cache/elite_clone/verify.json（作業用）と標準出力の要約。本体の JSON に要約を写すのは本体の --calc が読む
"""
import datetime, json, math, os, re, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bestpf_elite_clone as E  # noqa: E402  （場所と定数だけを借りる）

BAD_TITLE = re.compile(r'\b(PFD|PREF|PREFERRED|NOTE|NOTES|BOND|DEBT|DBCV|SDCV|WT|WTS|WARRANT|WARRANTS|RIGHT|RIGHTS|CALL|PUT)\b', re.I)
FUNDISH = re.compile(r'\b(ETF|ETN|ISHARES|SPDR|PROSHARES|POWERSHARES|VANGUARD|SELECT SECTOR|INDEX FD|INDEX FUND|FUND|FUNDS|FD|FDS|TRUST UNIT)\b', re.I)
END = E.END


def ym_add(m, k):
    t = m // 100 * 12 + m % 100 - 1 + k
    return t // 12 * 100 + t % 12 + 1


_px = {}


def monthly(sym):
    """Yahoo の JSON（本体と同じキャッシュの場所）→ {yyyymm: その月のリターン}（欠けた月をまたがない）"""
    if sym in _px:
        return _px[sym]
    out = None
    p = E._yh_path(sym)
    if os.path.exists(p):
        try:
            j = json.load(open(p))
            r = j['chart']['result'][0]
            ts = r.get('timestamp') or []
            adj = (r['indicators'].get('adjclose') or [{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
            lv = {}
            for t, a in zip(ts, adj):
                if a:
                    d = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
                    k = d.year * 100 + d.month
                    if k <= END:
                        lv[k] = a
            ks = sorted(lv)
            out = {}
            for a0, k in zip(ks, ks[1:]):
                if ym_add(a0, 1) == k and k >= 201301:
                    x = lv[k] / lv[a0] - 1
                    if x > 3.0:          # 本体（mw_best_ideas_13f.yh_load）と同じ跳ねの扱い: +300% 超の月から先は未観測
                        break
                    out[k] = x
            out = (out, set(lv))
        except Exception:  # noqa
            out = None
    _px[sym] = out
    return out


def main():
    man = json.load(open(os.path.join(E.C, 'manifest.json')))['filings']
    res = E.load_resolved()
    by = defaultdict(list)
    for x in man:
        if x['form'] != '13F-HR':
            continue
        f = json.load(open(os.path.join(E.FILD, x['acc'] + '.json')))
        pos = defaultdict(float)
        for r in f['rows'] or []:
            try:
                v = float(r['value'] or 0); sh = float(r['sh'] or 0)
            except ValueError:
                continue
            if r['putcall'] or (r['shtype'] or '').upper() != 'SH' or v <= 0 or sh <= 0:
                continue
            if BAD_TITLE.search(r['title'] or '') or FUNDISH.search((r['name'] or '') + ' ' + (r['title'] or '')):
                continue
            cu = re.sub(r'[^0-9A-Z]', '', (r['cusip'] or '').upper())
            if len(cu) == 9:
                pos[cu] += v
        y, mo = int(x['filed'][:4]), int(x['filed'][5:7])
        by[x['code']].append({'P': int(x['period'][:4]) * 100 + int(x['period'][5:7]), 'eff': ym_add(y * 100 + mo, 1), 'pos': dict(pos)})
    out = {}
    for code, fl in by.items():
        fl.sort(key=lambda r: (r['eff'], r['P']))
        # 同じ月に効く提出が複数なら最後のもの・期間が戻る提出は使わない
        seq = []
        for r in fl:
            if seq and r['P'] <= seq[-1]['P']:
                continue
            if seq and r['eff'] == seq[-1]['eff']:
                seq[-1] = r; continue
            seq.append(r)
        ser = {}
        for i, r in enumerate(seq):
            end = ym_add(seq[i + 1]['eff'], -1) if i + 1 < len(seq) else END
            # 古くなりすぎた提出（期間の末から9か月）は使わない＝本体と同じ線
            ms = []
            m = r['eff']
            while m <= min(end, END):
                if (m // 100 - r['P'] // 100) * 12 + m % 100 - r['P'] % 100 <= E.STALE_MONTHS:
                    ms.append(m)
                m = ym_add(m, 1)
            if not ms:
                continue
            f = ym_add(ms[0], -1)
            tot = sum(r['pos'].values())
            if tot <= 0:
                continue
            v = {}
            for cu, val in r['pos'].items():
                sym = res.get((cu, r['P']))
                d = monthly(sym) if sym else None
                if d and f in d[1]:
                    v[cu] = (val / tot, d[0])
            s = sum(w for w, _ in v.values())
            if s <= 0:
                continue
            val = {cu: w / s for cu, (w, _) in v.items()}
            for m in ms:
                obs = {cu: v[cu][1][m] for cu in val if m in v[cu][1]}
                b = sum(val[cu] for cu in obs)
                if b <= 0:
                    break
                R = sum(val[cu] * obs[cu] for cu in obs) / b
                tot2 = sum(val[cu] * (1 + obs[cu]) for cu in obs)
                val = {cu: val[cu] * (1 + obs[cu]) / tot2 for cu in obs}
                ser[m] = R
        out[code] = ser
    json.dump({c: {str(k): v for k, v in s.items()} for c, s in out.items()}, open(os.path.join(E.C, 'verify.json'), 'w'))
    # 本体と突き合わせ
    main_ = json.load(open(E.OUT))
    rows = []
    for code, ser in out.items():
        mm = main_['series']['copies'].get(code, {}).get('O_gross', {})   # 本体の写しの費用前（O）
        ks = sorted(set(int(k) for k in mm) & set(ser))
        if len(ks) < 24:
            continue
        a = [ser[k] for k in ks]; b = [mm[str(k)] for k in ks]
        ga = math.exp(sum(math.log1p(x) for x in a) * 12 / len(ks)) - 1
        gb = math.exp(sum(math.log1p(x) for x in b) * 12 / len(ks)) - 1
        mx = sum(x for x in a) / len(a); my = sum(y for y in b) / len(b)
        cv = sum((x - mx) * (y - my) for x, y in zip(a, b))
        vx = sum((x - mx) ** 2 for x in a); vy = sum((y - my) ** 2 for y in b)
        rows.append({'code': code, 'months_common': len(ks), 'months_main': len(mm), 'months_verify': len(ser),
                     'cagr_verify': round(ga * 100, 2), 'cagr_main_gross': round(gb * 100, 2), 'diff': round((gb - ga) * 100, 2),
                     'corr': round(cv / math.sqrt(vx * vy), 4) if vx > 0 and vy > 0 else None})
    rows.sort(key=lambda r: -abs(r['diff']))
    diffs = sorted(abs(r['diff']) for r in rows)
    summ = {'n': len(rows), 'median_abs_diff_cagr': diffs[len(diffs) // 2], 'p90_abs_diff': diffs[int(len(diffs) * 0.9)],
            'max_abs_diff': diffs[-1], 'median_corr': sorted(r['corr'] for r in rows if r['corr'] is not None)[len(rows) // 2],
            'n_abs_diff_gt_1pt': sum(1 for d in diffs if d > 1.0), 'largest': rows[:8]}
    json.dump({'summary': summ, 'rows': rows}, open(os.path.join(E.C, 'verify_summary.json'), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(summ, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
