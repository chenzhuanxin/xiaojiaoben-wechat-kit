# -*- coding: utf-8 -*-
"""
按《小脚本4.86》手册语义，模拟执行 加人节奏清单.sfq。
目的：不启动 exe、不碰微信，只验证脚本的「名单解析 / 条件分支 / 拼接 / 随机范围」逻辑对不对。
"""
import os, re, sys, random

HERE = os.path.dirname(os.path.abspath(__file__))
random.seed(0)

# ---------- 1. 读取并清洗 ----------
raw = open(os.path.join(HERE, "加人节奏清单.sfq"), encoding="gbk").read()
lines = []
for l in raw.splitlines():
    l = re.sub(r"//.*$", "", l).strip()
    if l:
        lines.append(l)

cfg_vars, VARS = {}, {}
# 头部字段行不参与执行（Edition/标题/启动热键/简介/自定义变量/变量）
instr = []          # (类型, 数据)
for l in lines:
    if re.match(r"^(自定义变量|变量)\s*[（(]", l):        # 声明行，单独吃掉
        body = l.split("(", 1)[1].rstrip(");")            # 取括号内那一段
        if l.startswith("自定义变量"):
            for kv in body.split(","):
                if "=" in kv:
                    a, b = kv.split("=", 1)
                    cfg_vars[a.strip()] = b.strip().strip('"')
        else:
            for x in body.split(","):
                VARS[x.strip()] = ""
        continue
    if re.match(r"^[A-Za-z一-龥/]+=", l):
        m = re.match(r"^([^=]+)=(.*)$", l)
        k, v = m.group(1), m.group(2)
        if k == "自定义变量":
            for kv in v.split(","):
                if "=" in kv:
                    a, b = kv.split("=", 1)
                    cfg_vars[a.strip()] = b.strip().strip('"')
        elif k == "变量":
            for a in v.replace(";", "").split(","):
                VARS[a.strip()] = ""
        continue
    if re.match(r"^子程序\s*[（(]", l):
        instr.append(("SUB", l))
        continue
    # 长关键字必须排在前面，否则 计次循环结束 会被 计次循环 抢先匹配
    m = re.match(r"^(计次循环结束|条件结束|如果|否则|跳转标记|标记|计次循环)\s*[（(]?(.*?)\)?;?$", l)
    if m:
        kw, arg = m.group(1), m.group(2).strip()
        instr.append((kw, arg))
    else:
        instr.append(("CMD", l))

for i, (kw, arg) in enumerate(instr):
    if kw == "如果":
        instr[i] = ("IF", arg)
    elif kw == "否则":
        instr[i] = ("ELSE", arg)
    elif kw == "条件结束":
        instr[i] = ("ENDIF", arg)
    elif kw == "计次循环":
        instr[i] = ("LOOP", arg)
    elif kw == "计次循环结束":
        instr[i] = ("ENDLOOP", arg)
    elif kw == "标记":
        instr[i] = ("MARK", arg)
    elif kw == "跳转标记":
        instr[i] = ("JUMP", arg)

# 参数切分（按顶层逗号）
def split_args(s):
    out, d, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            d += 1
        elif ch == ")":
            d -= 1
        if ch == "," and d == 0:      # 只按半角逗号切，中文逗号是内容的一部分
                out.append(cur.strip()); cur = ""
                continue
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out

# ---------- 2. 表达式求值 ----------
def getv(name):
    return VARS.get(name, "")

def unq(t):
    t = t.strip()
    if t.startswith('"') and t.endswith('"') and len(t) >= 2:
        return t[1:-1]
    if t == "#换行":
        return "\n"
    return t

def eval_expr(e, depth=0):
    e = e.strip()
    if depth > 12:
        return ""
    # 下标 a[2]
    m = re.fullmatch(r"([^\s\[\]]+)\s*\[\s*(\d+)\s*\]", e)
    if m:
        arr = eval_expr(m.group(1), depth + 1)
        try:
            idx = int(m.group(2))
        except ValueError:
            return ""
        if isinstance(arr, list):
            return arr[idx] if 1 <= idx <= len(arr) else ""
        return arr
    # 函数
    m = re.match(r"^(生成指定随机数字|生成随机数字|分割文本|取中间文本)\s*[（(](.*)[）)]$", e)
    if m:
        fn, inner = m.group(1), m.group(2)
        a = [x.strip() for x in split_args(inner)]
        if fn == "生成指定随机数字":
            return str(random.randint(int(a[0]), int(a[1])))
        if fn == "分割文本":
            txt = eval_expr(a[0], depth + 1)
            sep = unq(a[1])
            parts = txt.split(sep)
            return [""] + parts          # 手册：数组从 1 开始
        if fn == "取中间文本":
            pass
    # 字面量 / 变量（必须整串被一对引号包住，内部不能再有引号，否则是拼接式）
    m0 = re.fullmatch(r'"([^"]*)"', e)
    if m0:
        return m0.group(1)
    if e == "#换行":
        return "\n"
    if re.fullmatch(r"-?\d+", e):
        return e
    if re.fullmatch(r"[一-龥A-Za-z_][一-龥A-Za-z0-9_]*", e):
        return getv(e)
    # 运算链（手册：不支持括号、不支持优先级，一律左到右）
    toks = re.split(r"\s*([+*])\s*", e)
    if len(toks) >= 3:
        cur = eval_expr(toks[0], depth + 1)
        for k in range(1, len(toks), 2):
            op, rhs = toks[k].strip(), eval_expr(toks[k + 1], depth + 1)
            if op == "*":
                try:
                    cur = float(cur) * float(rhs)
                except ValueError:
                    cur = str(cur) * int(float(rhs))
            else:
                cur = str(cur) + str(rhs)
        return cur
    raise RuntimeError("表达式解析不了: " + e)

# ---------- 3. 主执行 ----------
trace = []          # 模拟 调试 输出
delays = []
log_lines = []
files = {}
PC = 0
IF_STACK = []
MARKS ={instr[i][1]: i for i in range(len(instr)) if instr[i][0] == "MARK"}
VARS.update(cfg_vars)          # 自定义变量 等同普通变量，到处都能读写

def setv(name, val):
    VARS[name] = val

def eval_cond(c):
    """支持 变量 比较 值 [且/或] 变量 比较 值"""
    c = c.strip()
    parts = re.split(r"\s+且\s+|\s+或\s+", c)
    joiner = "且" if "且" in c else ("或" if "或" in c else None)
    res = []
    for p in parts:
        m = re.match(r"^(.+?)\s*(>|<|>=|<=|=|≠|<>)(\s*)(.+)$", p)
        if not m:
            raise RuntimeError("条件解析不了: " + p)
        lv, op, rv = m.group(1).strip(), m.group(2), m.group(4).strip()
        a = str(eval_expr(lv)).strip()
        b = str(eval_expr(rv)).strip()
        try:
            x, y = float(a), float(b)
        except ValueError:
            x, y = a, b
        if op in (">",): r = x > y
        elif op == "<": r = x < y
        elif op == ">=": r = x >= y
        elif op == "<=": r = x <= y
        elif op == "=": r = a == b
        else: r = a != b
        res.append(r)
    if not joiner:
        return res[0]
    return all(res) if joiner == "且" else any(res)

if os.environ.get("SFQ_DEBUG"):
    print("[debug] cfg_vars =", cfg_vars)
    print("[debug] VARS =", {k: v for k, v in VARS.items() if not k.startswith("__")})

steps = 0
while PC < len(instr):
    steps += 1
    if steps > 5000:
        print("!! 可能死循环"); break
    kw, arg = instr[PC]
    if kw in ("MARK", "SUB"):      # SUB：子程序定义只是声明，不主动执行
        PC += 1; continue
    if kw == "ENDIF":
        if IF_STACK:
            IF_STACK.pop()
        PC += 1; continue
    if kw == "ELSE":
        # 条件成立时执行到 否则 就该跳过整个否则块
        if IF_STACK and IF_STACK[-1][1] is True:
            layer = arg
            end_i = next((i for i in range(PC, len(instr))
                          if instr[i][0] == "ENDIF" and instr[i][1] == layer), None)
            PC = (end_i + 1) if end_i is not None else PC + 1
        else:
            PC += 1
        continue
    if kw == "JUMP":
        PC = MARKS[arg]; continue
    if kw == "IF":
        m = re.match(r"^(.*?)\s*,\s*([^,]+)$", arg)
        cond_s, layer = (m.group(1), m.group(2).strip()) if m else (arg, "L%d" % PC)
        cond = eval_cond(cond_s)
        else_i = next((i for i in range(PC, len(instr))
                       if instr[i][0] == "ELSE" and instr[i][1] == layer), None)
        end_i = next((i for i in range(PC, len(instr))
                      if instr[i][0] == "ENDIF" and instr[i][1] == layer), None)
        IF_STACK.append((layer, cond))
        if not cond:
            PC = (else_i + 1) if else_i is not None else ((end_i or len(instr)))
        else:
            PC += 1
        continue
    if kw == "LOOP":
        a = split_args(arg)
        total, idx, group = a[0], a[1], a[2]
        total = int(str(eval_expr(total)).strip())
        VARS["__loop_total"] = total
        VARS["__loop_i"] = 1                       # 手册：循环下标从 1 开始
        VARS[VARS.get("__loop_idx", idx)] = 1
        VARS["__loop_pc"] = PC + 1
        VARS["__loop_end"] = next((i for i in range(PC, len(instr))
                                   if instr[i][0] == "ENDLOOP" and instr[i][1] == group), len(instr))
        PC += 1
        continue
    if kw == "ENDLOOP":
        t = int(str(VARS.get("__loop_total", 0)).strip())
        n = int(str(VARS.get("__loop_i", 0)).strip()) + 1
        if n <= t:
            VARS["__loop_i"] = n
            VARS[VARS.get("__loop_idx", "i")] = n
            PC = int(str(VARS.get("__loop_pc", PC)).strip())
            continue
        PC += 1
        continue
    # ---- 普通命令 ----
    l = arg
    m = re.match(r"^([一-龥A-Za-z_][一-龥A-Za-z0-9_]*)\s*[（(](.*)[）)];?\s*$", l)
    if not m:
        PC += 1; continue
    cmd, body = m.group(1), m.group(2)
    a = [x.strip() for x in split_args(body)]
    if cmd == "调试":
        trace.append(" ".join(str(eval_expr(x)) for x in a))
    elif cmd == "延时":
        delays.append(int(eval_expr(a[0])))
    elif cmd == "读入文本":
        setv(a[1], files.get(unq(a[0]), open(os.path.join(HERE, unq(a[0])), encoding="gbk").read()))
    elif cmd == "文本取行数":
        setv(a[1], len(str(getv(a[0])).splitlines()))
    elif cmd == "读指定文本行":
        src = files.get(unq(a[0]), open(os.path.join(HERE, unq(a[0])),
                                       encoding="gbk").read())
        setv(a[2], src.splitlines()[int(str(eval_expr(a[1])).strip()) - 1])
    elif cmd == "写指定文本行":
        pass
    elif cmd == "写到文件":
        files[unq(a[0])] = str(eval_expr(a[1]))
    elif cmd == "取时间_小时":
        setv(a[0], sys.argv[1] if len(sys.argv) > 1 else "19")
    elif cmd == "取时间_分钟":
        setv(a[0], "04")
    elif cmd == "运算":
        m2 = re.match(r"^([^=]+)=(.*)$", body)
        if m2:
            setv(m2.group(1).strip(), eval_expr(m2.group(2)))
        else:
            eval_expr(body)
    else:
        raise RuntimeError("解释不了的命令: %s" % cmd)
    PC += 1

# ---------- 4. 报告 ----------
out = []
out.append("=== 调试输出（脚本按 F9 后你会在小脚本「调试输出」框看到这些）===")
out.append("  " + "  ".join(trace))
out.append("")
out.append("=== 今日清单.txt（脚本 写到文件 落盘的内容）===")
out.append(files.get("今日清单.txt", "(没生成)"))
out.append("")
out.append("=== 延时序列（毫秒，未真等）===")
mv = int(cfg_vars.get("演练倍数", 1))
out.append("  共 %d 次，每次 = 随机(240,420) 秒 × 1000 × 演练倍数(%s)" % (len(delays), mv))
out.append("  真实节奏区间：240~420 秒，共 %d 条，总长约 %.0f 分钟"
           % (len(delays), len(delays) * 330 / 60))
out.append("")
out.append("=== 变量终值抽查 ===")
for k in ["目标名", "搜索号", "电话号", "渠道", "验证语"]:
    if k in VARS:
        out.append("  %s=%r" % (k, VARS[k]))
print("\n".join(out))
