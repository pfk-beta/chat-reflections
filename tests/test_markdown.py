from chat_reflections.markdown import render


def test_bracket_math_survives_markdown() -> None:
    assert '<span class="math">2 \\times 10^{-5}</span>' in render(r"to \(2 \times 10^{-5}\).")
    html = render("**F:**\n\\[ \\eta = \\frac{a}{b} \\]")
    assert '<span class="math display">\\eta = \\frac{a}{b}</span>' in html


def test_dollar_math() -> None:
    assert '<span class="math">\\sqrt{k}</span>' in render(r"by $\sqrt{k}$ ok")
    assert '<span class="math display">' in render("$$\nE=mc^2\n$$")


def test_no_false_positives() -> None:
    assert "math" not in render("costs $5 and $10, echo $HOME and $PATH")
    assert "math" not in render("`\\(x\\)`\n\n```\n$x$ \\[y\\]\n```")


def test_math_escaped() -> None:
    assert "<script>" not in render(r"\(<script>\)")


def test_double_math_mid_sentence_is_inline() -> None:
    html = render(r"reguła $$ x^n $$, np. \[ y \] koniec")
    assert html.count('<span class="math">') == 2 and "display" not in html
    assert '<span class="math display">' in render("Wzór:\n\\[ y = x \\]\ndalej")
