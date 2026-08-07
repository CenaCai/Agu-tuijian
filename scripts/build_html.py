#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成单文件 HTML 市场情绪日报（暗色、内联 SVG、可离线）。
读取 data/report_data.json → 写出 report.html。可重复运行。"""
import json, html, os

D = "data"
OUT = "report.html"
R = json.load(open(f"{D}/report_data.json", encoding="utf-8"))

# ───────────── 格式化 ─────────────
def pct(v):
    if v is None: return "—"
    return f"{v:+.2f}%"

def amt(v):
    """金额 → 亿/万 + 符号"""
    if v is None: return "—"
    s = "+" if v >= 0 else "-"
    a = abs(v)
    if a >= 1e8:
        return f"{s}{a/1e8:.2f}亿"
    if a >= 1e4:
        return f"{s}{a/1e4:.1f}万"
    return f"{s}{a:.0f}"

def amt_yi(v):
    if v is None: return "—"
    return f"{v/1e8:+.2f}亿"

def color_pct(v):
    """涨红跌绿"""
    if v is None: return "#8b949e"
    return "#f85149" if v > 0 else ("#3fb950" if v < 0 else "#8b949e")

def color_amt(v):
    if v is None: return "#8b949e"
    return "#f85149" if v > 0 else ("#3fb950" if v < 0 else "#8b949e")

RATE_COLOR = {"s-a": "#3fb950", "s-b": "#7ee787", "s-c": "#d29922",
              "s-d": "#f0883e", "s-e": "#f85149"}
RATE_BG = {"s-a": "rgba(63,185,80,.18)", "s-b": "rgba(126,231,135,.16)",
           "s-c": "rgba(210,153,34,.18)", "s-d": "rgba(240,136,62,.16)",
           "s-e": "rgba(248,81,73,.18)"}

def esc(s):
    return html.escape(str(s)) if s is not None else "—"

# ───────────── SVG 横向条形图 ─────────────
def hbars(rows, w=640, rowh=22, pad=4, maxv=None, color_fn=None,
          val_fmt=None, title=None):
    """rows: [(label, value, sub)]  value 决定长度"""
    if not rows:
        return ""
    maxv = maxv or max((abs(r[1]) for r in rows), default=1) or 1
    n = len(rows)
    top = 26 if title else 4
    h = top + n * (rowh + pad) + 6
    parts = [f'<svg viewBox="0 0 {w+150} {h}" width="100%" preserveAspectRatio="xMinYMin meet" '
             f'style="font-family:inherit">']
    if title:
        parts.append(f'<text x="0" y="16" fill="#c9d1d9" font-size="13" font-weight="600">{esc(title)}</text>')
    for i, (label, value, sub) in enumerate(rows):
        y = top + i * (rowh + pad)
        bw = max(2, int(abs(value) / maxv * w)) if maxv else 2
        col = color_fn(value) if color_fn else "#58a6ff"
        neg = value < 0
        x0 = w if neg else (w - bw)
        parts.append(f'<text x="0" y="{y+rowh-7}" fill="#8b949e" font-size="11.5">{esc(label)}</text>')
        parts.append(f'<rect x="{x0}" y="{y}" width="{bw}" height="{rowh-6}" rx="2" fill="{col}" opacity="0.9"/>')
        vt = val_fmt(value) if val_fmt else f"{value:.2f}"
        tx = (x0 - 6) if neg else (x0 + bw + 6)
        anc = "end" if neg else "start"
        parts.append(f'<text x="{tx}" y="{y+rowh-7}" fill="{col}" font-size="11" text-anchor="{anc}" font-weight="600">{esc(vt)}</text>')
    parts.append("</svg>")
    return "".join(parts)

def line_chart(points, w=640, h=160, color="#58a6ff", title=None):
    """points: [(label, value)] 折线/面积"""
    if not points:
        return ""
    vals = [p[1] for p in points if p[1] is not None]
    if not vals:
        return '<div class="muted">数据暂缺</div>'
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    n = len(points)
    pad_l, pad_b, pad_t = 36, 22, 8
    plotw, ploth = w - pad_l - 8, h - pad_b - pad_t
    def px(i, v):
        x = pad_l + (i / max(1, n - 1)) * plotw
        y = pad_t + (1 - (v - lo) / span) * ploth
        return x, y
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="font-family:inherit">']
    if title:
        parts.append(f'<text x="0" y="12" fill="#c9d1d9" font-size="12" font-weight="600">{esc(title)}</text>')
    # y 轴
    for g in (0, 0.5, 1):
        yy = pad_t + g * ploth
        vv = lo + (1 - g) * span
        parts.append(f'<line x1="{pad_l}" y1="{yy}" x2="{w-8}" y2="{yy}" stroke="#21262d" stroke-width="1"/>')
        parts.append(f'<text x="2" y="{yy+3}" fill="#6e7681" font-size="9">{vv:.0f}</text>')
    pts = [px(i, p[1]) for i, p in enumerate(points) if p[1] is not None]
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = d + f" L{pts[-1][0]:.1f},{pad_t+ploth} L{pts[0][0]:.1f},{pad_t+ploth} Z"
    parts.append(f'<path d="{area}" fill="{color}" opacity="0.12"/>')
    parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"/>')
    for (i, p), (x, y) in zip([(i, p) for i, p in enumerate(points) if p[1] is not None], pts):
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{color}"/>')
        if i % 2 == 0 or i == n - 1:
            parts.append(f'<text x="{x:.1f}" y="{h-6}" fill="#6e7681" font-size="9" text-anchor="middle">{esc(p[0][5:])}</text>')
    parts.append("</svg>")
    return "".join(parts)

# ───────────── 数据切片 ─────────────
lhb = R["lhb_records"]
lhb_stocks = R["lhb_stocks"]
themes = R["themes"]
ths = R["ths_hot"]
inds = R["industries"]
cands = R["candidates"]
shortlist = R["shortlist"]
trend = R["trend"]
sm = R["lhb_summary"]
ims = R["ind_summary"]

# 龙虎榜按净买入降序（记录级全量）
lhb_sorted = sorted(lhb, key=lambda x: -(x.get("net_buy") or 0))
# 行业排序（涨跌幅）
inds_by_chg = sorted(inds, key=lambda x: -x["change_pct"])
top_ind = inds_by_chg[:12]
bot_ind = inds_by_chg[-12:][::-1]
# 候选评分降序（用于条形）
score_rows = [(c["name"], c["score"], "") for c in shortlist]

# ───────────── HTML 片段 ─────────────
def overview_card(label, value, sub, color):
    return f'''<div class="card">
      <div class="card-label">{esc(label)}</div>
      <div class="card-value" style="color:{color}">{esc(value)}</div>
      <div class="card-sub">{esc(sub)}</div>
    </div>'''

top_theme = themes[0] if themes else None
lead_ind = inds_by_chg[0] if inds_by_chg else None
bw = R.get("breadth") or {}
breadth_sub = (f"{bw.get('up',0)}涨 / {bw.get('down',0)}跌 / {bw.get('flat',0)}平 · "
               f"涨停{bw.get('limit_up',0)} 跌停{bw.get('limit_down',0)} · 样本{bw.get('sample',0)}")
# 全市场涨跌方向（用于领涨行业副标题）
if bw and bw.get('sample'):
    mp_up = bw['up'] > bw['down']
    breadth_dir = f"全市场{'普涨' if mp_up else '普跌'}"
else:
    breadth_dir = ""
cards = "".join([
    overview_card("龙虎榜上榜", f"{sm['n_stocks']} 只", f"{sm['n_records']} 条记录 · 净买正 {sm['n_net_pos']} / 负 {sm['n_net_neg']}", "#e6edf3"),
    overview_card("龙虎榜净买入合计", amt_yi(sm['total_net']), f"买入 {sm['total_buy']/1e8:.1f}亿 / 卖出 {sm['total_sell']/1e8:.1f}亿", color_amt(sm['total_net'])),
    overview_card("最热题材", esc(top_theme['tag'] if top_theme else "—"), f"出现 {top_theme['count'] if top_theme else 0} 只 · 强势股共 {R['n_ths']} 只", "#58a6ff"),
    overview_card("市场宽度", f"{bw.get('up',0)} / {bw.get('down',0)}", breadth_sub, color_pct(bw.get('up',0)-bw.get('down',0))),
    overview_card("领涨行业", esc(lead_ind['name'] if lead_ind else "—"), f"涨跌幅 {pct(lead_ind['change_pct'] if lead_ind else None)} · {breadth_dir}", color_pct(lead_ind['change_pct'] if lead_ind else None)),
])

# 龙虎榜净买入 TOP15 条形
lhb_bars = hbars(
    [(f"{r['name']}({r['code']})", r["net_buy"]/1e8, "") for r in lhb_sorted[:15]],
    color_fn=lambda v: "#f85149" if v >= 0 else "#3fb950",
    val_fmt=lambda v: f"{v:+.2f}亿")

# 题材 TOP20 条形
theme_bars = hbars(
    [(t["tag"], t["count"], "") for t in themes[:20]],
    color_fn=lambda v: "#58a6ff", val_fmt=lambda v: f"{v:.0f}只")

# 行业领涨/领跌
ind_up_bars = hbars(
    [(i["name"], i["change_pct"], "") for i in top_ind],
    color_fn=color_pct, val_fmt=pct)
ind_dn_bars = hbars(
    [(i["name"], i["change_pct"], "") for i in bot_ind],
    color_fn=color_pct, val_fmt=pct)

# 候选评分条形
score_bars = hbars(
    [(c["name"], c["score"], "") for c in shortlist],
    maxv=100, color_fn=lambda v: ("#3fb950" if v >= 64 else ("#d29922" if v >= 50 else "#f0883e")),
    val_fmt=lambda v: f"{v:.0f}")

# 强势股趋势
trend_chart = line_chart([(d["date"], d["n"]) for d in trend], color="#a371f7",
                         title=f"同花顺强势股数量（情绪温度，{trend[0]['date'] if trend else ''}~{trend[-1]['date'] if trend else ''}）")

# ───────────── 龙虎榜表格 ─────────────
def lhb_row(r):
    chg = r.get("change_pct")
    nb = r.get("net_buy")
    return f'''<tr>
      <td class="mono">{esc(r.get('code'))}</td>
      <td>{esc(r.get('name'))}</td>
      <td class="mono" style="color:{color_pct(chg)}">{pct(chg)}</td>
      <td class="mono" style="color:{color_amt(nb)}">{amt(nb)}</td>
      <td class="reason">{esc(r.get('reason'))}</td>
      <td class="mono">{('%.2f%%' % r['turnover_pct']) if r.get('turnover_pct') is not None else '—'}</td>
    </tr>'''
lhb_table = "".join(lhb_row(r) for r in lhb_sorted)

# ───────────── 行业表格 ─────────────
def ind_row(i):
    chg = i.get("change_pct")
    up, dn, tot, leader = i.get("up"), i.get("down"), i.get("total"), i.get("leader")
    leader_txt = ("—" if not leader else f"{leader.get('name','—')} {pct(leader.get('chg'))}")
    return f'''<tr>
      <td class="mono">{esc(i.get('code'))}</td>
      <td>{esc(i.get('name'))}</td>
      <td class="mono" style="color:{color_pct(chg)}">{pct(chg)}</td>
      <td class="mono">{'%s / %s / %s' % (up if up is not None else '—', dn if dn is not None else '—', tot if tot is not None else '—') if (up is not None or dn is not None or tot is not None) else '采集中'}</td>
      <td>{esc(leader_txt)}</td>
      <td class="mono">{amt(i.get('main_net')) if i.get('main_net') is not None else '—'}</td>
    </tr>'''
ind_table = "".join(ind_row(i) for i in inds_by_chg)

# ───────────── 推荐表格 ─────────────
def rate_badge(g):
    txt, cls = g
    return f'<span class="badge" style="color:{RATE_COLOR[cls]};background:{RATE_BG[cls]}">{esc(txt)}</span>'

def cand_row(c):
    chg = c.get("change_pct")
    return f'''<tr>
      <td class="mono">{esc(c['code'])}</td>
      <td><b>{esc(c['name'])}</b></td>
      <td class="mono" style="color:{color_pct(chg)}">{pct(chg)}</td>
      <td class="mono">{('%.2f' % c['turnover_pct']) if c.get('turnover_pct') else '—'}</td>
      <td class="mono" style="color:{color_amt(c['net_buy'])}">{amt(c['net_buy'])}</td>
      <td class="mono" style="color:{color_pct(chg)}">{esc('、'.join(c.get('tags',[])[:3]))}</td>
      <td class="mono" style="color:#3fb950">{'%.2f' % c['buy']}</td>
      <td class="mono" style="color:#f0883e">{'%.2f' % c['sell']}</td>
      <td class="mono">{'%.2f' % c['stop']}</td>
      <td class="mono" style="font-weight:700;color:#e6edf3">{c['score']:.0f}</td>
      <td>{rate_badge(c['r_ultra'])}</td>
      <td>{rate_badge(c['r_short'])}</td>
      <td>{rate_badge(c['r_mid'])}</td>
      <td>{rate_badge(c['r_long'])}</td>
    </tr>'''
cand_table = "".join(cand_row(c) for c in shortlist)

# 统一持仓说明：名单主周期一致时提炼为单句，避免逐行重复冗余数字
_cycles = {}
for _c in shortlist:
    _cycles.setdefault(_c["primary_period"], []).append(_c)
if len(_cycles) == 1:
    _cyc = next(iter(_cycles))
    _rep = shortlist[0]
    hold_note = (f"本批 {len(shortlist)} 只主周期均为「<b>{_cyc}</b>」："
                 f"建议买入日 <b>{_rep['buy_date']}</b> → 建议卖出日 <b>{_rep['sell_date']}</b>，"
                 f"持仓约 <b>{_rep['hold_cal']} 天</b>（{_rep['hold_td']} 个交易日）。"
                 f"名单由龙虎榜 + 题材情绪筛选，天然偏短线动量，不建议长期持有。")
else:
    hold_note = ("名单含多周期标的，各股建议持仓窗口以其四周期评级中分数最高的周期为准"
                 "（超短期 3 / 短期 10 / 中期 40 / 长期 120 个交易日）。")

# 推荐股明细卡片（买卖价 + 四周期）
def cand_card(c):
    return f'''<div class="pick">
      <div class="pick-h">
        <span class="pick-name">{esc(c['name'])}</span>
        <span class="mono pick-code">{esc(c['code'])}</span>
        <span class="mono pick-score" style="color:#e6edf3">综合 {c['score']:.0f}</span>
      </div>
      <div class="pick-tags">{' · '.join(esc(t) for t in c.get('tags',[])[:4]) or '—'}</div>
      <div class="pick-grid">
        <div><span class="pk">建议买入</span><b style="color:#3fb950">{'%.2f' % c['buy']}</b></div>
        <div><span class="pk">建议卖出</span><b style="color:#f0883e">{'%.2f' % c['sell']}</b></div>
        <div><span class="pk">止损价</span><b style="color:#f85149">{'%.2f' % c['stop']}</b></div>
        <div><span class="pk">风险回报</span><b>{('%.2f' % c['rr']) if c.get('rr') else '—'}</b></div>
      </div>
      <div class="pick-rate">
        <span class="rlg"><span class="rl">超短期</span>{rate_badge(c['r_ultra'])}</span>
        <span class="rlg"><span class="rl">短期</span>{rate_badge(c['r_short'])}</span>
        <span class="rlg"><span class="rl">中期</span>{rate_badge(c['r_mid'])}</span>
        <span class="rlg"><span class="rl">长期</span>{rate_badge(c['r_long'])}</span>
      </div>
    </div>'''
pick_cards = "".join(cand_card(c) for c in shortlist)

# 题材明细（TOP 10）
theme_detail = ""
for t in themes[:10]:
    stocks = "、".join(f"{s['name']}({pct(s['zhangfu'])})" for s in t["stocks"][:6])
    theme_detail += f'''<div class="theme-item">
      <div class="theme-tag">{esc(t['tag'])} <span class="theme-cnt">{t['count']}只</span></div>
      <div class="theme-stocks">{esc(stocks)}</div>
    </div>'''

cov = ims.get("coverage", "—")
board_pending = ""

HTML = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>A股市场情绪日报 · {R['trade_date']}</title>
<style>
  :root {{
    --bg:#0d1117; --panel:#161b22; --panel2:#1c2230; --border:#30363d;
    --text:#e6edf3; --muted:#8b949e; --blue:#58a6ff; --red:#f85149; --green:#3fb950;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,"PingFang SC","Microsoft YaHei",Segoe UI,Roboto,sans-serif;
    font-size:13px; line-height:1.5; }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:22px 22px 60px; }}
  .mono {{ font-family:"SF Mono",ui-monospace,Menlo,Consolas,monospace; }}
  header {{ border-bottom:1px solid var(--border); padding-bottom:14px; margin-bottom:18px; }}
  h1 {{ font-size:22px; margin:0 0 4px; letter-spacing:.5px; }}
  .sub {{ color:var(--muted); font-size:12.5px; }}
  .sub b {{ color:var(--text); }}
  h2 {{ font-size:16px; margin:30px 0 12px; padding-left:9px; border-left:3px solid var(--blue); }}
  .cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }}
  .card {{ background:var(--panel); border:1px solid var(--border); border-radius:9px; padding:13px 14px; }}
  .card-label {{ color:var(--muted); font-size:12px; }}
  .card-value {{ font-size:21px; font-weight:700; margin:5px 0 3px; font-family:"SF Mono",ui-monospace,monospace; }}
  .card-sub {{ color:var(--muted); font-size:11.5px; }}
  .panel {{ background:var(--panel); border:1px solid var(--border); border-radius:9px; padding:14px 16px; }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
  table {{ width:100%; border-collapse:collapse; font-size:12px; }}
  th,td {{ padding:6px 8px; text-align:left; border-bottom:1px solid var(--border); }}
  th {{ color:var(--muted); font-weight:600; position:sticky; top:0; background:var(--panel); }}
  td.reason {{ color:#c9d1d9; max-width:280px; }}
  tbody tr:hover {{ background:var(--panel2); }}
  .table-scroll {{ max-height:430px; overflow:auto; border:1px solid var(--border); border-radius:8px; }}
  .badge {{ padding:1px 7px; border-radius:10px; font-size:11px; font-weight:600; }}
  .note {{ background:rgba(210,153,34,.12); border:1px solid rgba(210,153,34,.4); color:#d29922;
    border-radius:7px; padding:9px 12px; font-size:12px; margin:10px 0; }}
  .picks {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }}
  .pick {{ background:var(--panel); border:1px solid var(--border); border-radius:9px; padding:12px 13px; }}
  .pick-h {{ display:flex; align-items:baseline; gap:8px; }}
  .pick-name {{ font-size:15px; font-weight:700; }}
  .pick-code {{ color:var(--muted); font-size:11px; }}
  .pick-score {{ margin-left:auto; font-size:13px; }}
  .pick-tags {{ color:var(--blue); font-size:11.5px; margin:3px 0 9px; }}
  .pick-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:7px 12px; margin-bottom:9px; }}
  .pick-grid .pk {{ display:block; color:var(--muted); font-size:10.5px; }}
  .pick-grid b {{ font-size:14px; font-family:"SF Mono",ui-monospace,monospace; }}
  .pick-rate {{ display:flex; flex-wrap:wrap; gap:6px 12px; align-items:center;
    border-top:1px dashed var(--border); padding-top:9px; }}
  .pick-rate .rlg {{ display:inline-flex; align-items:center; gap:4px; }}
  .pick-rate .rl {{ color:var(--muted); font-size:10.5px; }}
  .theme-item {{ padding:8px 0; border-bottom:1px solid var(--border); }}
  .theme-tag {{ font-weight:600; font-size:13px; }}
  .theme-cnt {{ color:var(--blue); font-size:11px; font-weight:400; margin-left:4px; }}
  .theme-stocks {{ color:var(--muted); font-size:11.5px; margin-top:2px; }}
  .muted {{ color:var(--muted); }}
  footer {{ margin-top:34px; border-top:1px solid var(--border); padding-top:14px;
    color:var(--muted); font-size:11.5px; }}
  footer b {{ color:var(--text); }}
  .legend {{ display:flex; gap:16px; font-size:11.5px; color:var(--muted); margin:4px 0 10px; }}
  .legend i {{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; vertical-align:middle; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>A股市场情绪日报</h1>
    <div class="sub">交易日 <b>{R['trade_date']}</b> · 数据抓取于 {esc(R.get('fetched_at',''))[:10]} · 生成于 {esc(R.get('built_at',''))}</div>
    <div class="legend" style="margin-top:10px;">
      <span><i style="background:#f85149"></i>上涨 / 净买入为正</span>
      <span><i style="background:#3fb950"></i>下跌 / 净买入为负</span>
      <span><i style="background:#58a6ff"></i>题材热度</span>
      <span><i style="background:#a371f7"></i>情绪温度(强势股数)</span>
    </div>
  </header>

  <div class="cards">{cards}</div>

  {board_pending}

  <h2>一、建议关注名单（候选 {len(cands)} 只 → 精选 {len(shortlist)} 只）</h2>
  <div class="note" style="margin-bottom:12px;background:rgba(88,166,255,.10);border-color:rgba(88,166,255,.4);color:#79c0ff;">
    评级分五档：<b style="color:#3fb950">强</b>(≥78) / <b style="color:#7ee787">较强</b>(64-77) / <b style="color:#d29922">中性</b>(50-63) / <b style="color:#f0883e">偏弱</b>(36-49) / <b style="color:#f85149">回避</b>(&lt;36)，分别对应右侧<b>超短期 / 短期 / 中期 / 长期</b>四列；综合评分=资金+题材+技术+换手+行业(0-100)。
  </div>
  <div class="note" style="margin-bottom:12px;background:rgba(121,192,255,.08);border-color:rgba(121,192,255,.35);color:#9ecbff;">
    {hold_note}
  </div>
  <div class="panel" style="margin-bottom:14px;">
    <div class="card-sub" style="margin-bottom:8px;">综合评分 TOP（0-100，资金+题材+技术+换手+行业）</div>
    {score_bars}
  </div>
  <div class="picks">{pick_cards}</div>
  <div class="table-scroll" style="margin-top:14px;">
    <table>
      <thead><tr><th>代码</th><th>名称</th><th>涨跌幅</th><th>换手</th><th>龙虎净买</th><th>题材</th>
        <th>买价</th><th>卖价</th><th>止损</th><th>评分</th><th>超短期</th><th>短期</th><th>中期</th><th>长期</th></tr></thead>
      <tbody>{cand_table}</tbody>
    </table>
  </div>

  <h2>二、龙虎榜全景（按净买入降序）</h2>
  <div class="panel">
    <div class="table-scroll">
      <table>
        <thead><tr><th>代码</th><th>名称</th><th>涨跌幅</th><th>净买入</th><th>上榜原因</th><th>换手率</th></tr></thead>
        <tbody>{lhb_table}</tbody>
      </table>
    </div>
  </div>

  <h2>三、题材个股推荐（同花顺强势股归因 · TOP 10）</h2>
  <div class="panel">
    {theme_detail}
  </div>

  <h2>四、行业轮动（东财全市场行业板块 · 覆盖 {esc(cov)}）</h2>
  <div class="grid2">
    <div class="panel">
      <div class="card-sub" style="margin-bottom:8px;">相对领涨行业 TOP12</div>
      {ind_up_bars}
    </div>
    <div class="panel">
      <div class="card-sub" style="margin-bottom:8px;">领跌行业 TOP12</div>
      {ind_dn_bars}
    </div>
  </div>
  <div class="table-scroll" style="margin-top:14px;">
    <table>
      <thead><tr><th>板块代码</th><th>板块名称</th><th>涨跌幅</th><th>上涨/下跌/总数</th><th>领涨股</th><th>主力净流(亿)</th></tr></thead>
      <tbody>{ind_table}</tbody>
    </table>
  </div>

  <footer>
    <div><b>交易日期：</b>{R['trade_date']}（数据已校验为真实交易日）</div>
    <div style="margin-top:6px;"><b>数据来源：</b>
      龙虎榜 — 东方财富数据中心（datacenter-web.eastmoney.com, RPT_DAILYBILLBOARD_DETAILSNEW）；
      题材热点 — 同花顺涨停板复盘（zx.10jqka.com.cn/event/api/getharden）；
      行业分类 / 成分股 / 全市场涨跌家数 — 新浪财经（vip.stock.finance.sina.com.cn）；
      行业涨跌幅 / 技术面 — 腾讯财经历史K线（web.ifzq.gtimg.cn，不封IP并发）；
      基本面 — 新浪财经财报接口。
      <span style="color:#8b949e;">注：因东方财富 push2/push2his 接口当日处于限流状态，行业数据改用新浪分类+腾讯行情聚合替代，行业覆盖 {ims.get('coverage','')}，全市场涨跌家数基于 {bw.get('sample',0)} 只样本统计。</span>
    </div>
    <div style="margin-top:6px;"><b>免责声明：</b>本报告由数据脚本自动生成，仅作市场情绪复盘与量化筛选参考，不构成任何投资建议。买卖决策与风险自担。</div>
  </footer>
</div>
</body>
</html>'''

open(OUT, "w", encoding="utf-8").write(HTML)
print(f"OK → {OUT}  ({len(HTML)} bytes)  |  龙虎榜{lhb_sorted.__len__()} 题材{len(themes)} 行业{len(inds)} 推荐{len(shortlist)}")
