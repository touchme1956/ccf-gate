#!/usr/bin/env python3
"""night/mw_summary.py — 『市場に勝てる歴史検証』(mw_*) の全角度を一枚の台帳にまとめる（読むだけ・判定には不使用）

入力: out/mw_<角度>.json（研究側の tested）と out/mw_<角度>_verify.json（反証の検証の verdicts）
出力: out/mw_summary.json と標準出力の表
- 研究側の格付けの数（S/A/B/C）と、反証の検証の後の格付け（研究側の格付け → 検証後）を並べる
- 検証が付いていない S/A は『未検証』と明示する（黙って勝ちに数えない）
- 試した本数はプログラム全体の多重検定の母数（Bonferroni の線）に使う
"""
import glob, json, math, os, datetime
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'out')


def grade_of(x):
    g = str(x or '').strip()
    return g[:1] if g[:1] in 'SABC' else ('N' if g else '?')


def research_rows(d):
    t = d.get('tested')
    rows = []
    if isinstance(t, list):
        for s in t:
            if not isinstance(s, dict):
                continue
            name = s.get('id') or s.get('name') or s.get('key')
            rows.append((str(name), grade_of(s.get('grade')), s))
    elif isinstance(t, dict):
        for k, s in t.items():
            if isinstance(s, dict):
                rows.append((str(k), grade_of(s.get('grade')), s))
    return rows


def verify_rows(v):
    vd = v.get('verdicts') or v.get('verdicts_written_after_seeing_numbers')
    out = []
    if isinstance(vd, dict):
        for k, x in vd.items():
            if isinstance(x, dict):
                out.append((str(k), grade_of(x.get('claimed_grade')), grade_of(x.get('verified_grade')), x))
    elif isinstance(vd, list):
        for x in vd:
            if isinstance(x, dict):
                out.append((str(x.get('name')), grade_of(x.get('claimed_grade')), grade_of(x.get('verified_grade')), x))
    return out


def main():
    angles = sorted({os.path.basename(p)[3:-5] for p in glob.glob(os.path.join(OUT, 'mw_*.json'))
                     if 'prereg' not in p and not p.endswith('_verify.json') and not p.endswith('mw_summary.json')})
    table, total = [], 0
    for a in angles:
        d = json.load(open(os.path.join(OUT, f'mw_{a}.json')))
        rows = research_rows(d)
        n = d.get('n_tested') if isinstance(d.get('n_tested'), int) else len(rows)
        total += n or 0
        counts = {g: sum(1 for _, gg, _ in rows if gg == g) for g in 'SABC'}
        vp = os.path.join(OUT, f'mw_{a}_verify.json')
        ver = verify_rows(json.load(open(vp))) if os.path.exists(vp) else None
        after = {}
        if ver:
            for name, cg, vg, x in ver:
                after[name] = {'claimed': cg, 'verified': vg, 'verdict': str(x.get('verdict') or '')[:120]}
        surv = sorted([k for k, v in after.items() if v['verified'] in ('S', 'A')])
        table.append({'angle': a, 'n_tested': n, 'research_grades': counts, 'verified': bool(ver),
                      'verify_counts': ({g: sum(1 for v in after.values() if v['verified'] == g) for g in 'SABC'} if ver else None),
                      'survivors_SA_after_verify': surv, 'verdicts': after})
    bonf_t = None
    if total:
        # 両側 0.05 の Bonferroni の線（正規近似）
        p = 0.05 / total
        lo, hi = 0.0, 10.0
        for _ in range(80):
            mid = (lo + hi) / 2
            if math.erfc(mid / math.sqrt(2)) > p:
                lo = mid
            else:
                hi = mid
        bonf_t = round(hi, 2)
    res = {'generated': datetime.date.today().isoformat(), 'tool': 'night/mw_summary.py', 'program_tests_total': total,
           'bonferroni_t_program_wide': bonf_t, 'angles': table}
    json.dump(res, open(os.path.join(OUT, 'mw_summary.json'), 'w'), ensure_ascii=False, indent=1)
    print(f"角度 {len(table)}・試した本数 {total}・プログラム全体の Bonferroni の線 t≈{bonf_t}")
    for r in table:
        c = r['research_grades']; vc = r['verify_counts']
        vtxt = f"検証後 S{vc['S']} A{vc['A']} B{vc['B']} C{vc['C']}" if vc else '検証なし'
        print(f"  {r['angle']:16} n={r['n_tested']:4}  研究 S{c['S']} A{c['A']} B{c['B']} C{c['C']}  → {vtxt}  残った S/A: {', '.join(r['survivors_SA_after_verify'][:6])}")


if __name__ == '__main__':
    main()
