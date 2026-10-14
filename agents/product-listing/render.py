"""Same-version review documents and quiet, mobile-first product blocks."""
from html import escape
import json
from urllib.parse import quote
from validation import asset_ready

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


def page(body, title, extra_css=""):
    return ('<!doctype html>\n<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
            '<title>'+escape(title)+'</title><style>'+CSS+extra_css+'</style></head><body>'+body+'</body></html>\n')


PHOTO_CSS = '''h1,h2{white-space:pre-line}svg.photo,svg.diagram{display:block;width:100%;height:auto;overflow:hidden}section{word-break:keep-all;overflow-wrap:anywhere}section figure{width:100%;margin:28px auto}.kicker{font-size:12px;letter-spacing:3px;margin:0 0 18px;color:#777}figcaption{font-size:13px;line-height:1.7;color:#666;margin:12px 0 0}.photo-grid{display:flex;flex-wrap:wrap;justify-content:center;align-items:flex-start;gap:20px}.photo-grid figure{flex:0 1 calc(33.333% - 14px);min-width:0;margin:0}.diagram{max-width:720px;margin:28px auto}@media(max-width:480px){.photo-grid{gap:16px}.photo-grid figure{flex-basis:calc(50% - 8px)}}'''


def render_photo(photo, assets):
    asset = assets[photo['asset_id']]
    if asset['status'] != 'ready':
        return '<div class="placeholder">이미지 준비 필요 · '+escape(asset['alt'])+'</div>'
    x, y, width, height = photo['region']
    full_width, full_height = asset['dimensions']
    alt = escape(photo.get('alt',asset['alt']), quote=True)
    caption = '<figcaption>'+escape(photo['caption'])+'</figcaption>' if photo['caption'] else ''
    return (f'<figure style="max-width:{width}px"><svg class="photo" viewBox="{x} {y} {width} {height}" '
            f'role="img" aria-label="{alt}" xmlns="http://www.w3.org/2000/svg"><title>{alt}</title>'
            f'<image href="{quote(asset["path"],safe="/")}" width="{full_width}" height="{full_height}"/>'
            '</svg>'+caption+'</figure>')


def render_diagram(diagram):
    width, height = escape(diagram['width']), escape(diagram['height'])
    return ('<svg class="diagram" viewBox="0 0 720 430" role="img" aria-label="'+width+' × '+height+'">'
            '<rect x="100" y="70" width="500" height="250" rx="14" fill="#edc0ca" stroke="#b99099"/>'
            '<path d="M100 350H600 M100 342V358 M600 342V358 M635 70V320 M627 70H643 M627 320H643" stroke="#897871"/>'
            '<text x="350" y="390" text-anchor="middle" font-size="26">'+width+'</text>'
            '<text x="650" y="203" font-size="23">'+height+'</text></svg>')


def detail_body(data):
    assets = {a['id']:a for a in data['assets']}
    photo_layout = data['content'].get('layout') == 'photo'
    sections = []
    for block in data['content']['blocks']:
        pictures = []
        for aid in block['asset_ids']:
            asset = assets[aid]
            if (asset['status']=='ready' if photo_layout else asset_ready(asset,assets)):
                pictures.append('<figure><img src="'+quote(asset['path'],safe='/')+'" alt="'+escape(asset['alt'],quote=True)+'"></figure>')
            else:
                pictures.append('<div class="placeholder">이미지 준비 필요 · '+escape(asset['alt'])+'</div>')
        pictures.extend(render_photo(photo,assets) for photo in block.get('photos',[]))
        if block.get('photo_layout') == 'grid':
            pictures = ['<div class="photo-grid">'+''.join(pictures)+'</div>']
        words = []
        if block.get('kicker'): words.append('<div class="kicker">'+escape(block['kicker'])+'</div>')
        tag = 'h1' if block['kind']=='hero' else 'h2'
        if block['heading']: words.append('<'+tag+'>'+escape(block['heading'])+'</'+tag+'>')
        for key in ('composition','option_text','text'):
            if block.get(key): words.append('<p>'+escape(block[key])+'</p>')
        parts = words + pictures if photo_layout else pictures + words
        if block.get('diagram'): parts.append(render_diagram(block['diagram']))
        if block['rows']:
            parts.append('<table><tbody>'+''.join('<tr><th scope="row">'+escape(k)+'</th><td>'+escape(v)+'</td></tr>' for k,v in block['rows'])+'</tbody></table>')
        sections.append('<section class="'+block['kind']+'">'+''.join(parts)+'</section>')
    return '<main>'+(''.join(sections) or '<p class="empty">상세 콘텐츠 작성 전</p>')+'</main>'


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
    if data['content'].get('layout')=='photo':
        images += ['## 사진 배치','',table(['블록','원본·영역 [x,y,w,h]','사진 설명'],[
            (b['id'],p['asset_id']+' / '+str(p['region']),p['caption'])
            for b in data['content']['blocks'] for p in b.get('photos',[])]),'',
            '내부 사진 표시는 게시 권한 확인이 아닙니다. 원본 영역을 잘라 게시하려면 편집 권한이 필요합니다.','']
    review=['# 확인·검수 보고','',cell(header),'','## 게시 차단','']+['- '+cell(b) for b in state['blockers']]
    review+=['','## 확인 과제','',table(['과제','영향·상태','확인 방법·담당','해결'],[
        (i['id']+' / '+i['question'],i['impact']+' / '+i['severity']+' / '+i['status'],i['resolve_by']+' / '+i['owner'],i.get('resolution','미해결')) for i in data['issues']]),
        '','## 수행한 검사','',table(['검사','결과','범위·증거'],[
            (c['id'],label(c['status']),c['detail']+' / '+c['evidence']) for c in data['review']['checks']]),
        '','검토자: '+cell(data['review'].get('reviewer') or '미지정'),
        '','승인 기록: '+cell(data['approval']),
        '','## 작업시간','',cell(data['timing']),
        '','구조 검사와 의미·권한·채널 검수는 별개입니다. 로컬 승인 기록은 신원 인증이나 실제 게시를 뜻하지 않습니다.','']
    body=detail_body(data)
    extra_css=PHOTO_CSS if data['content'].get('layout')=='photo' else ''
    title=next((value(f['value']) for f in data['fields'] if f['id']=='title' and f['status']=='ready'),'상세페이지 초안')
    preview=page('<aside>내부 검토용 · '+escape(header)+'<br>판매자센터에 HTML 전체를 붙여 넣지 마세요.</aside>'+body+
                 '<footer>문구·이미지와 등록 입력표를 함께 검수하세요. 고객용 화면은 customer.html에서 확인합니다.</footer>',title+' · 검토',extra_css)
    customer=page(body,title,extra_css) if state['output']=='complete' else page('<main><p class="empty">미완성 초안입니다. 내부 미리보기에서 확인하세요.</p></main>','고객용 화면 준비 전')
    return dict(zip(FILES,('\n'.join(proposal),'\n'.join(fields),'\n'.join(images),'\n'.join(review),preview,customer)))
