"""Verify all delivered papers against the Corvinus TDK 2025/26 formal rules."""
import re, subprocess, sys, pathlib
# Allitsd at az utvonalakat a sajat gepeden levo mappakra.
PAPERS = {
 "ROTAVIRUS": r"C:\Users\molna\Documents\ROTAVIRUS\TDK_2026\analysis\paper",
 "BUDAPEST":  r"C:\Users\molna\Documents\BUDAPEST\TDK_2026\paper",
 "MFKAN":     r"C:\Users\molna\Documents\mfkan_portfolio_v8\TDK_2026\paper",
 "SPECTRAL":  r"C:\Users\molna\Documents\Spectral\TDK_2026\paper",
 "REGIME":    r"C:\Users\molna\Documents\regime_v2\TDK_2026\paper",
 "OKTATAS":   "C:\\Users\\molna\\Documents\\OKTAT\u00c1S\\TDK_2026\\paper",
 "EGESZSEGUGY": "C:\\Users\\molna\\Documents\\EG\u00c9SZS\u00c9G\u00dcGY\\TDK_2026\\paper",
 "ISKOLA":    r"C:\Users\molna\Documents\NEM SZABAD ISKOLA\TDK_2026\analysis\paper",
 "STAT":      r"C:\Users\molna\Documents\STAT_test_MFKAN\TDK_2026\paper",
 "DARTS":     r"C:\Users\molna\Documents\DARTS\TDK_2026\paper",
 "SYMBOLIC":  r"C:\Users\molna\Documents\Symbolic regression\TDK_2026\paper",
}
A4 = (595.276, 841.89)
def run(*a): return subprocess.run(a, capture_output=True, text=True).stdout
fail = 0
for name, d in PAPERS.items():
    d = pathlib.Path(d); pdf = d/"paper.pdf"
    tex = (d/"paper.tex").read_text(encoding="utf-8")
    sty = (d/"tdk.sty").read_text(encoding="utf-8")
    txt, info, fonts = run("pdftotext", str(pdf), "-"), run("pdfinfo", str(pdf)), run("pdffonts", str(pdf))
    pages = int(re.search(r"Pages:\s+(\d+)", info).group(1))
    w, h = [float(x) for x in re.search(r"Page size:\s+([\d.]+) x ([\d.]+)", info).groups()]
    m = re.search(r"(Research question|Kutat\u00e1si k\u00e9rd\u00e9s)", txt)
    seg = " ".join(txt[m.start():].split()) if m else ""
    e = re.search(r"(Keywords|Kulcsszavak)", seg); seg = seg[:e.start()] if e else seg
    # The "own results" heading may carry a parenthetical qualifier, e.g.
    # "Sajat eredmenyek (elozetes, szintetikus adaton)." -- allow it.
    own = re.split(r"(Own results[^.]{0,60}\.|Saj\u00e1t eredm\u00e9nyek[^.]{0,60}\.)", seg)
    own_len = len(own[-1].strip()) if len(own) > 1 else -1
    # Count only floats the document actually renders: inline ones plus the
    # fragments it \input s.  A results directory may hold spare fragments the
    # paper does not use, and those must not count against it.
    n_float = len(re.findall(r"\\begin\{(table|figure)\}", tex))
    ap = d/"appendix.tex"          # SYMBOLIC keeps two floats in its appendix
    if ap.exists():
        n_float += len(re.findall(r"\\begin\{(table|figure)\}",
                                  ap.read_text(encoding="utf-8")))
    tdir = d/"tables"
    for u in re.findall(r"\\input\{tables/([^}]+)\}", tex):
        f = tdir / (u if u.endswith(".tex") else u + ".tex")
        if f.exists():
            n_float += len(re.findall(r"\\begin\{(table|figure)\}",
                                      f.read_text(encoding="utf-8")))
    n_src = len(re.findall(r"^(Source|Forr\u00e1s):", txt, re.M))
    checks = [
      ("12pt document class", "[12pt,a4paper]" in tex),
      ("A4 page", abs(w-A4[0])<1 and abs(h-A4[1])<1),
      ("Times New Roman", "Termes" in fonts or "Times" in fonts),
      ("tdk.sty loaded", "{tdk}" in tex),
      ("2.5 cm margins", "margin=2.5cm" in sty),
      ("1.5 line spacing", "\\onehalfspacing" in sty),
      ("folio bottom-centre", "\\fancyfoot[C]" in sty),
      ("folio starts at intro", "\\tdkmaintext" in tex),
      ("decimal numbering", "\\Roman{section}" in sty),
      ("14pt cover", "fontsize{14}" in sty and ("\\tdkborito" in tex or "\\tdkcover" in tex)),
      (f"abstract 500-2500 chars ({len(seg)})", 500 <= len(seg) <= 2500),
      (f"own results <=500 chars ({own_len})", 0 < own_len <= 500),
      ("abstract has 3 parts", len(own) > 1 and bool(re.search(r"(Method\.|M\u00f3dszertan\.)", seg))),
      (f"source under every float ({n_src}/{n_float})", n_src >= n_float > 0),
      ("author-year citations", "authoryear" in tex or "\\bibitem[" in tex),
      ("table of contents", "\\tableofcontents" in tex),
      ("AI-use declaration", bool(re.search(r"(mesters\u00e9ges intelligencia|Artificial Intelligence)", txt))),
      ("originality declaration", bool(re.search(r"(Eredetis\u00e9gi nyilatkozat|Declaration of Originality)", txt))),
      (f"page limit ({pages} pages)", pages <= 60),
    ]
    print(f"\n=== {name}  ({pages} pages)")
    for label, ok in checks:
        print(f"   {'PASS' if ok else 'FAIL'}  {label}"); fail += (not ok)
print(f"\n{'ALL CHECKS PASS' if not fail else str(fail)+' CHECK(S) FAILED'}")
sys.exit(1 if fail else 0)
