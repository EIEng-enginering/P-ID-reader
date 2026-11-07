"""Generate non-confidential vector P&ID-like regression examples for Rev O.

These are synthetic drawings, not representative real-world engineering P&IDs.
"""
from __future__ import annotations
from pathlib import Path
from reportlab.pdfgen import canvas


def generate(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    for revision in ('A', 'B'):
        p=output_dir/f'synthetic_rev_o_{revision.lower()}.pdf'
        c=canvas.Canvas(str(p), pagesize=(640,400), pageCompression=0, invariant=1)
        c.setTitle(f'Synthetic Rev O Comparison {revision} - Not Plant Evidence')
        c.setFont('Helvetica-Bold',14)
        c.drawString(32,364,f'SYNTHETIC P&ID - REV {revision} - TEST ONLY')
        c.setFont('Helvetica',10)
        c.drawString(32,345,'CONTROLLED DRAWING REVISION TEST: NOT A VERIFIED FACILITY')
        c.setFont('Helvetica-Bold',12)
        # New revision moves the depicted pump and adds a valve-tag text.
        xpos=82 if revision=='A' else 122
        c.circle(xpos+23,205,22)
        c.line(22,205,xpos+1,205)
        c.line(xpos+45,205,480,205)
        c.drawCentredString(xpos+23,160,'P-101')
        c.circle(327,270,16)
        c.setFont('Helvetica',9)
        c.drawCentredString(327,266,'PT-201')
        c.setDash(4,4)
        c.line(327,254,327,205)
        c.setDash()
        if revision=='B':
            c.drawString(486,207,'V-301')
        c.setFont('Helvetica',10)
        c.drawString(32,60,'DRAWING EVIDENCE ONLY - ALL CONNECTIONS ARE UNVERIFIED')
        c.save()
    return [output_dir/f'synthetic_rev_o_{r.lower()}.pdf' for r in ('A','B')]


if __name__=='__main__':
    import sys
    paths=generate(Path(sys.argv[1]) if len(sys.argv)>1 else Path('fixtures'))
    print('\n'.join(str(p) for p in paths))
