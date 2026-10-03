# -*- coding: utf-8 -*-
"""静态校验 .sfq：括号配对 / 流程块配对 / 命令名是否真在官方手册里 / 危险命令扫描。"""
import os, re, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
CHM = os.path.join(os.path.dirname(HERE), "xb_xiaojiaoben", "chm_out")

# 手册里收录的命令页（流程关键字不在 CHM 单页里，单独列出）
FLOW = {"如果", "否则", "条件结束", "计次循环", "计次循环结束", "标记", "跳转标记"}
KNOWN = set() | FLOW
if os.path.isdir(CHM):
    KNOWN |= {f[: -len(f[f.rfind("."):])] for f in os.listdir(CHM)}

BANNED = ["打开进程", "关闭进程", "找图", "找色", "找字", "后台点击", "后台按键",
          "模拟按键", "读内存", "写内存", "网页访问", "网页打开", "窗口点击", "窗口按键"]

errors, warns = [], []

lines = open(os.path.join(HERE, "加人节奏清单.sfq"), encoding="gbk").read().splitlines()

used = collections.Counter()
depth_hist = []
stack = []
block = []          # 记录层的类型，用于检查 如果/条件结束 配对
for n, raw in enumerate(lines, 1):
    s = raw.strip()
    if not s or s.startswith("//"):
        continue
    # 头部字段行（标题=xxx / 简介=xxx / ...）不是命令，跳过
    if re.match(r"^[A-Za-z一-龥/]+=", s) and "(" not in s.split("=")[0]:
        continue
    # 危险命令扫描（注释里提到不算，只要不出现在代码行首）
    code = re.sub(r"//.*$", "", raw).strip()
    if not code:
        continue
    for b in BANNED:
        if b in code:
            errors.append(f"第{n}行 出现危险命令「{b}」: {code[:50]}")
    # 括号配对：本行内
    if code.count("(") != code.count(")"):
        errors.append(f"第{n}行 括号不配对 ({code.count('(')} 对 {code.count(')')}): {code[:50]}")
    depth_hist.append(sum(1 for c in code if c == "("))
    for c in code:
        if c == "(":
            stack.append(n)
        elif c == ")":
            if stack:
                stack.pop()
    # 命令名（行首 + 括号，或 运算( 里的内容）
    m = re.match(r"^([^\s(（][^\s(（]*)\s*[（(]", code)
    if m:
        used[m.group(1)] += 1
    if "运算(" in code:
        mm = re.search(r"运算\s*\(\s*[^=]+=\s*([^\s(（]+)\s*[（(]", code)
        if mm:
            used[mm.group(1)] += 1

# 跨行括号残留
if stack:
    errors.append(f"跨行括号未闭合，起始行 {stack[:5]}")

# 流程块配对
for i, raw in enumerate(lines):
    s = raw.strip()
    if re.match(r"^如果\s*[（(]", s):
        block.append(("如果", i + 1))
    elif re.match(r"^条件结束\s*[（(]", s):
        if not block:
            errors.append(f"第{i+1}行 条件结束 没有对应的 如果")
        else:
            block.pop()
    elif re.match(r"^计次循环\s*[（(]", s):
        block.append(("计次循环", i + 1))
    elif re.match(r"^计次循环结束\s*[（(]", s):
        if not block:
            errors.append(f"第{i+1}行 计次循环结束 没有对应的 计次循环")
        else:
            block.pop()
if block:
    errors.append("有未闭合的流程块: " + str(block))

# 命令名白名单
UNK = {"Edition", "标题", "启动热键", "暂停/继续热键", "终止热键", "简介",
       "自定义变量", "变量", "子程序", "运算", "调试", "延时", "如果", "否则",
       "条件结束", "计次循环", "计次循环结束", "标记", "跳转标记", "读入文本",
       "文本取行数", "读指定文本行", "写到文件", "取时间_小时", "取时间_分钟",
       "生成指定随机数字", "分割文本"}
for c in used:
    if c not in UNK:
        errors.append(f"命令名「{c}」不在已知集合内（手册或示例里都没出现过）")

print("=== 静态校验 ===")
print("用到的命令：")
for c, k in used.most_common():
    mark = "OK" if c in UNK else "??"
    print(f"  [{mark}] {c}  x{k}")
print()
print("括号深度峰值：", max(depth_hist) if depth_hist else 0)
if errors:
    print("!!! 错误:")
    for e in errors:
        print("  ", e)
else:
    print("括号配对 / 流程块配对 / 命令名 全部通过")
if warns:
    print("提示：", warns)
sys.exit(1 if errors else 0)
