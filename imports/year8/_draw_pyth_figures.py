#!/usr/bin/env python3
"""Redraw the G8 Applications of Pythagoras figures cleanly (no answer leakage)."""
import os, math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
os.makedirs(OUT, exist_ok=True)

BLUE = "#1f3f7a"
FILL = "#dCE3F0"

def newfig(w=4, h=3):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_aspect("equal"); ax.axis("off")
    return fig, ax

def save(fig, name):
    fig.savefig(os.path.join(OUT, name), dpi=130, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)

def line(ax, p, q, dashed=False, lw=1.6, color="black"):
    ax.plot([p[0], q[0]], [p[1], q[1]], ls="--" if dashed else "-", lw=lw, color=color)

def txt(ax, p, s, dx=0, dy=0, fs=13, color="black", ha="center", va="center"):
    ax.text(p[0] + dx, p[1] + dy, s, fontsize=fs, color=color, ha=ha, va=va)

def right_angle(ax, corner, a, b, size=0.5):
    """Small right-angle square at `corner`, arms toward a and b."""
    def u(p):
        vx, vy = p[0] - corner[0], p[1] - corner[1]
        m = math.hypot(vx, vy)
        return (vx / m, vy / m)
    ua, ub = u(a), u(b)
    p1 = (corner[0] + ua[0] * size, corner[1] + ua[1] * size)
    p3 = (corner[0] + ub[0] * size, corner[1] + ub[1] * size)
    p2 = (corner[0] + (ua[0] + ub[0]) * size, corner[1] + (ua[1] + ub[1]) * size)
    line(ax, p1, p2, lw=1.1); line(ax, p2, p3, lw=1.1)

# ── oblique projection for 3-D boxes/wedges (x right, y up, z depth) ──
KX, KY = 0.5 * math.cos(math.radians(28)), 0.5 * math.sin(math.radians(28))
def P(x, y, z):
    return (x + KX * z, y + KY * z)

# ════════════════════════════════════════════════════════════════════════
# 3-D figures
# ════════════════════════════════════════════════════════════════════════

def cuboid(name, w, h, d, labels, diag=("A", "G"), figsize=(3.6, 3.4)):
    """Box with corners: top A(bl-back) B(br-back) C(fr-r) D(fr-l);
    bottom E F G H. Front face HGCD (z=0), back face EFBA (z=d)."""
    V = {
        "H": P(0, 0, 0), "G": P(w, 0, 0), "C": P(w, h, 0), "D": P(0, h, 0),
        "E": P(0, 0, d), "F": P(w, 0, d), "B": P(w, h, d), "A": P(0, h, d),
    }
    fig, ax = newfig(*figsize)
    # back face (dashed/hidden edges via E)
    for a, b in [("E", "F"), ("E", "A"), ("E", "H")]:
        line(ax, V[a], V[b], dashed=True, lw=1.2)
    # visible edges
    for a, b in [("H", "G"), ("G", "C"), ("C", "D"), ("D", "H"),
                 ("A", "B"), ("B", "F"), ("F", "G"), ("B", "C"), ("A", "D")]:
        line(ax, V[a], V[b])
    line(ax, V[diag[0]], V[diag[1]], dashed=True, color=BLUE, lw=1.6)
    for k, p in V.items():
        dx = -0.14 * w if k in ("D", "H", "A", "E") else 0.12 * w
        txt(ax, p, k, dx=dx, dy=0.05 * h, fs=11, color=BLUE)
    for (a, b), s in labels.items():
        mid = ((V[a][0] + V[b][0]) / 2, (V[a][1] + V[b][1]) / 2)
        txt(ax, mid, s, dx=0.10 * w, dy=0, fs=12)
    save(fig, name)

# Q1a cube 10
cuboid("pyth_cube_ag.png", 10, 10, 10,
       {("H", "G"): "10", ("G", "C"): "10", ("F", "G"): "10"})
# Q1b box 5x5x10  (width HG=5, depth=5, height=10)
cuboid("pyth_cuboid_ag.png", 5, 10, 5,
       {("H", "G"): "5", ("G", "C"): "10", ("F", "G"): "5"})
# Q6 suitcase 90x65x30
cuboid("pyth_suitcase.png", 9.0, 6.5, 3.0,
       {("H", "G"): "90 cm", ("G", "C"): "65 cm", ("F", "G"): "30 cm"},
       figsize=(4.0, 3.2))

def wedge(name):
    """Right-angled wedge. Base DCFE: D(fr-l) C(fr-r) F(bk-r) E(bk-l);
    DC=10, CF=7; A above E and B above F at height 4."""
    w, d, ht = 10.0, 7.0, 4.0
    D, C = P(0, 0, 0), P(w, 0, 0)
    E, F = P(0, 0, d), P(w, 0, d)
    A, B = P(0, ht, d), P(w, ht, d)
    fig, ax = newfig(4.0, 3.0)
    # hidden edges from E
    for a, b in [(E, F), (E, D), (E, A)]:
        line(ax, a, b, dashed=True, lw=1.2)
    for a, b in [(D, C), (C, F), (F, B), (B, A), (A, D), (C, B)]:
        line(ax, a, b)
    line(ax, C, E, dashed=True, color=BLUE)   # CE base diagonal
    line(ax, A, C, dashed=True, color="#b00000")  # AC space diagonal
    right_angle(ax, F, C, B, size=0.45)
    for p, k, dx in [(A, "A", -0.5), (B, "B", 0.3), (C, "C", 0.1),
                     (D, "D", -0.5), (E, "E", -0.45), (F, "F", 0.3)]:
        txt(ax, p, k, dx=dx, dy=0.25, fs=11, color=BLUE)
    txt(ax, ((D[0] + C[0]) / 2, D[1]), "10", dy=-0.45)
    txt(ax, ((C[0] + F[0]) / 2, (C[1] + F[1]) / 2), "7", dx=0.35, dy=-0.2)
    txt(ax, ((F[0] + B[0]) / 2, (F[1] + B[1]) / 2), "4", dx=0.35)
    save(fig, name)

wedge("pyth_wedge.png")

def pyramid(name, base_lbl, edge_lbl, show_diag=True, show_height=True,
            apex="V", height_lbl=None):
    """Square-base pyramid, apex over centre. Base ABCD, oblique."""
    s = 3.0
    A, B = P(0, 0, s), P(s, 0, s)      # back corners
    C, D = P(s, 0, 0), P(0, 0, 0)      # front corners
    cx = (A[0] + B[0] + C[0] + D[0]) / 4
    cy = (A[1] + B[1] + C[1] + D[1]) / 4
    Vtx = (cx, cy + 3.2)
    M = (cx, cy)
    fig, ax = newfig(3.4, 3.4)
    for a, b in [(A, B), (A, D)]:
        line(ax, a, b, dashed=True, lw=1.2)
    for a, b in [(D, C), (C, B)]:
        line(ax, a, b)
    for c in (A, B, C, D):
        line(ax, Vtx, c, dashed=(c is A), lw=1.5)
    if show_diag:
        line(ax, B, D, dashed=True, color=BLUE)
    if show_height:
        line(ax, Vtx, M, dashed=True, color="#b00000")
        right_angle(ax, M, C, Vtx, size=0.3)
    txt(ax, Vtx, apex, dy=0.28, fs=12, color=BLUE)
    for p, k, dx, dy in [(A, "A", -0.1, 0.28), (B, "B", 0.28, 0.05),
                         (C, "C", 0.18, -0.28), (D, "D", -0.28, -0.28)]:
        txt(ax, p, k, dx=dx, dy=dy, fs=11, color=BLUE)
    txt(ax, ((D[0] + C[0]) / 2, D[1]), base_lbl, dy=-0.3)
    txt(ax, ((C[0] + Vtx[0]) / 2, (C[1] + Vtx[1]) / 2), edge_lbl, dx=0.35)
    if height_lbl:
        txt(ax, ((Vtx[0] + M[0]) / 2, (Vtx[1] + M[1]) / 2), height_lbl, dx=0.28)
    save(fig, name)

# Q3 pyramid base 8, edge 8 (BD + height)
pyramid("pyth_pyramid_bd.png", "8", "8")
# Q4 pyramid height 20, slant edge 30, base unknown
pyramid("pyth_pyramid_base.png", "?", "30", show_diag=False, apex="E",
        height_lbl="20")

def cone(name, slant_lbl, height_lbl, r_lbl="r"):
    rx, h = 1.6, 3.0
    fig, ax = newfig(3.0, 3.4)
    base = Ellipse((0, 0), 2 * rx, 0.8, fill=False, lw=1.6)
    ax.add_patch(base)
    apex = (0, h)
    line(ax, (-rx, 0), apex); line(ax, (rx, 0), apex)
    line(ax, apex, (0, 0), dashed=True, color="#b00000")    # height
    line(ax, (0, 0), (rx, 0), dashed=True, color=BLUE)      # radius
    right_angle(ax, (0, 0), (rx, 0), apex, size=0.28)
    txt(ax, (rx / 2, 0), r_lbl, dy=-0.3, color=BLUE)
    txt(ax, (0, h / 2), height_lbl, dx=-0.3, color="#b00000")
    txt(ax, (rx / 2 + 0.1, h / 2 + 0.2), slant_lbl, dx=0.35)
    ax.set_xlim(-rx - 0.6, rx + 0.9); ax.set_ylim(-0.8, h + 0.5)
    save(fig, name)

cone("pyth_cone_r6.png", "10 cm", "8 cm")     # Q5  r=6
cone("pyth_cone_r126.png", "22 cm", "18 cm")  # p19 Q7  r=12.6

# ════════════════════════════════════════════════════════════════════════
# 2-D figures
# ════════════════════════════════════════════════════════════════════════

def tri(name, pts, labels, ra_at=None, dashed_height=None, figsize=(3.4, 3.0),
        vlabels=None):
    fig, ax = newfig(*figsize)
    ks = list(pts)
    for i in range(len(ks)):
        line(ax, pts[ks[i]], pts[ks[(i + 1) % len(ks)]])
    for (a, b), s in labels.items():
        mid = ((pts[a][0] + pts[b][0]) / 2, (pts[a][1] + pts[b][1]) / 2)
        ox = labels.get(("_off_" + a + b), (0, 0))
        save_off = ox if isinstance(ox, tuple) else (0, 0)
    # simpler: labels is dict edge->(text,dx,dy)
    save(fig, name)

# Use an explicit simple drawer instead (clearer per-figure control)
def seg(ax, p, q, dashed=False, color="black"):
    line(ax, p, q, dashed=dashed, color=color)

def fig_triangle(name, V, edges, points_lbl, ra=None, extra=None, figsize=(3.6, 3.0)):
    """V: dict name->(x,y); edges: list of (a,b); points_lbl: dict name->(dx,dy)
    edges entries may be ((a,b), 'text', dx, dy)."""
    fig, ax = newfig(*figsize)
    # outline
    for e in edges:
        a, b = e[0]
        seg(ax, V[a], V[b])
        if len(e) > 1 and e[1]:
            mid = ((V[a][0] + V[b][0]) / 2, (V[a][1] + V[b][1]) / 2)
            txt(ax, mid, e[1], dx=e[2], dy=e[3], fs=12)
    if ra:
        right_angle(ax, V[ra[0]], V[ra[1]], V[ra[2]], size=ra[3] if len(ra) > 3 else 0.35)
    for k, (dx, dy) in points_lbl.items():
        txt(ax, V[k], k, dx=dx, dy=dy, fs=11, color=BLUE)
    if extra:
        extra(ax)
    save(fig, name)

# Rev Q8: triangle d (top), 8.6 (right vertical), 18.6 (hypotenuse). RA top-right.
fig_triangle("pyth_tri_d.png",
    {"P": (0, 3), "Q": (4, 3), "R": (4, 0)},
    [(("P", "Q"), "d", 0, 0.3), (("Q", "R"), "8.6", 0.35, 0), (("R", "P"), "18.6", -0.3, 0.25)],
    {}, ra=("Q", "P", "R", 0.35))

# Rev Q8 trapezoid: top 24, bottom 12, left vertical a, right slant 16. RA left.
def fig_trapzd():
    fig, ax = newfig(3.8, 2.8)
    A, B = (0, 3), (4.0, 3)         # top  (24)
    Dn, Cn = (0, 0), (2.0, 0)       # bottom (12), left aligned
    for p, q in [(A, B), (B, Cn), (Cn, Dn), (Dn, A)]:
        seg(ax, p, q)
    right_angle(ax, A, B, Dn, 0.3); right_angle(ax, Dn, A, Cn, 0.3)
    txt(ax, (2.0, 3), "24", dy=0.3); txt(ax, (1.0, 0), "12", dy=-0.32)
    txt(ax, (0, 1.5), "a", dx=-0.28, color=BLUE); txt(ax, (3.0, 1.5), "16", dx=0.32)
    save(fig, "pyth_trapezoid_a.png")
fig_trapzd()

# TT Q4 triangle ABC: AB=34 hyp, AC=30 base, BC vertical, RA at C.
fig_triangle("pyth_tri_bc.png",
    {"A": (0, 0), "C": (5, 0), "B": (5, 2.6)},
    [(("A", "B"), "34 cm", -0.1, 0.35), (("A", "C"), "30 cm", 0, -0.32), (("C", "B"), "", 0, 0)],
    {"A": (-0.25, -0.1), "B": (0.25, 0.1), "C": (0.25, -0.25)}, ra=("C", "A", "B", 0.35))

# TT Q5 triangle PQR: RA at apex R, legs 11 & 15, base PQ.
fig_triangle("pyth_tri_pq.png",
    {"P": (0, 0), "Q": (5.2, 0), "R": (1.7, 2.7)},
    [(("P", "R"), "11 m", -0.35, 0.1), (("R", "Q"), "15 m", 0.35, 0.15), (("P", "Q"), "", 0, 0)],
    {"P": (-0.25, -0.2), "Q": (0.25, -0.2), "R": (0, 0.3)}, ra=("R", "P", "Q", 0.3))

# TT Q2 name hypotenuse: triangle RST, RA at R.
fig_triangle("pyth_name_hyp.png",
    {"R": (1.4, 2.7), "S": (5.0, 1.0), "T": (0, 0)},
    [(("R", "S"), "", 0, 0), (("S", "T"), "", 0, 0), (("T", "R"), "", 0, 0)],
    {"R": (0, 0.28), "S": (0.28, 0), "T": (-0.25, -0.2)}, ra=("R", "S", "T", 0.32))

# TT Q8 equilateral side 4, height h, half-base 2.
def fig_equi():
    fig, ax = newfig(3.4, 3.0)
    A, B, Cc = (-2, 0), (2, 0), (0, 3.464)
    M = (0, 0)
    for p, q in [(A, B), (B, Cc), (Cc, A)]:
        seg(ax, p, q)
    seg(ax, Cc, M, dashed=True, color="#b00000")
    right_angle(ax, M, B, Cc, 0.28)
    txt(ax, (-1, 1.8), "4 cm", dx=-0.35, dy=0.2)
    txt(ax, (1, 1.8), "4 cm", dx=0.35, dy=0.2)
    txt(ax, (-1, 0), "2 cm", dy=-0.3); txt(ax, (1, 0), "2 cm", dy=-0.3)
    txt(ax, (0, 1.7), "h", dx=-0.28, color="#b00000")
    save(fig, "pyth_equilateral.png")
fig_equi()

# TT Q9 trapezium: top 6, bottom 9, right vertical 5, left slant; inner RA triangle (3,5).
def fig_trapzm():
    fig, ax = newfig(3.8, 3.0)
    Dn, Cn = (0, 0), (5, 0)            # bottom 9 (scaled)
    Bt = (5, 3)                        # top-right
    At = (1.5, 3)                      # top-left (top = 6)
    foot = (1.5, 0)
    for p, q in [(At, Bt), (Bt, Cn), (Cn, Dn), (Dn, At)]:
        seg(ax, p, q)
    seg(ax, At, foot, dashed=True, color="#b00000")
    right_angle(ax, foot, Dn, At, 0.25); right_angle(ax, Cn, Dn, Bt, 0.25)
    txt(ax, (3.25, 3), "6 cm", dy=0.3); txt(ax, (2.5, 0), "9 cm", dy=-0.32)
    txt(ax, (5, 1.5), "5 cm", dx=0.35); txt(ax, (0.6, 1.6), "d", dx=-0.2, color=BLUE)
    txt(ax, (1.5, 1.5), "5 cm", dx=0.3, dy=0, color="#b00000")
    txt(ax, (0.75, 0), "3 cm", dy=-0.3, fs=10, color="#b00000")
    save(fig, "pyth_trapezium.png")
fig_trapzm()

# Rev Q11 isosceles: equal sides 25, base 22, height dashed.
def fig_iso():
    fig, ax = newfig(3.6, 3.0)
    A, B, Cc = (-2.2, 0), (2.2, 0), (0, 3.0)
    for p, q in [(A, B), (B, Cc), (Cc, A)]:
        seg(ax, p, q)
    seg(ax, Cc, (0, 0), dashed=True, color="#b00000")
    right_angle(ax, (0, 0), B, Cc, 0.25)
    txt(ax, (-1.1, 1.5), "25 cm", dx=-0.4, dy=0.2)
    txt(ax, (1.1, 1.5), "25 cm", dx=0.4, dy=0.2)
    txt(ax, (0, 0), "22 cm", dy=-0.3)
    txt(ax, (0, 1.5), "h", dx=-0.28, color="#b00000")
    save(fig, "pyth_isosceles.png")
fig_iso()

# TT Q13 ladder: RA triangle, ladder 25 (hyp), base 7, height (window).
def fig_ladder():
    fig, ax = newfig(3.0, 3.4)
    A, B, Cc = (0, 0), (2.0, 0), (0, 4.0)   # base 7, height window, hyp ladder
    for p, q in [(A, B), (B, Cc), (Cc, A)]:
        seg(ax, p, q)
    right_angle(ax, A, B, Cc, 0.28)
    txt(ax, (1.1, 2.1), "25 m", dx=0.3, dy=0.2)
    txt(ax, (1.0, 0), "7 m", dy=-0.3)
    txt(ax, (0, 2.0), "?", dx=-0.3, color=BLUE)
    save(fig, "pyth_ladder.png")
fig_ladder()

# TT Q14 find y: parallelogram, top 1, bottom 2, left 3, diagonal x=√5, right y.
def fig_findy():
    fig, ax = newfig(3.6, 3.4)
    # left triangle: base 2 (bottom), left side 3, vertical diagonal x
    Bl, Br = (0, 0), (2.0, 0)          # bottom = 2
    Tl = (0.6, 3.0)                    # top-left of vertical diagonal
    Tr = (2.6, 3.0)                    # top-right
    # vertices: parallelogram Bl, Br, Tr, Tl ; diagonal Br->Tl  (x)
    for p, q in [(Bl, Br), (Br, Tr), (Tr, Tl), (Tl, Bl)]:
        seg(ax, p, q)
    seg(ax, Br, Tl, dashed=True, color=BLUE)   # x
    txt(ax, (1.6, 3.0), "1 cm", dy=0.3)        # top
    txt(ax, (1.0, 0), "2 cm", dy=-0.3)         # bottom
    txt(ax, (0.1, 1.5), "3 cm", dx=-0.4)       # left
    txt(ax, (2.7, 1.5), "y cm", dx=0.45, color="#b00000")  # right
    txt(ax, (1.3, 1.5), "x cm", dx=0.2, color=BLUE)
    save(fig, "pyth_findy.png")
fig_findy()

# TT Q16 rectangle find x: 14 wide, 6 tall, top-left 5, diagonal to bottom-right.
def fig_rect_x():
    fig, ax = newfig(4.0, 2.6)
    A, B = (0, 2.4), (5.6, 2.4)        # top
    Cc, Dn = (5.6, 0), (0, 0)          # bottom-right, bottom-left
    pt = (2.0, 2.4)                    # 5 from left on top
    for p, q in [(A, B), (B, Cc), (Cc, Dn), (Dn, A)]:
        seg(ax, p, q)
    seg(ax, pt, Cc, color=BLUE)        # diagonal x
    for c in (A, B, Cc, Dn):
        right_angle(ax, c, *( [B, Dn] if c == A else [A, Cc] if c == B else [B, Dn] if c == Cc else [A, Cc]), size=0.18)
    txt(ax, (1.0, 2.4), "5", dy=0.28); txt(ax, (3.8, 2.4), "9", dy=0.28)
    txt(ax, (0, 1.2), "6", dx=-0.28); txt(ax, (2.8, 0), "14", dy=-0.3)
    txt(ax, (3.9, 1.1), "x", dx=0.2, dy=0.1, color=BLUE)
    save(fig, "pyth_rect_x.png")
fig_rect_x()

# TT Q15 square diagonal 72, find side.
def fig_square():
    fig, ax = newfig(3.0, 3.0)
    A, B, Cc, Dn = (0, 0), (3, 0), (3, 3), (0, 3)
    for p, q in [(A, B), (B, Cc), (Cc, Dn), (Dn, A)]:
        seg(ax, p, q)
    seg(ax, A, Cc, dashed=True, color=BLUE)
    right_angle(ax, A, B, Dn, 0.25)
    txt(ax, (1.6, 1.4), "72 cm", dx=0.1, dy=0.25, color=BLUE)
    txt(ax, (1.5, 0), "?", dy=-0.3)
    save(fig, "pyth_square.png")
fig_square()

# p19 Q8 Constance: RA triangle, hyp 7, leg 5, find x.
fig_triangle("pyth_constance.png",
    {"A": (0, 0), "B": (3.2, 0), "C": (3.2, 2.4)},
    [(("A", "C"), "7", -0.25, 0.25), (("B", "C"), "5", 0.3, 0), (("A", "B"), "x", 0, -0.3)],
    {}, ra=("B", "A", "C", 0.3))

# TT Q17 Sarah/Charlie: L-path 1 km across + 2 km up, direct hypotenuse.
def fig_path():
    fig, ax = newfig(3.2, 3.4)
    S, corner, Ch = (0, 0), (2.0, 0), (2.0, 4.0)
    seg(ax, S, corner); seg(ax, corner, Ch)
    seg(ax, S, Ch, dashed=True, color=BLUE)
    right_angle(ax, corner, S, Ch, 0.28)
    txt(ax, (1.0, 0), "1 km", dy=-0.3)
    txt(ax, (2.0, 2.0), "2 km", dx=0.35)
    txt(ax, (0.7, 2.2), "d", dx=-0.2, dy=0, color=BLUE)
    txt(ax, S, "Sarah", dx=-0.45, dy=-0.2, fs=10, color=BLUE)
    txt(ax, Ch, "Charlie", dx=0.1, dy=0.28, fs=10, color=BLUE)
    save(fig, "pyth_path.png")
fig_path()

print("drew figures")
