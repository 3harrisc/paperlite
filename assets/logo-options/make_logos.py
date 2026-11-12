"""Logo concepts for PaperLite. Each is a 1024x1024 SVG (macOS icon grid:
artwork tile 824x824 inset 100px). Run to (re)write the SVG files."""

TILE = '<rect x="100" y="100" width="824" height="824" rx="186" fill="url(#bg)"/>'
GLOSS = '<rect x="100" y="100" width="824" height="824" rx="186" fill="url(#gloss)"/>'

def svg(defs, body, top="#F0563A", bottom="#C22A1E"):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient>
<linearGradient id="gloss" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0.16"/><stop offset="0.5" stop-color="#fff" stop-opacity="0"/></linearGradient>
<filter id="drop" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="14" stdDeviation="18" flood-color="#5a0d06" flood-opacity="0.35"/></filter>
{defs}
</defs>
{TILE}{GLOSS}
{body}
</svg>'''

# A — "Squeeze": a page with a folded corner and two chevrons pressing inward. Says PDF + compress.
A = svg("", '''
<g filter="url(#drop)">
  <path d="M322 214 H604 L722 332 V780 a30 30 0 0 1 -30 30 H322 a30 30 0 0 1 -30 -30 V244 a30 30 0 0 1 30 -30 Z" fill="#fff"/>
</g>
<path d="M604 214 V302 a30 30 0 0 0 30 30 H722 Z" fill="#F6C9C1"/>
<g fill="none" stroke="#D93A2B" stroke-width="44" stroke-linecap="round" stroke-linejoin="round">
  <path d="M420 372 L507 438 L594 372"/>
  <path d="M420 696 L507 630 L594 696"/>
</g>
<g stroke="#D93A2B" stroke-width="30" stroke-linecap="round" opacity="0.55">
  <path d="M398 534 H616"/>
</g>
''')

# B — "Big fold": a page whose top corner folds right down across it. Pure paper, abstract, distinctive.
B = svg('''<linearGradient id="flap" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FFFFFF"/><stop offset="1" stop-color="#F3D2CC"/></linearGradient>
<filter id="flapShadow" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="-10" dy="12" stdDeviation="14" flood-color="#7a1a10" flood-opacity="0.35"/></filter>''', '''
<g filter="url(#drop)">
  <path d="M318 214 H404 L726 536 V784 a30 30 0 0 1 -30 30 H318 a30 30 0 0 1 -30 -30 V244 a30 30 0 0 1 30 -30 Z" fill="#fff"/>
</g>
<path d="M404 214 L726 536 L428 536 a24 24 0 0 1 -24 -24 Z" fill="url(#flap)" filter="url(#flapShadow)"/>
<rect x="352" y="600" width="300" height="30" rx="15" fill="#F1E3E0"/>
<rect x="352" y="664" width="220" height="30" rx="15" fill="#F1E3E0"/>
''')

# C — "Sheet & stroke": a page with a signature stroke sweeping out of it. Says documents + sign.
C = svg("", '''
<g transform="rotate(-8 512 512)">
  <rect x="348" y="214" width="372" height="520" rx="34" fill="#fff" opacity="0.38"/>
</g>
<g filter="url(#drop)">
  <rect x="300" y="236" width="400" height="548" rx="34" fill="#fff"/>
</g>
<rect x="364" y="320" width="200" height="30" rx="15" fill="#E7E9EE"/>
<rect x="364" y="384" width="270" height="30" rx="15" fill="#E7E9EE"/>
<rect x="364" y="448" width="230" height="30" rx="15" fill="#E7E9EE"/>
<path d="M346 676 C 400 560, 454 560, 452 640 C 450 700, 404 714, 430 650 C 460 580, 520 600, 520 652 C 520 690, 560 690, 600 640 C 640 590, 700 600, 780 610"
      fill="none" stroke="#D93A2B" stroke-width="30" stroke-linecap="round" stroke-linejoin="round"/>
''')

# D — "Lite stack" (alternative colour direction: ink navy + coral). Two sheets, the front one
# slimmed by a pair of arrows — calmer, more 'utility' feel.
D = svg("", '''
<g filter="url(#drop)">
  <rect x="356" y="208" width="380" height="500" rx="40" fill="#FF7A59"/>
  <rect x="288" y="296" width="380" height="500" rx="40" fill="#fff"/>
</g>
<g fill="none" stroke="#1F2A44" stroke-width="40" stroke-linecap="round" stroke-linejoin="round">
  <path d="M478 400 V 476 M440 440 L478 478 L516 440"/>
  <path d="M478 692 V 616 M440 652 L478 614 L516 652"/>
  <path d="M388 546 H568"/>
</g>
''', top="#2B3A63", bottom="#16203A")

for name, s in {"A_squeeze": A, "B_big_fold": B, "C_sheet_stroke": C, "D_lite_stack": D}.items():
    open(f"{name}.svg", "w").write(s)
print("written")
