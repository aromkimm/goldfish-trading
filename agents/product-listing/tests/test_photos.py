"""Photo layout regressions, using synthetic images and facts."""
import copy
import json
import sys
import unittest
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_listing import ListingCase
from bundle import approve, build, check
from validation import validate, readiness


class PhotoTests(ListingCase):
    # Reuse fixture helpers without rerunning the base test suite.
    def setUp(self):
        super().setUp()
        self.data['content']['layout'] = 'photo'
        self.data['assets'][0]['dimensions'] = [1, 1]
        self.block = self.data['content']['blocks'][0]
        self.block.update(kind='hero', kicker='TEST PRODUCT', composition='단일 구성',
                          option_text='시험 색상', heading='시험 상품명', text='확인된 설명',
                          asset_ids=[], photos=[dict(asset_id='image', region=[0, 0, 1, 1], caption='사진 설명')])

    def test_photo_preview_shows_available_unlicensed_image_but_blocks_customer(self):
        self.data['assets'][0]['rights'] = 'unknown'
        out, data = self.bundle()
        preview = (out/'preview.html').read_text()
        self.assertIn('viewBox="0 0 1 1"', preview)
        self.assertIn('assets/photo.png', preview)
        self.assertIn('사진 설명', preview)
        self.assertEqual(data['state']['publication'], 'blocked')
        self.assertNotIn('assets/photo.png', (out/'customer.html').read_text())
        self.assertEqual(check(out), [])

    def test_intro_order_and_same_body_for_customer(self):
        out, data = self.bundle()
        html = (out/'preview.html').read_text()
        for text in ('TEST PRODUCT', '<h1>시험 상품명', '단일 구성', '시험 색상', '확인된 설명', '<figure'):
            self.assertIn(text, html)
        positions = [html.index(s) for s in ('TEST PRODUCT', '<h1>시험 상품명', '단일 구성', '시험 색상', '확인된 설명', '<figure')]
        self.assertEqual(positions, sorted(positions))
        customer = (out/'customer.html').read_text()
        self.assertEqual(html.split('<main>')[1].split('</main>')[0], customer.split('<main>')[1].split('</main>')[0])
        self.assertIn('max-width:1px', html)

    def test_invalid_regions_dimensions_and_markup_are_rejected_or_escaped(self):
        for region in ([0,0,2,1], [-1,0,1,1], [0,0,0,1], [0,0,True,1], 'bad', [0,0,1]):
            with self.subTest(region=region):
                d=copy.deepcopy(self.data); d['content']['blocks'][0]['photos'][0]['region']=region
                self.assertTrue(validate(d,self.source))
        d=copy.deepcopy(self.data); d['assets'][0]['dimensions']=[2,2]
        self.assertTrue(validate(d,self.source))
        self.block['photos'][0]['caption']='<script>alert(1)</script>'
        out,_=self.bundle(); html=(out/'preview.html').read_text()
        self.assertNotIn('<script>',html); self.assertIn('&lt;script&gt;',html)

    def test_photo_refs_and_dual_image_lists_rejected(self):
        d=copy.deepcopy(self.data); d['content']['blocks'][0]['photos'][0]['asset_id']='absent'
        self.assertTrue(validate(d,self.source))
        d=copy.deepcopy(self.data); d['content']['blocks'][0]['asset_ids']=['image']
        self.assertTrue(validate(d,self.source))
        d=copy.deepcopy(self.data); del d['content']['layout']
        self.assertTrue(validate(d,self.source))

    def test_photo_only_usage_blocks_approval_and_crop_change_resets_review(self):
        self.data['content']['main_asset_id']=None
        self.data['assets'][0]['rights']='unknown'
        self.assertIn('asset:image',readiness(self.data)['blockers'])
        self.data['content']['main_asset_id']='image'; self.data['assets'][0]['rights']='use'
        out,data=self.bundle(); data=self.review(out,data)
        approve(out,'시험',data['revision'],decision='시험 승인')
        self.block['photos'][0]['caption']='변경된 사진 설명'
        new=build(self.save(),self.root/'new',previous=out)
        self.assertNotEqual(new['revision'],data['revision'])
        self.assertIsNone(new['approval'])
        self.assertTrue(all(c['status']=='not_run' for c in new['review']['checks']))

    def test_corrupt_image_header_and_ungrounded_diagram_fail(self):
        (self.source/'assets/photo.png').write_bytes(b'not an image')
        import hashlib
        self.data['assets'][0]['sha256']=hashlib.sha256(b'not an image').hexdigest()
        self.assertTrue(self.errors())

    def test_diagram_is_structured_and_escaped(self):
        self.block['diagram']={'width':'60cm','height':'30cm'}
        out,_=self.bundle(); html=(out/'preview.html').read_text()
        self.assertIn('60cm',html); self.assertIn('30cm',html)
        self.block['diagram']={'svg':'<script>bad</script>'}
        self.assertTrue(self.errors())

    def test_prepare_defaults_to_photo_layout_and_reads_dimensions(self):
        from bundle import prepare
        brief=self.source/'brief.json'
        brief.write_text(json.dumps(dict(product_id='photo',scope='단일',sources=[dict(id='image',location='시험 이미지',path='assets/photo.png',observed_at='2026-10-14')])))
        data=prepare(brief,self.root/'prepared')
        self.assertEqual(data['content'].get('layout'),'photo')
        self.assertEqual(data['assets'][0].get('dimensions'),[1,1])

    def test_crop_requires_edit_rights_and_missing_photo_is_placeholder(self):
        # A real, synthesized 2x1 PNG makes a non-full crop possible.
        import struct,zlib,hashlib
        def chunk(kind,data):
            return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
        raw=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00'+b'\xff\xff\xff'*2))+chunk(b'IEND',b'')
        path=self.source/'assets/photo.png';path.write_bytes(raw)
        self.data['assets'][0].update(dimensions=[2,1],sha256=hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.errors(),[])
        self.assertIn('image-edit:image',readiness(self.data)['blockers'])
        self.data['assets'][0]['rights']='edit'
        self.assertNotIn('image-edit:image',readiness(self.data)['blockers'])
        self.data['assets'][0].update(status='missing',path=None,sha256=None)
        out,data=self.bundle()
        self.assertIn('이미지 준비 필요',(out/'preview.html').read_text())
        self.assertEqual(data['state']['publication'],'blocked')

    def test_missing_asset_dimensions_and_unknown_photo_properties_fail(self):
        self.data['assets'][0].update(status='missing',path=None,sha256=None,dimensions=[True,1.5])
        self.assertTrue(self.errors())
        self.data['assets'][0]['dimensions']=[1,1]
        self.block['photos'][0]['max_display_width']=999
        self.assertTrue(self.errors())

if __name__=='__main__': unittest.main()
