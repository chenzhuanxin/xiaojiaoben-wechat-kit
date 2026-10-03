#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信加人节奏管理器 —— 只做「提醒 + 台账」，不碰微信。

硬边界（本脚本刻意不实现，也请不要自行加）：
  * 不模拟按键、不发送窗口消息、不注入微信进程
  * 不读写微信内存、不 hook、不抓包、不读剪贴板
  * 不自动发送验证语、不自动回复

所有「加好友 / 通过 / 聊天」都由你本人手动点。脚本只负责：
把一天要加的人按「分时段 + 不等间距 + 随机抖动」排成时刻表，
到点弹窗提醒你，并帮你把「真人来源验证语」和「加完当天要不要聊天」记下来。
"""

import argparse
import csv
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE, "planner_config.json")
SCHED_PATH = os.path.join(BASE, "schedule.json")
FIRED_PATH = os.path.join(BASE, "fired.json")
BOOK_PATH = os.path.join(BASE, "加人台账.csv")

COLS = ["日期", "时段", "序号", "渠道", "目标", "微信号", "联系电话",
        "对方昵称备注", "验证语",
        "发出时间", "通过时间", "状态", "跟进备注"]


def load_cfg():
    with open(CFG_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- 时刻表生成

def _hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def gen_plan(cfg, day=None):
    """在一个窗口内随机撒点，再全局强制最小间隔，得到一条不等间距的时刻表。"""
    if day is None:
        day = datetime.now()
    day = day.replace(hour=0, minute=0, second=0, microsecond=0)  # 必须归零到当天零点
    min_gap = cfg.get("最小间隔秒", 150)
    jitter = cfg.get("间隔抖动秒", 60)
    picks = []

    for w in cfg["窗口"]:
        start, end = _hm(w["起"]), _hm(w["止"])
        n = int(w["数量"])
        span = max(1, end - start)
        step = span / (n + 1)                  # 窗口内等分步长
        for i in range(n):
            # 在等分点上下各抖半个步长，落在窗口内但间距不等
            off = random.uniform(-step * 0.5, step * 0.5)
            t = int(start + step * (i + 1) + off)
            t = max(start, min(end, t))
            picks.append({
                "分钟": t,
                "渠道": w["渠道"],
                "窗口": "%s-%s" % (w["起"], w["止"]),
            })

    picks.sort(key=lambda x: x["分钟"])
    for i, p in enumerate(picks, 1):
        p["序号"] = i

    # 全局消解：强制任意两次提醒之间不少于「最小间隔 + 随机抖动」
    for i in range(1, len(picks)):
        floor = picks[i - 1]["分钟"] + min_gap / 60 + random.uniform(0, jitter) / 60
        if picks[i]["分钟"] < floor:
            picks[i]["分钟"] = int(floor)

    out = []
    for p in picks:
        d = day + timedelta(minutes=p["分钟"])
        pool = [t for t in cfg["文案库"] if t["渠道"] == p["渠道"]] or cfg["文案库"]
        tpl = random.choice(pool)["模板"]
        out.append({
            "分钟": p["分钟"],
            "时间": d.strftime("%H:%M"),
            "序号": p["序号"],
            "渠道": p["渠道"],
            "文案": tpl,
        })
    return out


def cmd_plan(a):
    cfg = load_cfg()
    day = datetime.strptime(a.date, "%Y-%m-%d") if a.date else datetime.now().replace(second=0, microsecond=0)
    plan = gen_plan(cfg, day)
    with open(SCHED_PATH, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    print("已生成 %s 的提醒时刻表（%d 条，最小间隔 %d 秒）\n" % (day.strftime("%Y-%m-%d"), len(plan), cfg["最小间隔秒"]))
    for p in plan:
        print("  %s  第%2d条  %-8s  %s" % (p["时间"], p["序号"], p["渠道"], p["文案"]))
    print("\n提示：verify 语里的 {xxx} 请手动替换成真实信息，别原样发。")
    return plan


# ---------------------------------------------------------------- 提醒窗口

def toast(title, body, seconds=8):
    try:
        import tkinter as tk
    except ImportError:
        print("[%s] %s\n%s\n" % (datetime.now().strftime("%H:%M:%S"), title, body))
        return
    r = tk.Tk()
    r.title("")
    r.overrideredirect(True)
    r.attributes("-topmost", True)
    w, h = 460, 150
    sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
    r.geometry("%dx%d+%d+%d" % (w, h, sw - w - 24, int(sh * 0.12)))
    r.configure(bg="#ffffff")
    tk.Label(r, text=title, bg="#ffffff", fg="#1a1a1a",
             font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w", padx=16, pady=(14, 4))
    tk.Label(r, text=body, bg="#ffffff", fg="#555555", wraplength=w - 32,
             justify="left", font=("Microsoft YaHei UI", 11)).pack(anchor="w", padx=16)

    def close(e=None):
        r.destroy()

    tk.Button(r, text="知道了", command=close, bg="#f2f2f2",
              relief="flat", width=8).pack(anchor="e", padx=16, pady=(10, 12))
    r.bind("<Button-1>", close)
    r.after(int(seconds * 1000), close)
    r.mainloop()


# ---------------------------------------------------------------- 台账

def _append(row):
    new = not os.path.exists(BOOK_PATH)
    with open(BOOK_PATH, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in COLS})


def _check_phone(s):
    """大陆手机号轻校验，只提示不阻断（固话、座机、带分机号都得放行）。"""
    s = (s or "").strip()
    if not s or re.fullmatch(r"1[3-9]\d{9}", s):
        return ""
    if re.fullmatch(r"0\d{2,3}-?\d{7,8}(-\d{1,6})?", s):
        return ""
    return "  注意：这个号码看着不像手机号（11 位 1 开头）或带区号的固话"


def _prev_row(target):
    """同一天同一目标上一条记录。追加行靠它补齐全字段，避免 xlsx 里大片空列。"""
    if not os.path.exists(BOOK_PATH):
        return None
    day = datetime.now().strftime("%Y-%m-%d")
    with open(BOOK_PATH, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["日期"] == day
                and r["目标"] == target]
    return rows[-1] if rows else None


def _dup_check(target, nick, passed, followed):
    """同一天同一目标被记了多次时给个提醒（不阻断，删了重加是正常操作）。

    注意：「发出 → 通过 → 已聊」本来就是同一个人的三行正常流转，
    所以只有「已经有过已通过记录，现在又要登记通过/跟进」才算可疑。
    """
    if not os.path.exists(BOOK_PATH):
        return None
    day = datetime.now().strftime("%Y-%m-%d")
    with open(BOOK_PATH, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["日期"] == day
                and r["目标"] == target]
    if not rows:
        return None
    prev = rows[-1]
    note = []

    if passed or followed:
        n_passed = sum(1 for r in rows if r["状态"] == "已通过")
        if n_passed >= 2:
            note.append("今天这个人已经被记成「已通过」%d 次了，确认不是重复加了同一个人？" % n_passed)

    pnick = prev["对方昵称备注"].strip()
    if pnick and nick.strip() and pnick != nick.strip():
        note.append("今天上次记的昵称是「%s」，这次填的是「%s」——同一个人的话多半是目标名填重了" % (pnick, nick))
    return "；".join(note)


def cmd_add(a):
    day = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%H:%M")
    prev = _prev_row(a.目标)

    # 「通过」后有「跟进」，跟进那条要沿用上一条的状态，不能退回「待通过」
    if a.通过:
        state = "已通过"
    elif a.跟进:
        state = prev["状态"] if prev else "已通过"
    else:
        state = "待通过"

    # 必须在 _append 之前算，否则会把刚写进去的这一行也算成「重复」
    dup = _dup_check(a.目标, a.昵称, a.通过, a.跟进)

    # 同一人后续登记时补齐前文信息，导出后每行都是完整的
    _append({
        "日期": day,
        "时段": a.时段 or (prev.get("时段", "") if prev else ""),
        "序号": a.序号 or (prev.get("序号", "") if prev else ""),
        "渠道": a.渠道 or (prev.get("渠道", "") if prev else ""),
        "目标": a.目标,
        "微信号": a.微信 or (prev.get("微信号", "") if prev else ""),
        "联系电话": a.电话 or (prev.get("联系电话", "") if prev else ""),
        "对方昵称备注": a.昵称 or (prev.get("对方昵称备注", "") if prev else ""),
        "验证语": a.验证语 or (prev.get("验证语", "") if prev else ""),
        "发出时间": (prev.get("发出时间", "") if prev and not a.通过 else now),
        "状态": state,
        "通过时间": now if a.通过 else (prev.get("通过时间", "") if prev else ""),
        "跟进备注": "已聊" if a.跟进 else ("待聊" if state == "已通过" else ""),
    })

    # 继承后的值才算数：后续行没重填时，也得认它是"有联系方式/有昵称"的
    nick = a.昵称 or (prev.get("对方昵称备注", "") if prev else "")
    wxid = a.微信 or (prev.get("微信号", "") if prev else "")
    phone = a.电话 or (prev.get("联系电话", "") if prev else "")
    label = "%s（%s）" % (a.目标, nick) if nick else a.目标

    if a.通过 and not a.跟进:
        msg = "已登记：%s 已通过 —— 今天记得聊两句，别刚通过就发广告" % label
        if not nick.strip():
            msg += "\n  另外，对方的昵称/备注还没填，回头补一下（通过以后微信里显示的名字）"
    elif a.跟进:
        msg = "已登记：%s 跟进完成" % label
    else:
        msg = "已登记：%s 待通过" % label
    print(msg)

    if a.通过 and not (wxid.strip() or phone.strip()):
        print("  注意：微信号和联系电话都没填——你是靠哪个号搜到的？回头补一眼，"
              "不然过一阵子想复核这单就对不上了")
    if a.电话.strip():
        print(_check_phone(a.电话))

    if dup:
        print("  注意：%s" % dup)


ALIAS = {
    "目标": ["目标", "姓名", "名字", "联系人", "客户", "客户名称", "单位",
             "公司名称", "企业名称", "单位名称", "名称", "昵称"],
    "微信号": ["微信号", "微信", "wxid", "微信号id", "微信id", "wx", "微信号号"],
    "联系电话": ["联系电话", "电话", "手机", "手机号码", "手机号", "座机",
                 "固话", "联系方式", "手机号码1", "手机1"],
    "渠道": ["渠道", "来源", "客户来源", "分组", "通道", "客源"],
    "验证语": ["验证语", "好友验证", "验证", "申请语", "打招呼"],
}


def _norm_header(name):
    return re.sub(r"\s+", "", (name or "")).replace("﻿", "").lower()


def _read_table(path):
    """读 csv / xlsx 名单，返回 (表头列表, 行字典列表)。先试 utf-8 再试 gbk。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        try:
            from openpyxl import load_workbook
        except ImportError:
            print("读 xlsx 需要 openpyxl")
            return None, None
        ws = load_workbook(path, read_only=True, data_only=True).active
        rows = [[("" if c is None else str(c).strip()) for c in row]
                for row in ws.iter_rows(values_only=True)]
    else:
        raw = open(path, "rb").read()
        text = None
        for enc in ("utf-8-sig", "gbk", "utf-8"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            print("这个文件的编码读不出来，另存成 UTF-8 或 GBK 再试")
            return None, None
        rows = [row for row in csv.reader(text.splitlines())]
    rows = [r for r in rows if any((c or "").strip() for c in r)]
    if len(rows) < 2:
        return None, None
    header = [_norm_header(c) for c in rows[0]]
    cols = {}
    for std, keys in ALIAS.items():
        for i, h in enumerate(header):
            if h in keys and "标准_" + std not in cols:
                cols["标准_" + std] = i
                break
    idx = {}
    for std in ALIAS:
        k = "标准_" + std
        if k in cols:
            idx[std] = cols[k]
    return idx, rows[1:]


def cmd_load(a):
    """把现成名单（csv/xlsx）批量登记成「待通过」，省得一条条敲 add。"""
    idx, rows = _read_table(a.file)
    if idx is None:
        print("读不出数据。表头要含「姓名/单位」「电话/手机」「微信号」这类列，"
              "脚本会自己认。")
        return
    if "目标" not in idx:
        print("名单里没找到「姓名 / 单位」这一列，看不出要加谁。")
        return

    day = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%H:%M")
    ok = no_way = no_vmsg = 0
    imported = set()
    # 撞名检查必须在写入之前读台账，否则会把刚导进去的人算成「今天已有」
    exist = set()
    if os.path.exists(BOOK_PATH):
        with open(BOOK_PATH, encoding="utf-8-sig") as f:
            exist = {r["目标"] for r in csv.DictReader(f) if r["日期"] == day}

    for r in rows:
        def get(std):
            i = idx.get(std)
            return r[i] if (i is not None and i < len(r)) else ""

        target = get("目标").strip()
        if not target:
            continue
        phone = get("联系电话").strip()
        wxid = get("微信号").strip()
        ch = get("渠道").strip()
        # 验证语刻意不自动填：文案库模板是套话，自动套上去等于群发广告，
        # 这里留空，等你自己去台账补一句带真人来源的话
        vmsg = get("验证语").strip()

        _append({
            "日期": day, "时段": "", "序号": "", "渠道": ch, "目标": target,
            "微信号": wxid, "联系电话": phone, "对方昵称备注": "",
            "验证语": vmsg, "发出时间": now, "状态": "待通过",
            "通过时间": "", "跟进备注": "",
        })
        ok += 1
        imported.add(target)
        if not (wxid or phone):
            no_way += 1
        if not vmsg:
            no_vmsg += 1
        warn = _check_phone(phone)
        if warn:
            print("  %s %s" % (target, warn))

    print("已从 %s 导入 %d 人" % (os.path.basename(a.file), ok))

    # 名单里撞上今天已经记过的人，多半是同一个名单导了第二遍
    clash = sorted(exist & imported)
    if clash:
        print("  今天台账里已经有 %d 个同名的人（%s），确认不是同一个名单导了两遍？"
              % (len(clash), "、".join(sorted(clash)[:4])))

    if no_way:
        print("  %d 个人没填联系方式——没号就没法搜到人，加之前补上" % no_way)
    if no_vmsg:
        print("  %d 个人还没写验证语（这条刻意没自动填，套话模板发出去等于群发广告），"
              "直接编辑 加人台账.csv 补一句带真人来源的" % no_vmsg)


def cmd_followup(a):
    if not os.path.exists(BOOK_PATH):
        print("台账还是空的")
        return
    today = datetime.now().strftime("%Y-%m-%d")
    latest = {}          # 同一个人可能被写多行（发出 / 通过 / 聊过），只认最新那条
    with open(BOOK_PATH, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["日期"] == today:
                latest[r["目标"]] = r
    rows = [v for v in latest.values()
            if v["状态"] == "已通过" and v["跟进备注"].strip() != "已聊"]
    print("今日待跟进（%d 人）：" % len(rows))
    for r in rows:
        who = r["对方昵称备注"].strip() or r["目标"]
        tag = "" if r["对方昵称备注"].strip() else "（还没记昵称）"
        last = r["验证语"][:18] or r["渠道"]
        print("  - %s%s ｜ %s ｜ %s" % (who, tag, r["渠道"], last))
    if not rows:
        print("  没有待跟进的，说明你当天已经跟过了。")


def cmd_status(a):
    if not os.path.exists(SCHED_PATH):
        print("先跑：python planner.py plan")
        return
    if not os.path.exists(BOOK_PATH):
        print("今日计划 %d 条 / 台账还是空的，加完用 add 登记" % len(_plan_rows()))
        return
    today = datetime.now().strftime("%Y-%m-%d")
    sent = 0
    latest = {}          # 同名取最新一条，和 followup 口径一致
    with open(BOOK_PATH, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["日期"] != today:
                continue
            sent += 1
            latest[r["目标"]] = r
    passed = sum(1 for r in latest.values() if r["状态"] == "已通过")
    with open(SCHED_PATH, encoding="utf-8") as f:
        plan = json.load(f)
    print("今日进度：计划 %d 条 / 已发 %d 条 / 已通过 %d 条"
          % (len(plan), sent, passed))
    names = [r["对方昵称备注"].strip() or r["目标"]
             for r in latest.values() if r["状态"] == "已通过"]
    missing_nick = sum(1 for r in latest.values()
                       if r["状态"] == "已通过" and not r["对方昵称备注"].strip())
    print("已通过：%s" % ("、".join(names) or "无"))
    if missing_nick:
        print("  有 %d 个通过的人还没填昵称备注，回头补一眼（日后清理僵尸粉要用得上）"
              % missing_nick)
    if sent >= len(plan):
        print("今日计划已完成，别加超量——超额比量小更容易触发风控。")


def cmd_sheet(a):
    try:
        from openpyxl import Workbook
    except ImportError:
        print("需要 openpyxl：C:/Python314/python.exe -m pip install openpyxl")
        return
    wb = Workbook()
    ws = wb.active
    ws.title = "加人台账"
    ws.append(COLS)
    from openpyxl.styles import Font, Alignment, PatternFill
    from openpyxl.utils import get_column_letter
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = "A1:%s1" % get_column_letter(len(COLS))
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="E8EEF7")
        c.alignment = Alignment(horizontal="center", vertical="center")
    widths = {"日期": 12, "时段": 10, "序号": 6, "渠道": 14, "目标": 22,
              "微信号": 22, "联系电话": 16, "对方昵称备注": 22, "验证语": 40,
              "发出时间": 10, "通过时间": 10, "状态": 10, "跟进备注": 10}
    for i, c in enumerate(ws[1], 1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(c.value, 14)
    if os.path.exists(BOOK_PATH):
        with open(BOOK_PATH, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                ws.append([r.get(c, "") for c in COLS])
    out = os.path.join(BASE, "加人台账.xlsx")
    wb.save(out)
    print("已导出：%s" % out)


def _plan_rows():
    if not os.path.exists(SCHED_PATH):
        return []
    with open(SCHED_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_fired(k, seqs):
    data = {}
    if os.path.exists(FIRED_PATH):
        data = json.load(open(FIRED_PATH, encoding="utf-8"))
    data[k] = seqs
    with open(FIRED_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def cmd_run(a):
    """常驻：按时刻表弹提醒 + 到点催跟进。不会动微信一根手指。"""
    cfg = load_cfg()
    fire_at = cfg.get("跟进检查点", "10:00")
    print("提醒器已启动 %s。Ctrl+C 退出。" % datetime.now().strftime("%H:%M:%S"))
    follow_done = set()

    while True:
        now = datetime.now()
        k = now.strftime("%Y-%m-%d")
        cur = now.hour * 60 + now.minute

        # 1) 到点的加人提醒，一次只弹一条
        fired_today = []
        if os.path.exists(FIRED_PATH):
            fired_today = json.load(open(FIRED_PATH, encoding="utf-8")).get(k, [])
        due = [p for p in _plan_rows()
               if p["分钟"] <= cur and p["序号"] not in fired_today]
        if due:
            p = sorted(due, key=lambda x: x["分钟"])[0]
            _save_fired(k, fired_today + [p["序号"]])
            toast("该加第 %d 个了 · %s" % (p["序号"], p["渠道"]),
                  "验证语：%s\n（把 {} 换成真名字，别原样发）" % p["文案"])

        # 2) 每日一次跟进催办（只弹一次）
        if now.strftime("%H:%M") == fire_at and k not in follow_done:
            follow_done.add(k)
            try:
                import io
                buf = io.StringIO()
                old, sys.stdout = sys.stdout, buf
                cmd_followup(None)
                sys.stdout = old
                body = [x for x in buf.getvalue().splitlines() if x.strip()]
                if len(body) > 1:
                    toast("今天该聊几句了", "\n".join(body[1:6]))
            except Exception:
                pass

        time.sleep(20)


def main():
    p = argparse.ArgumentParser(description="微信加人节奏管理器（仅提醒与台账）")
    s = p.add_subparsers(dest="cmd")

    a = s.add_parser("plan", help="生成今天的等间距打散时刻表")
    a.add_argument("--date", help="YYYY-MM-DD，默认今天")
    a.set_defaults(fn=cmd_plan)

    a = s.add_parser("run", help="常驻提醒（Ctrl+C 退出）")
    a.set_defaults(fn=cmd_run)

    a = s.add_parser("add", help="手动加完登记一行")
    a.add_argument("--渠道", required=True)
    a.add_argument("--目标", required=True, help="你搜索时用的名字/公司/群名")
    a.add_argument("--微信", default="", dest="微信",
                   help="对方的微信号（wxid 或 微信号串）")
    a.add_argument("--电话", default="", dest="电话",
                   help="对方的联系电话（手机号或带区号固话），靠号码加人就填这个")
    a.add_argument("--昵称", default="", dest="昵称",
                   help="对方通过后在微信里显示的昵称，或你给他起的备注名")
    a.add_argument("--验证语", default="")
    a.add_argument("--时段", default="")
    a.add_argument("--序号", default="")
    a.add_argument("--通过", action="store_true", help="对方已通过")
    a.add_argument("--跟进", action="store_true", help="已聊过（自动标记跟进完成）")
    a.set_defaults(fn=cmd_add)

    a = s.add_parser("load", help="从名单 csv/xlsx 批量登记待通过")
    a.add_argument("file")
    a.set_defaults(fn=cmd_load)

    a = s.add_parser("followup", help="今日待跟进清单")
    a.set_defaults(fn=cmd_followup)

    a = s.add_parser("status", help="今日进度")
    a.set_defaults(fn=cmd_status)

    a = s.add_parser("sheet", help="导出 xlsx 台账")
    a.set_defaults(fn=cmd_sheet)

    args = p.parse_args()
    if not getattr(args, "fn", None):
        p.print_help()
        return
    args.fn(args)


if __name__ == "__main__":
    main()
