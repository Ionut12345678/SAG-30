"""Time-split, no-lookahead directional forecast evaluation, research only."""
import argparse, json, math
from pathlib import Path
from statistics import mean
from backtest import load

HORIZONS=(5,10,20)
FEATURES=(5,20,60)
SPLITS=(("train","2021-01-01","2023-12-31"),("validation","2024-01-01","2024-12-31"),("test","2025-01-01","2026-12-31"))

def features(bars,i):
    if i<60:return None
    close=bars[i]["close"]
    return [close/bars[i-n]["close"]-1 for n in FEATURES]

def sample(groups,horizon,start,end):
    rows=[]
    for symbol,bars in groups.items():
        for i in range(60,len(bars)-horizon):
            day=str(bars[i]["date"])
            # Ensure both the prediction and realized label remain in the same split;
            # no training label from validation/test dates.
            target_day=str(bars[i+horizon]["date"])
            if start<=day<=end and target_day<=end:
                x=features(bars,i)
                if x is None:continue
                y=bars[i+horizon]["close"]/bars[i]["close"]-1
                rows.append((symbol,day,x,y))
    return rows

def fit(rows,alpha=1e-6):
    # Three-feature linear model, standardized by training-only moments.
    xs=[r[2] for r in rows];ys=[r[3] for r in rows]
    if len(rows)<100:raise ValueError("Insufficient training samples")
    center=[mean(x[j] for x in xs) for j in range(3)]
    scale=[max(1e-8,math.sqrt(mean((x[j]-center[j])**2 for x in xs))) for j in range(3)]
    mat=[[0.]*4 for _ in range(4)];rhs=[0.]*4
    for x,y in zip(xs,ys):
        z=[1.]+[(x[j]-center[j])/scale[j] for j in range(3)]
        for a in range(4):
            rhs[a]+=z[a]*y
            for b in range(4):mat[a][b]+=z[a]*z[b]
    for j in range(1,4):mat[j][j]+=alpha*len(rows)
    for k in range(4):
        pivot=max(range(k,4),key=lambda a:abs(mat[a][k]))
        mat[k],mat[pivot]=mat[pivot],mat[k];rhs[k],rhs[pivot]=rhs[pivot],rhs[k]
        if abs(mat[k][k])<1e-12:raise ValueError("Singular training design")
        div=mat[k][k]
        mat[k]=[z/div for z in mat[k]];rhs[k]/=div
        for i in range(4):
            if i==k:continue
            mult=mat[i][k]
            mat[i]=[mat[i][j]-mult*mat[k][j] for j in range(4)]
            rhs[i]-=mult*rhs[k]
    return center,scale,rhs

def predict(model,x):
    center,scale,beta=model
    return beta[0]+sum(beta[j+1]*(x[j]-center[j])/scale[j] for j in range(3))

def metrics(rows,model):
    if not rows:return {"count":0}
    forecast=[predict(model,r[2]) for r in rows]
    true=[r[3] for r in rows]
    return {"count":len(rows),"directional_accuracy_pct":round(100*sum((a>0)==(b>0) for a,b in zip(forecast,true))/len(rows),3),
            "baseline_up_accuracy_pct":round(100*sum(y>0 for y in true)/len(true),3),
            "mean_absolute_error_pct":round(100*mean(abs(a-b) for a,b in zip(forecast,true)),3),
            "mean_true_return_pct":round(100*mean(true),3),
            "mean_predicted_return_pct":round(100*mean(forecast),3)}

def evaluate(groups):
    out={}
    for horizon in HORIZONS:
        subsets={label:sample(groups,horizon,start,end) for label,start,end in SPLITS}
        model=fit(subsets["train"])
        out[str(horizon)]={name:metrics(rows,model) for name,rows in subsets.items()}
    return {"method":"Train-only standardized ridge linear baseline; fixed parameters; prediction at close of t with label at t+h.",
            "caveats":"Overlapping forecast horizons; five currently surviving symbols; adjusted OHLC; no transaction simulation or execution. Not a calibrated probability or live price target.",
            "horizons":out}

def main():
    p=argparse.ArgumentParser();p.add_argument("csv");p.add_argument("--out",required=True);a=p.parse_args()
    result=evaluate(load(a.csv))
    Path(a.out).write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))
if __name__=="__main__":main()
