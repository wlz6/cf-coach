import re
from typing import Optional

try:
    from pylatexenc.latex2text import LatexNodes2Text
    _HAS_PYLATEXENC = True
except ImportError:
    _HAS_PYLATEXENC = False

SUPERSCRIPT_MAP = str.maketrans("0123456789+-=()nxyz", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿˣʸᶻ")
SUBSCRIPT_MAP = str.maketrans("0123456789+-=()aeijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ")


def format_inline_tex(formula: str) -> str:
    """将单条 LaTeX 行内公式解析转换为美观的 Unicode 字符表达。"""
    raw = formula.strip()
    if not raw:
        return ""

    # 预处理常见模式
    processed = re.sub(r'\\pmod\{([^}]+)\}', r'(mod \1)', raw)
    processed = re.sub(r'\\bmod\{([^}]+)\}', r'mod \1', processed)
    processed = re.sub(r'\\mathcal\{O\}', '𝒪', processed)
    processed = re.sub(r'\\mathcal\{([^}]+)\}', r'\1', processed)

    if _HAS_PYLATEXENC:
        try:
            converter = LatexNodes2Text(math_mode='text')
            res = converter.latex_to_text(processed).strip()
        except Exception:
            res = processed
    else:
        # 轻量基础符号回退字典
        symbol_map = {
            r'\le': '≤', r'\leq': '≤', r'\ge': '≥', r'\geq': '≥',
            r'\ne': '≠', r'\neq': '≠', r'\in': '∈', r'\notin': '∉',
            r'\cdot': '·', r'\times': '×', r'\oplus': '⊕', r'\otimes': '⊗',
            r'\sum': '∑', r'\prod': '∏', r'\infty': '∞',
            r'\lfloor': '⌊', r'\rfloor': '⌋', r'\lceil': '⌈', r'\rceil': '⌉',
            r'\approx': '≈', r'\pm': '±', r'\mp': '∓',
        }
        res = processed
        for k, v in symbol_map.items():
            res = res.replace(k, v)

    # 转换上标：形如 ^5 或 ^{10}
    res = re.sub(r'\^{?([0-9+\-nxyz]+)}?', lambda m: m.group(1).translate(SUPERSCRIPT_MAP), res)
    # 转换下标：形如 _i 或 _{12}
    res = re.sub(r'_([0-9a-z])', lambda m: m.group(1).translate(SUBSCRIPT_MAP), res)
    res = re.sub(r'_{([0-9a-z]+)}', lambda m: m.group(1).translate(SUBSCRIPT_MAP), res)

    # 去除多余连续空格
    res = re.sub(r'\s+', ' ', res)
    return res


def convert_tex_in_markdown(text: str) -> str:
    """遍历 Markdown 正文，将 $...$ 与 $$...$$ 中的 TeX 公式转换为终端可读的 Unicode。"""
    if not text:
        return ""

    # 1. 处理块级公式 $$...$$
    def replace_block(match):
        inner = match.group(1).strip()
        formatted = format_inline_tex(inner)
        return f"\n> **[公式]** `{formatted}`\n"

    res = re.sub(r'\$\$(.+?)\$\$', replace_block, text, flags=re.DOTALL)

    # 2. 处理行内公式 $...$（排除转义 \$ 以及代码块内的美元符）
    def replace_inline(match):
        inner = match.group(1).strip()
        formatted = format_inline_tex(inner)
        return f"`{formatted}`"

    res = re.sub(r'(?<!\\)\$(.+?)(?<!\\)\$', replace_inline, res)
    return res
