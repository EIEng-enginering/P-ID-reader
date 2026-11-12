import io
from pathlib import Path
import subprocess
import unittest
from PIL import Image,ImageDraw,ImageFont
from pid_reader.engineering.wp456.ocr import reread,unrotate_box,locate_tesseract,TesseractUnavailable
from .test_readings import word


class OcrTests(unittest.TestCase):
    def renderer(self,roi):return Image.new('L',(200,100),255),lambda b:b
    def engine(self,*args,**kw):return [dict(text='FR',conf='95',left='20',top='10',width='40',height='20')]
    def test_rotation_inverse(self):
        b=dict(x0=.1,y0=.2,x1=.3,y1=.4)
        self.assertEqual(unrotate_box(b,0),b)
        a=unrotate_box(b,90);self.assertAlmostEqual(a['x0'],.6);self.assertAlmostEqual(a['y1'],.3)
        a=unrotate_box(b,270);self.assertAlmostEqual(a['x0'],.2);self.assertAlmostEqual(a['y1'],.9)

    def test_rotated_passes_keep_provenance(self):
        out=reread([word('roi')],source_sha256='a'*64,renderer=self.renderer,command='fake',
                   engine=self.engine,rotations=(0,90),psms=(6,))
        self.assertEqual(out['calls'],2);self.assertEqual(len({w['run_id'] for w in out['words']}),2)
        self.assertEqual(out['status'],'SUCCESS')

    def test_cancel_before_render(self):
        def no_render(roi):raise AssertionError('Should not render')
        out=reread([word('roi')],source_sha256='a'*64,renderer=no_render,command='fake',engine=self.engine,cancelled=lambda:True)
        self.assertEqual(out['status'],'PARTIAL');self.assertEqual(out['calls'],0)

    def test_timeout_diagnostic(self):
        def failed(*a,**kw):raise subprocess.TimeoutExpired('fake',1)
        out=reread([word('roi')],source_sha256='a'*64,renderer=self.renderer,command='fake',engine=failed,rotations=(0,),psms=(6,))
        self.assertEqual(out['status'],'PARTIAL');self.assertFalse(out['words'])

    def test_count_budget_explicit(self):
        out=reread([word('r1'),word('r2')],source_sha256='a'*64,renderer=self.renderer,command='fake',
                   engine=self.engine,max_regions=1,rotations=(0,),psms=(6,))
        self.assertEqual(out['diagnostics'][-1]['status'],'REGION_COUNT_BUDGET')

    def test_no_region_is_successful_empty(self):
        out=reread([],source_sha256='a'*64,renderer=self.renderer,command='fake',engine=self.engine)
        self.assertEqual(out['words'],[]);self.assertEqual(out['calls'],0)

    def test_invalid_rotation_rejected(self):
        with self.assertRaises(ValueError):reread([],source_sha256='a'*64,renderer=self.renderer,command='fake',rotations=(45,))

    @unittest.skipUnless(locate_tesseract(),'Tesseract program unavailable')
    def test_real_tesseract_utf8_tsv(self):
        def render(roi):
            image=Image.new('L',(600,140),255)
            try:font=ImageFont.truetype('DejaVuSans.ttf',48)
            except OSError:
                import os
                font_path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'arial.ttf'
                if not font_path.is_file():self.skipTest('No test font available')
                font=ImageFont.truetype(str(font_path),48)
            ImageDraw.Draw(image).text((20,30),'V-2201',fill=0,font=font)
            return image,lambda b:b
        out=reread([word('roi')],source_sha256='a'*64,renderer=render,rotations=(0,),psms=(6,))
        self.assertTrue(any('V-2201' in w['text'] for w in out['words']),out)
