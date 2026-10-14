"""Same-version review documents and quiet, mobile-first product blocks."""
from html import escape
import json
from urllib.parse import quote
from .schema import asset_ready

FILES = ('proposal.md','fields.md','image-tasks.md','review.md','preview.html','customer.html')
LABELS = {'supported':'근거 확보','hypothesis':'가설 검증 필요','reconsider':'상품 재검토',
          'partial':'부분 초안','complete':'검수 대상 완성','blocked':'보류','reviewable':'사람 검토 가능','approved':'해당 버전 승인',
          'target':'채택','exclude':'제외','hold':'보류','ready':'준비','needs_confirmation':'확인 필요','not_applicable':'해당 없음',
          'confirmed':'확인된 것','estimated':'추정치','unknown':'모름','pass':'통과','fail':'실패','not_run':'미실행'}


def label(v):
    return LABELS.get(v,v)


def value(v):
    if v is None: return '모름'
    if isinstance(v,(list,dict)): return json.dumps(v,ensure_ascii=False)
    return str(v)


def cell(v):
    # Escape Markdown too: external titles cannot create active links/headings.
    s=escape(value(v)).replace('\n','<br>')
    for char in ('\\','`','*','_','[',']','|'):
        s=s.replace(char,'&#'+str(ord(char))+';')
    return s


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join('---' for _ in headers)+' |']+
                     ['| '+' | '.join(cell(v) for v in row)+' |' for row in rows])


def metric(m):
    return f"{label(m['status'])}: {value(m['value'])} · {m['definition']} · {m['period']} · {m['device']} · {m['note']}"


CSS = '''*{box-sizing:border-box}body{margin:0;background:#fff;color:#222;font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",sans-serif}main{max-width:860px;margin:0 auto}section{padding:42px 28px;text-align:center;overflow-wrap:anywhere}section.hero{padding-top:24px}h1,h2{font-weight:650;line-height:1.4;letter-spacing:-.025em;margin:28px auto 20px;max-width:32ch}h1{font-size:32px}h2{font-size:26px}p{font-size:17px;line-height:1.9;white-space:pre-line;margin:18px auto;max-width:44ch}figure{margin:0 0 30px}img{display:block;width:100%;height:auto}table{border-collapse:collapse;width:100%;margin:28px 0;font-size:16px;text-align:left;table-layout:fixed}th,td{padding:15px 12px;border-bottom:1px solid #dedede;vertical-align:top;overflow-wrap:anywhere}th{width:30%;font-weight:600;background:#fafafa}section.notice p{text-align:left}aside,footer{max-width:860px;margin:auto;padding:18px 24px;background:#f5f5f5;font-size:14px;line-height:1.7;overflow-wrap:anywhere}.placeholder{padding:64px 20px;background:#f4f4f4;border:1px dashed #aaa;color:#555}.empty{padding:64px 24px;text-align:center}@media(max-width:480px){section{padding:30px 18px}h1{font-size:27px}h2{font-size:23px}p{font-size:16px}th,td{padding:12px 8px;font-size:15px}}'''


def page(body, title):
    return ('<!doctype html>\n<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
            '<title>'+escape(title)+'</title><style>'+CSS+'</style></head><body>'+body+'</body></html>\n')


def render(data):
    state=data['state']; st=data['strategy']; rev=data['revision']
    header=f"버전: {rev} · 전략: {label(state['strategy'])} · 산출물: {label(state['output'])} · 게시: {label(state['publication'])}"
    proposal=['# 등록 제안서','',cell(st['summary']),'',cell(header),'',
              '## 고객과 선택 이유','',cell(st['reason_to_choose']),'','반대 근거: '+cell(st['counter_evidence']),
              '','불확실성: '+cell(st['uncertainties']),'','## 검색어 판단','',
              table(['검색어·의도','판단·적합성','이유','수요·근거'],[
                  (q['query']+' / '+q['intent'],label(q['decision'])+' / '+q['fit'],q['reason'],
                   metric(q['demand'])+' / '+', '.join(q['observation_refs']+q['fact_refs'])) for q in st['queries']]),
              '','## 경쟁 관측','']
    for o in data['observations']:
        proposal += [cell(o['query']+' · '+o['observed_at']+' · '+o['surface']),
                     '',cell('기기: '+o['device']+' / 로그인: '+o['login']+' / 광고: '+o['ad']+' / 표본: '+o['sampling']),'',
                     table(['상품·범위','관계·총비용','배송·정보·신뢰','한계·출처'],[
                         (c['name']+' / '+c['scope'],c['relation']+' / '+metric(c['total_price']),
                          c['delivery']+' / '+c['information']+' / '+c['trust'],c['note']+' / '+', '.join(c['source_refs'])) for c in o['competitors']]),'']
    proposal += ['## 구매 질문','',table(['질문','중요도·이유','근거·미결'],[
        (q['question'],q['priority']+' / '+q['reason'],('가설 / ' if q['hypothesis'] else '')+', '.join(q['source_refs']+q['fact_refs']+q['issue_refs'])) for q in data['questions']]),
        '','## 출처','',table(['ID·종류','위치·확인일','범위·접근·한계'],[
            (s['id']+' / '+s['kind'],s['location']+' / '+value(s['observed_at']),s['scope']+' / '+s['access']+' / '+s['note']) for s in data['sources']]),'']
    fields=['# 등록 입력표','',cell(header),'','값 열만 옮겨 입력합니다. 확인 필요·해당 없음은 상태와 근거를 먼저 확인합니다.','',
            table(['항목','복사할 값','상태·범위','내부 메모·근거'],[
                (f['label'],f['value'],label(f['status'])+' / '+f['scope'],f['note']+' / '+', '.join(f['fact_refs']+f['query_refs']+f['issue_refs'])) for f in data['fields']]),
            '','채널 요구사항: '+cell(data['channel']['status']+' / '+data['channel']['note']),'']
    images=['# 이미지 작업 목록','',cell(header),'',table(['자산·용도','작업·상태','권한·근거','범위·지시'],[
        (a['id']+(' / 대표' if a['id']==data['content']['main_asset_id'] else ' / 상세 또는 후보'),
         a['task']+' / '+a['status'],a['rights']+' / '+', '.join(a['rights_source_refs']),a['scope']+' / '+a['instruction']) for a in data['assets']]),'']
    review=['# 확인·검수 보고','',cell(header),'','## 게시 차단','']+['- '+cell(b) for b in state['blockers']]
    review+=['','## 확인 과제','',table(['과제','영향·상태','확인 방법·담당','해결'],[
        (i['id']+' / '+i['question'],i['impact']+' / '+i['severity']+' / '+i['status'],i['resolve_by']+' / '+i['owner'],i.get('resolution','미해결')) for i in data['issues']]),
        '','## 수행한 검사','',table(['검사','결과','범위·증거'],[
            (c['id'],label(c['status']),c['detail']+' / '+c['evidence']) for c in data['review']['checks']]),
        '','검토자: '+cell(data['review'].get('reviewer') or '미지정'),
        '','승인 기록: '+cell(data['approval']),
        '','## 작업시간','',cell(data['timing']),
        '','구조 검사와 의미·권한·채널 검수는 별개입니다. 로컬 승인 기록은 신원 인증이나 실제 게시를 뜻하지 않습니다.','']
    assets={a['id']:a for a in data['assets']}; sections=[]
    for b in data['content']['blocks']:
        parts=[]
        for aid in b['asset_ids']:
            a=assets[aid]
            if asset_ready(a,assets):
                parts.append('<figure><img src="'+quote(a['path'],safe='/')+'" alt="'+escape(a['alt'],quote=True)+'"></figure>')
            else: parts.append('<div class="placeholder">이미지 준비 필요 · '+escape(a['alt'])+'</div>')
        tag='h1' if b['kind']=='hero' else 'h2'
        if b['heading']: parts.append('<'+tag+'>'+escape(b['heading'])+'</'+tag+'>')
        if b['text']: parts.append('<p>'+escape(b['text'])+'</p>')
        if b['rows']:
            parts.append('<table><tbody>'+''.join('<tr><th scope="row">'+escape(k)+'</th><td>'+escape(v)+'</td></tr>' for k,v in b['rows'])+'</tbody></table>')
        sections.append('<section class="'+b['kind']+'">'+''.join(parts)+'</section>')
    body='<main>'+(''.join(sections) or '<p class="empty">상세 콘텐츠 작성 전</p>')+'</main>'
    title=next((value(f['value']) for f in data['fields'] if f['id']=='title' and f['status']=='ready'),'상세페이지 초안')
    preview=page('<aside>내부 검토용 · '+escape(header)+'<br>판매자센터에 HTML 전체를 붙여 넣지 마세요.</aside>'+body+
                 '<footer>문구·이미지와 등록 입력표를 함께 검수하세요. 고객용 화면은 customer.html에서 확인합니다.</footer>',title+' · 검토')
    customer=page(body,title) if state['output']=='complete' else page('<main><p class="empty">미완성 초안입니다. 내부 미리보기에서 확인하세요.</p></main>','고객용 화면 준비 전')
    return dict(zip(FILES,('\n'.join(proposal),'\n'.join(fields),'\n'.join(images),'\n'.join(review),preview,customer)))
