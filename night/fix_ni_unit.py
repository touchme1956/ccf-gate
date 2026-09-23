#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ni/fcf が **百万$** で入っているパックを十億$へ揃える（2026-08-20 ユーザー指示「IRMD直して」）

★何が起きていたか
  `ccfMcapUSD`（v9.9.146）は時価総額を `px × ni ÷ eps` で作る。**ni は十億$の前提**だが、
  一部のパックは **ni も fcf も 百万$** で入っている。実測 **IRMD**: 87.4×22.5÷1.76 = **1,117十億$**
  ＝ MSFT級に化け、配分の **T1（≥1兆$）で 6.78%** を受けていた（実体 1.23十億$＝T5）。

★なぜ長く見えなかったか（これが本題）
  `night/backfill_machine_evidence.py` は fcf/ni を**比でしか判定しない**（絶対値で突き合わせると
  単位差だけで全社が作業リストに乗り「鳴りすぎる警報は鳴らないのと同じ」になるため）。
  そのうえ一致した社へ **「門はfcf/niを比でしか使わないため、パック側の単位規約はそのまま。比は一致」**
  という注記を刻んでいた。＝**単位の食い違いを知ったうえで、実害が無いという理由で許していた。**
  その前提は **v9.9.146 が絶対値を使う消費者(ccfMcapUSD)を足した時点で崩れた**が、誰も戻って見なかった。
  CLAUDE.md 自身が書いている「**既知の穴は但し書きではなくガードで塞ぐこと**」の実例。

★直し方（推測しない・ルール7）
  **ちょうど1000で割り、桁数はそのまま**にする（22.5 → 0.0225 ／ 17.1 → 0.0171）。
  ＝**値は正しく、単位の札だけが違った**という診断そのもの。`conv = fcf/ni` は**恒等的に不変**なので
  **Ωは1ptも動かない**（門は fcf/ni を比でしか使わない＝上の注記が述べていたことは、この意味では正しかった）。
  raw/1e9 へ丸め直す案は採らない——conv が 0.760→0.764 と動き、**単位の是正が値の変更に化ける**。

★証拠は二つ独立に要る（片方だけでは書かない）
  (1) **内部矛盾**: パック自身の `_meta.evidence.ni` が述べる実額 ÷1e9 と、格納値が 1000倍ずれる
  (2) **桁の照合**: `px×ni÷eps` がパック自身の `mcap` 欄の 100倍以上に出る
  ⚠**日本株は対象外**——EDINET由来の evidence は実額を**千円**で書くので value=raw/1e6 が正しい
  （実測 6861: 値445.2 / 実額445,185千円）。ここを外さないと正しい社を壊す。
  ★**日本株は別の証拠で裁く（2026-09-23 追加）**——16パックが `_meta.unit` に**自分で『百万円』と申告**したまま
  ni/fcf を百万円で持っていた（実測 2477: px 2349×ni 1067÷eps 179 = 14,002十億円＝¥14兆の小型株）。
  申告された単位そのものが演繹的な証拠なので、`_meta.unit` が『百万円』を名乗り『十億円』を名乗らない日本株パックだけを
  ちょうど1000で割り、unit の札を十億円へ書き換える（evidence の実額が千円である社＝unit が『JPY』の社には触れない）。

使い方: python3 night/fix_ni_unit.py [--write] [--only T,...] [--check]
  `--check` は**見つかったら exit 1**（CIの見張り）。是正の道具であると同時に、
  **同じ型が戻ってこないかを毎回測る検査**でもある。
"""
import json, glob, os, re, sys
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JP = re.compile(r'^\d{4,5}(\s|$|\.)')


def load(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def div1000(x):
    """**ちょうど1000で割る**。浮動小数の粕（8.4/1000=0.008400000000000001）を出さないため
    十進で小数点を移す＝**桁数はそのまま**＝conv=fcf/ni が恒等的に不変になる。"""
    return float(Decimal(str(x)) / Decimal(1000))


def raw_of(ev, kind):
    """evidence の文から実額を拾う。ni は『純利益 N』、fcf は『営業CF A − 設備投資 B』。
    ⚠`evidence.ni` が無いパックがある（実測 LMAT/PKE/WAY）ので、**同じパックの `evidence.eps`**
    （『純利益 N ÷ 株数 M』）を第二の出所にする——別フィールドだが `machine_check.ok` に 'eps' が
    載っている＝**採取器が再現した実額**なので、推測ではない。"""
    if not isinstance(ev, str):
        return None
    if kind == 'ni':
        m = re.search(r'純利益\s*([\d,]{6,})', ev)
        return float(m.group(1).replace(',', '')) if m else None
    m = re.search(r'営業CF\s*([\d,]{6,})\s*−\s*設備投資\s*([\d,]{4,})', ev)
    return float(m.group(1).replace(',', '')) - float(m.group(2).replace(',', '')) if m else None


def scan(only=None):
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, 'out', '*_gate_pack.json'))):
        d = load(p)
        nm = str(d.get('nm', '')).strip()
        t = nm.split()[0] if nm else os.path.basename(p)[:-16]
        if only and t not in only:
            continue
        meta = d.get('_meta') or {}
        if JP.match(nm):
            # 日本株は実額が千円＝下の内部矛盾の検査は当たらない。**自分で『百万円』と申告したパックだけ**を裁く
            u = str(meta.get('unit') or '')
            ni, fcf = d.get('ni'), d.get('fcf')
            if '百万円' in u and '十億円' not in u and isinstance(ni, (int, float)) and ni:
                px, eps = d.get('px'), d.get('eps')
                mag = (px * ni / eps) if all(isinstance(x, (int, float)) for x in (px, eps)) and eps else None
                out.append({'t': t, 'path': p, 'verdict': 'unit_million_jp', 'contra': True,
                            'mag': round(mag, 1) if mag else None, 'ni': ni, 'fcf': fcf,
                            'ni_new': div1000(ni), 'fcf_new': div1000(fcf) if isinstance(fcf, (int, float)) else None,
                            'conv_old': (fcf / ni) if isinstance(fcf, (int, float)) else None, 'unit_old': u})
            continue
        ev = meta.get('evidence') or {}
        ni, fcf = d.get('ni'), d.get('fcf')
        if not isinstance(ni, (int, float)) or not ni:
            continue
        # 証拠(1) 内部矛盾
        r = raw_of(ev.get('ni'), 'ni') or raw_of(ev.get('eps'), 'ni')
        # 判別の本体は**1000倍の隔たり**のほう。/1e6 との一致は桁の確認なので 5% まで許す
        contra = bool(r) and abs(ni - r / 1e6) / abs(ni) < 0.05 and abs(ni - r / 1e9) / abs(ni) > 0.5
        # 証拠(2) 桁の照合
        px, eps, mc = d.get('px'), d.get('eps'), d.get('mcap')
        mag = None
        if all(isinstance(x, (int, float)) for x in (px, eps, mc)) and eps and mc:
            mag = (px * ni / eps) / mc
        magbad = bool(mag) and mag > 100
        # ★どちらか一方でも**演繹的に**確定すれば書く。両方を要求すると、
        #   証拠の**不在**（px/mcap を採っていない社・evidence の無い社）を**反証**として扱うことになる
        #   ＝「測っていない」と「測って問題なし」の取り違え（ルール7の同族）。
        #   (1)内部矛盾は単独で決定的——パックが**自分の evidence と1000倍食い違う**
        #   (2)桁の照合も単独で決定的——株価のドリフトでは1000倍は説明できない
        #   ⚠ただし **(1)が「単位は正しい」と言っているのに(2)が鳴る**なら別の壊れ方＝**書かない**
        if r is not None and not contra and magbad:
            out.append({'t': t, 'path': p, 'verdict': 'conflict',
                        'contra': False, 'mag': round(mag, 1) if mag else None,
                        'ni': ni, 'fcf': fcf})
            continue
        if not (contra or magbad):
            continue
        out.append({'t': t, 'path': p, 'verdict': 'unit_million',
                    'contra': contra, 'mag': (round(mag, 1) if mag else None), 'ni': ni, 'fcf': fcf,
                    'ni_new': div1000(ni), 'fcf_new': div1000(fcf) if isinstance(fcf, (int, float)) else None,
                    'conv_old': (fcf / ni) if isinstance(fcf, (int, float)) else None,
                    'raw_ni': r, 'raw_fcf': raw_of(ev.get('fcf'), 'fcf')})
    return out


def write(rows):
    n = 0
    for r in rows:
        if r['verdict'] == 'unit_million_jp':
            d = load(r['path'])
            d['ni'] = r['ni_new']
            if r['fcf_new'] is not None:
                d['fcf'] = r['fcf_new']
            meta = d.setdefault('_meta', {})
            meta['unit'] = ('JPY（fcf/ni 欄は十億円＝門の ccfMcapUSD の規約。2026-09-23 に百万円から1000で割って揃えた'
                            '——旧札『%s』）' % r['unit_old'])
            k = meta.get('kenshi')
            k = k if isinstance(k, list) else ([] if k in (None, '') else [k])
            k.append('2026-09-23 単位是正: ni %s→%s / fcf %s→%s（百万円→十億円・ちょうど1000で割った）。'
                     'パック自身の unit が『%s』と申告していた＝値ではなく単位の札の誤り。conv=fcf/ni は不変でΩは動かない。'
                     '百万円のままだと `ccfMcapUSD` の px×ni÷eps が %s十億円（1000倍）に化ける'
                     % (r['ni'], r['ni_new'], r['fcf'], r['fcf_new'], r['unit_old'], r['mag']))
            meta['kenshi'] = k
            with open(r['path'], 'w', encoding='utf-8') as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            n += 1
            continue
        if r['verdict'] != 'unit_million':
            continue
        d = load(r['path'])
        d['ni'] = r['ni_new']
        if r['fcf_new'] is not None:
            d['fcf'] = r['fcf_new']
        meta = d.setdefault('_meta', {})
        ev = meta.setdefault('evidence', {})
        tail = ('（★2026-08-20 単位是正: **ちょうど1000で割った**（百万$→十億$）。'
                '値は正しく単位の札だけが違った＝`conv=fcf/ni` は恒等的に不変でΩは動かない。'
                '`ccfMcapUSD` が px×ni÷eps で**絶対値**を使うため、百万のままだと時価総額が1000倍に化ける）')
        for k in ('ni', 'fcf'):
            s = ev.get(k)
            if isinstance(s, str):
                s = s.replace('（門はfcf/niを比でしか使わないため、パック側の単位規約はそのまま。比は一致）', '')
                ev[k] = s + tail
        meta.setdefault('kenshi', []).append(
            '2026-08-20 単位是正: ni %s→%s / fcf %s→%s（百万$→十億$・ちょうど1000で割った）。'
            '**値ではなく単位の札の誤り**——conv=fcf/ni は不変なのでΩは動かない。'
            '発見の経路: `ccfMcapUSD`(v9.9.146) が px×ni÷eps で絶対値を使うようになったため、'
            'px%s×ni%s÷eps%s = %.0f十億$ ＝ mcap欄 %s の約%s倍 に化けていた。'
            '⚠この単位の食い違いは backfill_machine_evidence が「門は比でしか使わない」として'
            '**知ったうえで許していた**もので、絶対値の消費者が増えた時点で前提が崩れていた。'
            % (r['ni'], r['ni_new'], r['fcf'], r['fcf_new'],
               load(r['path']).get('px'), r['ni'], load(r['path']).get('eps'),
               (load(r['path']).get('px') or 0) * r['ni'] / (load(r['path']).get('eps') or 1),
               load(r['path']).get('mcap'), r['mag']))
        with open(r['path'], 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        n += 1
    return n


if __name__ == '__main__':
    only = None
    for i, a in enumerate(sys.argv):
        if a == '--only' and i + 1 < len(sys.argv):
            only = set(sys.argv[i + 1].split(','))
    rows = scan(only)
    hit = [r for r in rows if r['verdict'] in ('unit_million', 'unit_million_jp')]
    one = [r for r in rows if r['verdict'] == 'conflict']
    print('■ ni/fcf の単位是正（百万$ → 十億$ ／ 日本株は unit が『百万円』と申告したパックだけ 百万円 → 十億円）')
    for r in hit:
        print('  %-6s ni %-8s → %-10s / fcf %-8s → %-10s  conv %-6s（不変）  %s'
              % (r['t'], r['ni'], r['ni_new'], r['fcf'], r['fcf_new'],
                 round(r['conv_old'], 3) if r['conv_old'] is not None else '—',
                 ('px×ni÷eps = %s十億円（百万円のまま）' % r['mag']) if r['verdict'] == 'unit_million_jp'
                 else ('桁のずれ %sx' % r['mag'])))
    if one:
        print('  ⚠内部矛盾は「単位は正しい」と言うのに桁が合わない＝**別の壊れ方。書かない**:')
        for r in one:
            print('     %-6s 内部矛盾=%s 桁のずれ=%s' % (r['t'], r['contra'], r['mag']))
    print('  対象 %d社 / 要確認 %d社' % (len(hit), len(one)))
    if '--write' in sys.argv:
        print('  → %d社を書き換えた' % write(rows))
    elif '--check' in sys.argv:
        if hit or one:
            print('  ✗ 単位が十億でないパックが残っている（python3 night/fix_ni_unit.py --write）')
            sys.exit(1)
        print('  ✓ ni/fcf の単位はすべて十億（$ / 円）（対象 %d社を走査）' % len(
            [p for p in glob.glob(os.path.join(ROOT, 'out', '*_gate_pack.json'))]))
    else:
        print('  （--write で反映。先に影の計測でΩが動かないことを確かめること）')
