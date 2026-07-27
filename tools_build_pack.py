# -*- coding: utf-8 -*-
"""門パックの決定論的生成器。
   moat_evidence.json(堀の証拠台帳) + 機械値 → 門に取り込むパックJSON
   **同じ台帳からは必ず同じパック=同じスコアが出る**。スコアが動いたら、必ず台帳の差分が
   gitに残っている。審査者(私)の記憶や気分でスコアが動くことを構造的に禁止する。
   使い方: python tools_build_pack.py            … 台帳から out/v5/v5_all_pack.json を再生成
           python tools_build_pack.py --check    … 再生成しても既存と一致するか検査(CI用)
"""
import json,sys,os,hashlib

LEDGER="moat_evidence.json"
MACHINE="out/v5/_machine.json"   # 機械値(SEC/EDINET由来)。堀以外の全項目
OUT="out/v5/v5_all_pack.json"

def build():
    ev=json.load(open(LEDGER,encoding="utf-8"))
    mach=json.load(open(MACHINE,encoding="utf-8"))
    out=[]
    for nm in sorted(mach.keys()):                       # 名前順=生成順が決定論的
        o=dict(mach[nm])
        e=ev["companies"].get(nm)
        if e is None:
            raise SystemExit(f"台帳に堀の証拠がない: {nm}")
        ms=e.get("moats") or []
        if len(ms)>=2:
            o["moats"]=[{k:m[k] for k in ("seg","rev","dom","irr","rep","dur","indep","indep_reason")
                         if k in m} for m in ms]
            best=max(ms,key=lambda m: moat_one(m))
            for k in ("dom","irr","rep","dur"): o[k]=best[k]
        else:
            m=ms[0] if ms else e
            for k in ("dom","irr","rep","dur"): o[k]=m.get(k)
        a=o.setdefault("_meta",{}).setdefault("audit",{})
        a["protocol"]="門2審査プロトコル v5(証拠規則)＋v9.10 複数の堀"
        a["auditDate"]=ev["asof"]; a["model"]="claude-opus-5"
        a["moat_evidence"]=e.get("evidence")
        a["source_ledger"]=f"{LEDGER}@{sha()[:12]}"
        out.append(o)
    return out

def moat_one(m):
    import math
    c=lambda v: min(96,max(1,float(v or 1)))
    w=[.30,.30,.25,.15]; v=[c(m.get("dom")),c(m.get("irr")),c(m.get("rep")),c(m.get("dur"))]
    return math.exp(sum(wi*math.log(vi) for vi,wi in zip(v,w)))

def sha():
    return hashlib.sha256(open(LEDGER,"rb").read()).hexdigest()

if __name__=="__main__":
    got=build()
    txt=json.dumps(got,ensure_ascii=False,indent=1)
    if "--check" in sys.argv:
        cur=open(OUT,encoding="utf-8").read()
        if cur.strip()!=txt.strip():
            print("✗ 再現しない: 台帳から生成した内容が既存パックと一致しない"); sys.exit(1)
        print(f"✓ 再現した: {len(got)}社 / 台帳 sha256={sha()[:12]}"); sys.exit(0)
    open(OUT,"w",encoding="utf-8").write(txt)
    print(f"生成: {OUT}  {len(got)}社  台帳 sha256={sha()[:12]}")
