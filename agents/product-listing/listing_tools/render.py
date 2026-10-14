"""Only JSON is authoritative; these views contain no independent facts."""
from html import escape
import json
import re
from urllib.parse import quote


def render(data):
    def value(v):
        if v is None: return '모름 / 미적용(상태 참조)'
        return json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else str(v)
    def cell(v):
        return escape(value(v)).replace('|','&#124;').replace('\n','<br>')
    pub=data['publication']; decision=data['content_decision']; content=data['content']
    md=[f"# 등록 패키지 — {cell(data['package_id'])}", '',
        f"버전: `{data['revision']}` · 게시 상태: **{pub['status']}** · 콘텐츠: **{decision['type']}**",'',
        cell(data['purpose']), '', cell(decision['reason']), '',
        '## 등록 필드', '', '| 항목 | 값 | 상태 / 근거 | 사실 / 확인 과제 | 비고 |',
        '| --- | --- | --- | --- | --- |']
    for f in data['fields']:
        md.append('| '+' | '.join(cell(v) for v in (f['label'],f['value'],f['status']+' / '+f['evidence_kind'],', '.join(f['fact_refs']+f['issue_refs']),f['note']))+' |')
    md += ['', '## 확인 과제', '']
    for i in data['issues']:
        md += [f"- **{cell(i['id'])} · {i['severity']} · {i['status']}**: {cell(i['question'])} — {cell(i['resolve_by'])}"]
    md += ['', '## 옮겨 입력하기', ''] + ['- '+cell(s) for s in content['transfer_instructions']]
    md += ['', '이미지 순서: '+', '.join('`'+p+'`' for p in content['image_order']), '',
           '## 근거·검수 원본', '', '출처·사실·권한·검사·미측정 시간·승인은 아래 JSON의 동일 버전에서 파생된다.', '']
    # Longest backtick run + 1 prevents source material breaking the code fence.
    body=json.dumps({k:data[k] for k in ('sources','facts','assets','content','review','publication')},ensure_ascii=False,indent=2)
    fence='`'*max(3,1+max((len(s) for s in re.findall(r'`+',body)),default=0))
    md += [fence+'json',body,fence,'']
    parts=[]
    if content.get('intro_title'): parts.append('<h1>'+escape(content['intro_title'])+'</h1>')
    for b in content['blocks']:
        title='<h2>'+escape(b.get('heading') or '')+'</h2>' if b.get('heading') else ''
        parts.append('<section>'+title+'<p>'+escape(b['text'])+'</p></section>')
    if content.get('supplier_heading'): parts.append('<h2>'+escape(content['supplier_heading'])+'</h2>')
    if content.get('supplier_note'): parts.append('<p>'+escape(content['supplier_note'])+'</p>')
    for n,p in enumerate(content['image_order'],1):
        parts.append(f'<img src="{quote(p,safe="/")}" alt="상품 상세 이미지 {n}" loading="eager">')
    html='''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>등록 콘텐츠 내부 검토</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f4f4;color:#222;font-family:system-ui,sans-serif}
aside,footer{max-width:860px;margin:auto;padding:16px;overflow-wrap:anywhere;font-size:14px}
main{max-width:860px;margin:auto;background:white}img{display:block;width:100%;height:auto}section,h1,h2,main>p{padding:16px;overflow-wrap:anywhere}p{line-height:1.65}
</style></head><body><aside>내부 검토용 · 판매자센터에 이 HTML 전체를 복사하지 마세요.<br>'''
    html+=escape(data['package_id']+' / '+data['revision']+' / '+pub['status'])+'</aside><main>'+''.join(parts)+'</main>'
    html+='<footer>원본 권한·채널 검수 및 게시 판단은 등록 패키지를 확인하세요.</footer></body></html>\n'
    return '\n'.join(md), html
