"""Reviewed selection data, with local files omitted; not publishable fixtures."""
import copy
import json
from html import unescape
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bundle import build, check
from validation import validate


class ProductTests(unittest.TestCase):
    def test_reviewed_names_categories_tags_and_evidence_survive_build(self):
        expected = {
            'desk-mat': ('PU 인조가죽 데스크 매트 60×30cm 핑크 스트랩 포함', '데스크패드', ['책상꾸미기','데스크테리어','책상깔개']),
            'basket': ('미니 수납 바구니 걸이형 책상 소품 정리', '패브릭바구니', ['소품수납','책상정리']),
        }
        for name,(title,category,tags) in expected.items():
            with self.subTest(product=name), tempfile.TemporaryDirectory() as tmp:
                source=ROOT/'tests/fixtures'/f'{name}.json'
                original=json.loads(source.read_text())
                out=Path(tmp)/'built'; result=build(source,out)
                for key in ('scope','scope_source_refs','sources','facts','observations','strategy','questions','fields','channel','content','issues'):
                    self.assertEqual(result[key],original[key],key)
                fields={f['id']:f for f in result['fields']}
                self.assertEqual(fields['title']['value'],title)
                self.assertTrue(fields['category']['value'].endswith(category))
                self.assertEqual(fields['tags']['value'],tags)
                rendered=unescape((out/'fields.md').read_text())
                for value in (title,category,*tags): self.assertIn(value,rendered)
                proposal=unescape((out/'proposal.md').read_text())
                for q in original['strategy']['queries']:
                    self.assertIn(q['query'],proposal)
                    self.assertIn(q['reason'].replace('\n','<br>'),proposal)
                self.assertEqual(check(out),[])
                self.assertEqual(result['state']['publication'],'blocked')

    def test_selected_keywords_and_category_require_existing_evidence(self):
        source=ROOT/'tests/fixtures/desk-mat.json'
        base=json.loads(source.read_text())
        for field in ('title','category','tags'):
            with self.subTest(field=field):
                d=copy.deepcopy(base)
                next(f for f in d['fields'] if f['id']==field)['fact_refs']=[]
                self.assertTrue(validate(d,source.parent))
        for decision in ('hold','exclude'):
            d=copy.deepcopy(base)
            qid=next(f for f in d['fields'] if f['id']=='tags')['query_refs'][0]
            next(q for q in d['strategy']['queries'] if q['id']==qid)['decision']=decision
            self.assertTrue(validate(d,source.parent))

if __name__=='__main__': unittest.main()
