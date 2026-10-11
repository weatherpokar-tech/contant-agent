"""Content Agent: scrape -> stats -> dashboard (docs/index.html) -> Telegram.
Edit the SETTINGS block to change accounts or limits. Secrets come from env vars only."""
import json, os, sys, statistics as st, datetime as dt, urllib.request, collections

# ---------- SETTINGS (safe to edit) ----------
ME = "anime_space_edit1"
COMPETITORS = ["therankempire", "speeeedy07", "daplug.in"]
LIMIT = 50                      # posts per account (Apify bills per result)
# ----------------------------------------------

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def env(k): return os.environ.get(k, "").strip()

def http(url, body, headers=None, timeout=330):
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, json.dumps(body).encode(), h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def fetch():
    if env("DATA_FILE"):                       # offline test mode
        return json.load(open(env("DATA_FILE")))
    urls = [f"https://www.instagram.com/{u}/" for u in [ME] + COMPETITORS]
    body = {"directUrls": urls, "resultsType": "posts", "resultsLimit": LIMIT}
    return http("https://api.apify.com/v2/acts/apify~instagram-scraper/run-sync-get-dataset-items",
                body, {"Authorization": "Bearer " + env("APIFY_TOKEN")})

def plays(p): return p.get("videoPlayCount") or p.get("videoViewCount") or 0
def likes(p): return max(p.get("likesCount") or 0, 0)
def cap(p, n=90): return (p.get("caption") or "").replace("\n", " ")[:n]

def build(items):
    keep = {ME, *COMPETITORS}
    missing = sorted({i.get("username") for i in items if i.get("error") and i.get("username")})
    posts = [p for p in items if p.get("ownerUsername") in keep]
    acc = {}
    for u in sorted({p["ownerUsername"] for p in posts}):
        v = [plays(p) for p in posts if p["ownerUsername"] == u]
        acc[u] = dict(n=len(v), med=int(st.median(v)), avg=int(sum(v) / len(v)), best=max(v), me=(u == ME))
    comp = [p for p in posts if p["ownerUsername"] != ME]
    top = [dict(u=p["ownerUsername"], c=cap(p), pl=plays(p)) for p in sorted(comp, key=plays, reverse=True)[:6]]
    wd = collections.defaultdict(list)
    for p in comp:
        if p.get("timestamp"):
            t = dt.datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00"))
            wd[t.strftime("%a")].append(plays(p))
    q = sorted(comp, key=plays, reverse=True)[:max(1, len(comp) // 4)]
    mine = sorted([p for p in posts if p["ownerUsername"] == ME and p.get("timestamp")], key=lambda p: p["timestamp"])
    return dict(date=dt.date.today().strftime("%b %d, %Y"), n=len(posts), missing=missing, acc=acc, top=top,
                wd={k: int(st.median(v)) for k, v in wd.items()},
                dur=int(st.median([p.get("videoDuration") or 0 for p in q])) if q else 0,
                my=[dict(d=p["timestamp"][:10], pl=plays(p), lk=likes(p)) for p in mine])

def fmt(n): return f"{n/1e6:.1f}M" if n >= 1e6 else f"{n/1e3:.1f}K" if n >= 1e3 else str(n)

def report(d, link):
    me = d["acc"].get(ME, {})
    comp_med = [a["med"] for u, a in d["acc"].items() if u != ME]
    days = sorted(d["wd"].items(), key=lambda x: -x[1])[:3]
    lines = [f"Content Agent weekly report ({d['date']})",
             f"You (@{ME}): {me.get('n', 0)} Reels, typical {fmt(me.get('med', 0))} plays, best {fmt(me.get('best', 0))}."]
    if comp_med: lines.append(f"Competitors' typical Reel: {fmt(int(st.median(comp_med)))} plays.")
    if d["top"]: lines.append(f"Top Reel: @{d['top'][0]['u']} with {fmt(d['top'][0]['pl'])} plays. {d['top'][0]['c'][:60]}")
    if days: lines.append("Best days to post (UTC): " + ", ".join(f"{k} ({fmt(v)})" for k, v in days))
    if d["missing"]: lines.append("Not found: " + ", ".join(d["missing"]))
    lines.append("Dashboard: " + link)
    return "\n".join(lines)

def telegram(text):
    if env("DRY_RUN"): print(text); return
    http(f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/sendMessage",
         {"chat_id": env("TELEGRAM_CHAT_ID"), "text": text, "disable_web_page_preview": True}, timeout=30)

def main():
    try:
        d = build(fetch())
        if not d["n"]: raise RuntimeError("No posts returned")
        os.makedirs(f"{ROOT}/docs", exist_ok=True)
        json.dump(d, open(f"{ROOT}/dashboard/data.json", "w"), separators=(",", ":"))
        tpl = open(f"{ROOT}/dashboard/template.html").read()
        open(f"{ROOT}/docs/index.html", "w").write(tpl.replace("__DATA__", json.dumps(d, separators=(",", ":"))))
        repo = env("GITHUB_REPOSITORY") or "owner/repo"
        o, r = repo.split("/")
        telegram(report(d, f"https://{o}.github.io/{r}/"))
        print("OK", d["n"], "posts")
    except Exception as e:                      # tell the owner instead of failing silently
        msg = f"Content Agent run failed: {type(e).__name__}: {str(e)[:150]}"
        try: telegram(msg)
        except Exception: pass
        print(msg); sys.exit(1)

if __name__ == "__main__": main()
