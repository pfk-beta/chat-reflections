"""Markdown -> HTML with math protected from the markdown parser.

Math is emitted as escaped TeX in `<span class="math">` (`.display` for block math) and
rendered client-side by KaTeX. Supported delimiters: `$..$`, `$$..$$`, `\\(..\\)`, `\\[..\\]`.
"""

from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml
from markdown_it.rules_inline import StateInline
from markdown_it.token import Token
from mdit_py_plugins.dollarmath import dollarmath_plugin

_BRACKETS = {"\\(": ("\\)", "math_inline"), "\\[": ("\\]", "math_inline_double")}


def _bracket_math(state: StateInline, silent: bool) -> bool:
    """`\\(..\\)` / `\\[..\\]` anywhere in inline text, also mid-paragraph."""
    opener = state.src[state.pos : state.pos + 2]
    if opener not in _BRACKETS:
        return False
    closer, token_type = _BRACKETS[opener]
    end = state.src.find(closer, state.pos + 2)
    if end < 0:
        return False
    if not silent:
        state.push(token_type, "math", 0).content = state.src[state.pos + 2 : end].strip()
    state.pos = end + 2
    return True


def _alone_on_line(tokens: list[Token], idx: int) -> bool:
    def edge(i: int) -> bool:
        while 0 <= i < len(tokens) and tokens[i].type == "text" and not tokens[i].content.strip():
            i += -1 if i < idx else 1
        return not 0 <= i < len(tokens) or tokens[i].type in ("softbreak", "hardbreak")

    return edge(idx - 1) and edge(idx + 1)


def _render(display: bool | None):
    """display=None: block math only when alone on its line (`$$`/`\\[` used mid-sentence)."""

    def rule(self, tokens: list[Token], idx: int, options, env) -> str:
        block = _alone_on_line(tokens, idx) if display is None else display
        cls = "math display" if block else "math"
        return f'<span class="{cls}">{escapeHtml(tokens[idx].content)}</span>'

    return rule


md = (
    MarkdownIt("commonmark", {"html": False, "breaks": True})
    .enable("table")
    .use(dollarmath_plugin, allow_space=False, allow_digits=False, double_inline=True)
)
md.inline.ruler.before("escape", "math_bracket", _bracket_math)
md.add_render_rule("math_inline", _render(False))
md.add_render_rule("math_inline_double", _render(None))
for t in ("math_block", "math_block_label"):
    md.add_render_rule(t, _render(True))


def render(text: str) -> str:
    return md.render(text)
