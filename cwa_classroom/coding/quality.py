"""
coding.quality
~~~~~~~~~~~~~~
Static code-quality analysis for student submissions.

Produces a *quality multiplier* (0.70 – 1.00) that is applied on top of the
base accuracy+speed score so that correct-but-inefficient solutions earn
proportionally fewer points than clean, efficient ones.

Supported languages
-------------------
python      — full AST analysis via the stdlib `ast` module (exact)
javascript  — regex/heuristic analysis (no external deps required)
html / css  — not analysed; quality_score = 1.0 (browser-sandbox only)
scratch     — not analysed; quality_score = 1.0

Quality metrics
---------------
1. Cyclomatic complexity   — counts independent execution paths
2. Maximum nesting depth   — deepest level of nested loops / conditionals
3. Maximum loop-nesting    — deepest level of nested *loops* specifically
                             (proxy for O(n^k) algorithms)
4. Redundant loop calls    — cheap-to-hoist calls repeated inside a loop
                             (e.g. `len(xs)` every iteration)

Penalty schedule
----------------
Each metric contributes a fractional penalty (0.0–0.30).  Total penalties are
capped at QUALITY_MAX_PENALTY (default 0.30) so the multiplier stays ≥ 0.70.

Callers can override the cap via the `max_penalty` parameter.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import List


# ---------------------------------------------------------------------------
# Public data class
# ---------------------------------------------------------------------------

@dataclass
class QualityResult:
    """Result of a single quality analysis pass."""

    # 0.70 – 1.00 multiplier applied to the base score
    quality_score: float = 1.0

    # Human-readable issues (shown in teacher/admin views, not to students)
    issues: List[str] = field(default_factory=list)

    # Raw metrics (stored for audit / statistics)
    cyclomatic_complexity: int = 1
    max_nesting_depth: int = 0
    max_loop_depth: int = 0
    redundant_loop_calls: int = 0

    # True when the source could not be parsed (parse error → no penalty)
    parse_error: bool = False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyse_code_quality(
    code: str,
    language_slug: str,
    max_penalty: float = 0.30,
) -> QualityResult:
    """Analyse *code* for the given *language_slug* and return a QualityResult.

    Args:
        code:           Raw source code submitted by the student.
        language_slug:  One of 'python', 'javascript', 'html', 'css',
                        'html-css', 'scratch'.  Unknown slugs get a
                        pass-through score of 1.0.
        max_penalty:    Maximum total penalty (0.0–1.0).  Defaults to 0.30 so
                        a correct solution always scores ≥ 70 pts.

    Returns:
        QualityResult with quality_score in [1.0 - max_penalty, 1.0].
    """
    slug = (language_slug or '').lower()

    if slug == 'python':
        result = _analyse_python(code)
    elif slug == 'javascript':
        result = _analyse_javascript(code)
    else:
        # HTML, CSS, Scratch — browser-evaluated, no server-side analysis
        return QualityResult(quality_score=1.0)

    # Apply global cap
    total_penalty = 1.0 - result.quality_score
    if total_penalty > max_penalty:
        total_penalty = max_penalty
    result.quality_score = round(1.0 - total_penalty, 4)
    return result


# ---------------------------------------------------------------------------
# Python analysis  (exact — uses stdlib `ast`)
# ---------------------------------------------------------------------------

class _ComplexityVisitor(ast.NodeVisitor):
    """Single-pass AST visitor measuring complexity and nesting."""

    def __init__(self) -> None:
        # Cyclomatic complexity starts at 1 (the default path)
        self.complexity: int = 1
        self.max_depth: int = 0
        self.max_loop_depth: int = 0

        self._depth: int = 0        # current structural depth
        self._loop_depth: int = 0   # current loop-nesting depth

    # -- depth helpers -------------------------------------------------------

    def _push(self, is_loop: bool = False) -> None:
        self._depth += 1
        if self._depth > self.max_depth:
            self.max_depth = self._depth
        if is_loop:
            self._loop_depth += 1
            if self._loop_depth > self.max_loop_depth:
                self.max_loop_depth = self._loop_depth

    def _pop(self, is_loop: bool = False) -> None:
        self._depth -= 1
        if is_loop:
            self._loop_depth -= 1

    # -- branch nodes --------------------------------------------------------

    def visit_If(self, node: ast.If) -> None:
        self.complexity += 1
        self._push()
        self.generic_visit(node)
        self._pop()

    def visit_IfExp(self, node: ast.IfExp) -> None:
        # Ternary `a if cond else b` — also adds a branch
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.complexity += 1
        self._push(is_loop=True)
        self.generic_visit(node)
        self._pop(is_loop=True)

    def visit_While(self, node: ast.While) -> None:
        self.complexity += 1
        self._push(is_loop=True)
        self.generic_visit(node)
        self._pop(is_loop=True)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        self._push()
        self.generic_visit(node)
        self._pop()

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        # Each extra operand in `a and b and c` adds a branch
        self.complexity += len(node.values) - 1
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        # Each `if` guard inside a comprehension adds a branch
        self.complexity += len(node.ifs)
        self._loop_depth += 1
        if self._loop_depth > self.max_loop_depth:
            self.max_loop_depth = self._loop_depth
        self.generic_visit(node)
        self._loop_depth -= 1


class _RedundancyVisitor(ast.NodeVisitor):
    """Count calls inside loops that are cheap to hoist outside.

    Targets pure, side-effect-free builtins whose arguments are unlikely to
    change between iterations: len, sorted, reversed, list, tuple, set, dict,
    sum, max, min, str, int, float, bool, abs, range.
    """

    _HOISTABLE = frozenset({
        'len', 'sorted', 'reversed', 'list', 'tuple', 'set', 'dict',
        'sum', 'max', 'min', 'str', 'int', 'float', 'bool', 'abs', 'range',
    })

    def __init__(self) -> None:
        self._in_loop: bool = False
        self.count: int = 0

    def _visit_loop(self, node: ast.AST) -> None:
        prev = self._in_loop
        self._in_loop = True
        self.generic_visit(node)
        self._in_loop = prev

    visit_For = _visit_loop  # type: ignore[assignment]
    visit_While = _visit_loop  # type: ignore[assignment]

    def visit_Call(self, node: ast.Call) -> None:
        if self._in_loop and isinstance(node.func, ast.Name):
            if node.func.id in self._HOISTABLE:
                self.count += 1
        self.generic_visit(node)


def _complexity_penalty(cc: int) -> tuple[float, str | None]:
    """Return (penalty, issue_text | None) for a cyclomatic complexity value."""
    if cc <= 5:
        return 0.0, None
    if cc <= 10:
        return 0.05, f"Moderate complexity (CC={cc}): consider breaking this into smaller functions."
    if cc <= 20:
        return 0.10, f"High complexity (CC={cc}): code has many branches — aim for CC ≤ 10."
    return 0.20, f"Very high complexity (CC={cc}): this code is difficult to read and maintain."


def _nesting_penalty(max_depth: int) -> tuple[float, str | None]:
    if max_depth <= 2:
        return 0.0, None
    if max_depth == 3:
        return 0.03, f"Deep nesting (depth={max_depth}): consider extracting inner blocks."
    if max_depth == 4:
        return 0.08, f"Deep nesting (depth={max_depth}): refactor to reduce indentation levels."
    return 0.15, f"Excessive nesting (depth={max_depth}): deeply nested code is hard to follow."


def _loop_depth_penalty(max_loop: int) -> tuple[float, str | None]:
    if max_loop <= 1:
        return 0.0, None
    if max_loop == 2:
        return 0.08, (
            f"Nested loops (depth={max_loop}): this is O(n²) or worse. "
            "Check whether a single pass or a lookup structure would suffice."
        )
    return 0.18, (
        f"Deeply nested loops (depth={max_loop}): O(n³) or worse. "
        "This will be very slow on large inputs — rethink the algorithm."
    )


def _redundancy_penalty(count: int) -> tuple[float, str | None]:
    if count == 0:
        return 0.0, None
    if count <= 2:
        return 0.03, (
            f"{count} potentially redundant call(s) inside a loop "
            "(e.g. len/sorted). Move invariant calls outside the loop."
        )
    return 0.07, (
        f"{count} redundant call(s) inside loops: operations like len(), "
        "sorted(), or range() inside a loop body repeat work every iteration."
    )


def _analyse_python(code: str) -> QualityResult:
    """Full AST analysis for Python source code."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        # Syntax errors are already caught by the test runner; no penalty here.
        return QualityResult(quality_score=1.0, parse_error=True,
                             issues=[f"Syntax error (no quality penalty applied): {exc}"])

    # Complexity + nesting
    cv = _ComplexityVisitor()
    cv.visit(tree)

    # Redundant loop calls
    rv = _RedundancyVisitor()
    rv.visit(tree)

    issues: list[str] = []
    total_penalty = 0.0

    for penalty_fn, value in [
        (_complexity_penalty, cv.complexity),
        (_nesting_penalty, cv.max_depth),
        (_loop_depth_penalty, cv.max_loop_depth),
        (_redundancy_penalty, rv.count),
    ]:
        p, msg = penalty_fn(value)
        total_penalty += p
        if msg:
            issues.append(msg)

    return QualityResult(
        quality_score=round(1.0 - total_penalty, 4),
        issues=issues,
        cyclomatic_complexity=cv.complexity,
        max_nesting_depth=cv.max_depth,
        max_loop_depth=cv.max_loop_depth,
        redundant_loop_calls=rv.count,
    )


# ---------------------------------------------------------------------------
# JavaScript analysis  (heuristic — no external deps)
# ---------------------------------------------------------------------------

# Strip line and block comments before analysis to avoid false positives
_JS_LINE_COMMENT  = re.compile(r'//[^\n]*')
_JS_BLOCK_COMMENT = re.compile(r'/\*.*?\*/', re.DOTALL)
_JS_STRING_DOUBLE = re.compile(r'"(?:[^"\\]|\\.)*"')
_JS_STRING_SINGLE = re.compile(r"'(?:[^'\\]|\\.)*'")
_JS_STRING_BACKTICK = re.compile(r'`(?:[^`\\]|\\.)*`', re.DOTALL)

# Patterns that count as branch points for a rough cyclomatic-complexity proxy
_JS_BRANCH = re.compile(
    r'\b(?:if|else\s+if|for|while|do|switch|case|catch|\?\s*[^:]+:)\b',
    re.IGNORECASE,
)
# Loop-opening tokens
_JS_LOOP_OPEN  = re.compile(r'\b(?:for|while|do)\b')
_JS_BLOCK_OPEN  = re.compile(r'\{')
_JS_BLOCK_CLOSE = re.compile(r'\}')

# Hoistable calls commonly misused inside loops
_JS_LOOP_CALL = re.compile(
    r'\b(?:Array\.from|Object\.keys|Object\.values|Object\.entries|'
    r'JSON\.parse|JSON\.stringify|\.split|\.join|\.sort|\.reverse|\.filter|\.map)\b'
)


def _strip_js_literals(code: str) -> str:
    """Remove strings and comments so regex patterns don't false-positive."""
    code = _JS_BLOCK_COMMENT.sub(' ', code)
    code = _JS_LINE_COMMENT.sub(' ', code)
    code = _JS_STRING_BACKTICK.sub('""', code)
    code = _JS_STRING_DOUBLE.sub('""', code)
    code = _JS_STRING_SINGLE.sub("''", code)
    return code


def _js_max_loop_nesting(code: str) -> int:
    """Approximate maximum loop nesting depth by tracking { } balanced pairs."""
    depth = 0
    max_loop_depth = 0
    loop_depth_stack: list[int] = []  # stack of block depths where loops start

    i = 0
    while i < len(code):
        # Check for a loop keyword at this position
        m = _JS_LOOP_OPEN.match(code, i)
        if m:
            loop_depth_stack.append(depth)
            max_loop_depth = max(max_loop_depth, len(loop_depth_stack))
            i = m.end()
            continue
        c = code[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            # Pop any loops that opened at this depth or deeper
            while loop_depth_stack and loop_depth_stack[-1] >= depth:
                loop_depth_stack.pop()
        i += 1

    return max_loop_depth


def _js_redundant_loop_calls(code: str) -> int:
    """
    Count method calls commonly misused inside JS loops.
    Very conservative: only triggers if the call appears inside a `{ }` block
    that is preceded by a loop keyword on the same or prior line.
    """
    count = 0
    lines = code.split('\n')
    in_loop_block = False
    brace_balance = 0
    loop_start_balance = None

    for line in lines:
        if _JS_LOOP_OPEN.search(line) and '{' in line:
            in_loop_block = True
            loop_start_balance = brace_balance

        if in_loop_block:
            brace_balance += line.count('{') - line.count('}')
            count += len(_JS_LOOP_CALL.findall(line))
            if loop_start_balance is not None and brace_balance <= loop_start_balance:
                in_loop_block = False
                loop_start_balance = None

    return count


def _analyse_javascript(code: str) -> QualityResult:
    """Heuristic quality analysis for JavaScript source code."""
    stripped = _strip_js_literals(code)

    branch_count = len(_JS_BRANCH.findall(stripped))
    cc = 1 + branch_count  # rough cyclomatic complexity proxy

    max_loop = _js_max_loop_nesting(stripped)
    redundant = _js_redundant_loop_calls(stripped)

    # Nesting depth: approximate via maximum brace depth
    max_brace_depth = 0
    current_depth = 0
    for ch in stripped:
        if ch == '{':
            current_depth += 1
            max_brace_depth = max(max_brace_depth, current_depth)
        elif ch == '}':
            current_depth -= 1
    # Subtract 1 level for the typical function wrapper
    max_nesting = max(0, max_brace_depth - 1)

    issues: list[str] = []
    total_penalty = 0.0

    for penalty_fn, value in [
        (_complexity_penalty, cc),
        (_nesting_penalty, max_nesting),
        (_loop_depth_penalty, max_loop),
        (_redundancy_penalty, redundant),
    ]:
        p, msg = penalty_fn(value)
        total_penalty += p
        if msg:
            issues.append(msg)

    return QualityResult(
        quality_score=round(1.0 - total_penalty, 4),
        issues=issues,
        cyclomatic_complexity=cc,
        max_nesting_depth=max_nesting,
        max_loop_depth=max_loop,
        redundant_loop_calls=redundant,
    )
