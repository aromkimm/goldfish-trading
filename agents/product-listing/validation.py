"""Validate evidence links; never infer product truth or search performance."""
from datetime import datetime
import hashlib
import sys
from pathlib import Path
import re
from images import image_size

CHECKS = ('identity', 'facts', 'strategy', 'rights', 'desktop', 'mobile', 'channel')
CORE_FIELDS = ('title', 'category', 'price', 'options', 'shipping', 'returns', 'supply')
COLLECTIONS = ('sources', 'facts', 'observations', 'questions', 'fields', 'assets', 'issues')
IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.gif', '.webp')


def text(value):
    return isinstance(value, str) and bool(value.strip())


def local_file(root, name):
    if not text(name) or '\\' in name:
        raise ValueError('자료 경로 필요')
    p = Path(name)
    if p.is_absolute() or '..' in p.parts or len(p.parts) < 2 or p.parts[0] not in ('assets', 'sources'):
        raise ValueError('자료 경로는 assets/ 또는 sources/ 내부여야 함: '+name)
    root = Path(root)
    if root.is_symlink():
        raise ValueError('자료 폴더 심볼릭 링크 금지')
    cursor = root
    for part in p.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError('심볼릭 링크 자료 금지: '+name)
    if not cursor.is_file() or not cursor.resolve().is_relative_to(root.resolve()):
        raise ValueError('자료 없음 또는 경로 이탈: '+name)
    return cursor


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def block_assets(block):
    return set(block['asset_ids']) | {p['asset_id'] for p in block.get('photos', [])}


def used_assets(data):
    return set().union(*(block_assets(b) for b in data['content']['blocks'])) | ({data['content']['main_asset_id']} if data['content']['main_asset_id'] else set())



def asset_ready(asset, assets):
    seen = set()
    current = asset
    while current:
        if current['id'] in seen:
            return False
        seen.add(current['id'])
        if current['status'] != 'ready' or current['rights'] == 'unknown':
            return False
        if (current is not asset or current['task']=='edit') and current['rights']!='edit':
            return False
        current = assets.get(current['derived_from']) if current['derived_from'] else None
    return True


def readiness(data):
    """Derived axes, called only after structural validation."""
    missing = []
    fields = {f['id']: f for f in data['fields']}
    required = set(CORE_FIELDS) | set(data['channel']['required_field_ids'])
    for key in sorted(required):
        if key not in fields or fields[key]['status'] != 'ready':
            missing.append('required:'+key)
    if data['channel']['status'] != 'verified':
        missing.append('channel-requirements')
    if not data['scope_source_refs']:
        missing.append('product-scope')
    if not data['strategy']['queries'] or not data['questions'] or not data['content']['blocks']:
        missing.append('content-incomplete')
    if not data['content']['main_asset_id']:
        missing.append('main-image')
    assets = {a['id']: a for a in data['assets']}
    used = used_assets(data)
    for a in data['assets']:
        if a['id'] in used:
            if not asset_ready(a, assets):
                missing.append('asset:'+a['id'])
    for block in data['content']['blocks']:
        for photo in block.get('photos', []):
            asset = assets[photo['asset_id']]
            dimensions = asset.get('dimensions')
            if dimensions and photo['region'] != [0, 0, *dimensions] and asset['rights'] != 'edit':
                blocker = 'image-edit:' + asset['id']
                if blocker not in missing: missing.append(blocker)
    missing += ['issue:'+i['id'] for i in data['issues'] if i['status']=='open' and i['severity']=='blocker']
    blocks = list(missing)
    passed = {c['id'] for c in data.get('review',{}).get('checks',[]) if c['status']=='pass'}
    blocks += ['review:'+c for c in CHECKS if c not in passed]
    return dict(strategy=data['strategy']['status'], output='partial' if missing else 'complete',
                publication='blocked' if blocks else ('approved' if data.get('approval') else 'reviewable'), blockers=blocks)


def validate(data, root):
    errors = []
    def require(ok, message):
        if not ok: errors.append(message)
    def texts(obj, keys, label):
        for k in keys:
            require(text(obj.get(k)), f'{label}.{k}: 값 필요')
    def refs(value, index, label, required=False):
        ok = isinstance(value,list) and all(isinstance(x,str) and x in index for x in value)
        require(ok and (bool(value) or not required), label+': 참조 오류')
        return ok
    def stamp(value, label, optional=False):
        if value is None and optional: return
        try:
            require(isinstance(value,str),label+': 날짜 필요')
            datetime.fromisoformat(value)
        except (TypeError,ValueError): require(False,label+': ISO 날짜 필요')
    def metric(m,label):
        require(isinstance(m,dict),label+': 수치 객체 필요')
        if not isinstance(m,dict): return
        require(m.get('status') in ('confirmed','estimated','unknown'),label+': 수치 구분 필요')
        refs(m.get('source_refs'),indexes['sources'],label+'.source_refs',m.get('status')!='unknown')
        texts(m,('period','definition','device','note'),label)
        v=m.get('value')
        if m.get('status')=='unknown': require(v is None,label+': 모름은 null')
        else: require(type(v) in (int,float) and 0<=v<=sys.float_info.max,label+': 유한한 비음수 필요')
    def usable(fact_ids, label):
        for fid in fact_ids:
            if fid not in indexes['facts']: continue
            f=indexes['facts'][fid]
            require(f['status'] not in ('unknown','conflict'),label+': 미확인·충돌 사실 사용 금지')
            require(all(indexes['sources'][s]['access']=='available' for s in f['source_refs']),label+': 미조회 출처로 상품 주장 금지')
            require(any(indexes['sources'][s]['kind'] not in ('competitor','search','reference') for s in f['source_refs']),label+': 경쟁·포맷 자료만으로 상품 주장 금지')
    try:
        if not isinstance(data,dict): return ['패키지는 객체여야 함']
        require(data.get('schema_version')=='listing-2','listing-2만 지원; 이전 계약 자동 변환 금지')
        texts(data,('package_id','scope'),'package')
        indexes={}
        for key in COLLECTIONS:
            rows=data.get(key)
            if not isinstance(rows,list) or not all(isinstance(r,dict) for r in rows):
                return errors+[key+': 객체 배열 필요']
            ids=[r.get('id') for r in rows]
            if not all(text(i) for i in ids): return errors+[key+': ID 필요']
            require(len(ids)==len(set(ids)),key+': 중복 ID')
            indexes[key]={r['id']:r for r in rows}
        refs(data.get('scope_source_refs'),indexes['sources'],'scope_source_refs')
        for s in data['sources']:
            label='source:'+s['id']
            texts(s,('location','scope','note'),label)
            require(s.get('kind') in ('supplier','provided','verified','channel','search','competitor','reference'),label+': 종류 오류')
            require(s.get('access') in ('available','blocked','not_checked'),label+': 접근 상태 오류')
            stamp(s.get('observed_at'),label,s.get('access')!='available')
            if s.get('local_path'):
                p=local_file(root,s['local_path'])
                require(s.get('sha256')==sha_file(p),label+': 파일 변조')
        for i in data['issues']:
            label='issue:'+i['id']
            texts(i,('question','resolve_by','impact','owner'),label)
            require(i.get('severity') in ('blocker','warning') and i.get('status') in ('open','resolved'),label+': 상태 오류')
            refs(i.get('source_refs'),indexes['sources'],label,i.get('status')=='resolved')
            if i.get('status')=='resolved': texts(i,('resolution',),label)
        for f in data['facts']:
            label='fact:'+f['id']
            texts(f,('scope','locator','note'),label)
            require(f.get('status') in ('supplier_stated','user_provided','verified','conflict','unknown'),label+': 상태 오류')
            require(f.get('numeric_status') in ('confirmed','estimated','unknown','not_numeric'),label+': 수치 구분 오류')
            refs(f.get('source_refs'),indexes['sources'],label,f.get('status')!='unknown')
            refs(f.get('issue_refs'),indexes['issues'],label+'.issues',f.get('status') in ('unknown','conflict'))
            if f.get('status')=='unknown': require(f.get('value') is None,label+': 모름은 null')
            else: require(text(f.get('value')),label+': 단위 포함 문자열 필요')
        for o in data['observations']:
            label='observation:'+o['id']
            texts(o,('query','surface','device','login','sampling','ad'),label)
            stamp(o.get('observed_at'),label)
            refs(o.get('source_refs'),indexes['sources'],label,True)
            require(isinstance(o.get('competitors'),list),label+': 경쟁 비교 배열 필요')
            for c in o['competitors']:
                texts(c,('name','scope','delivery','information','trust','note'),label+'.competitor')
                require(c.get('relation') in ('same','substitute'),label+': 동일/대체 구분 필요')
                refs(c.get('source_refs'),indexes['sources'],label,True)
                metric(c.get('total_price'),label+'.total_price')
        st=data['strategy']
        texts(st,('summary','reason_to_choose','counter_evidence','uncertainties'),'strategy')
        require(st.get('status') in ('supported','hypothesis','reconsider'),'strategy: 상태 오류')
        queries=st['queries']
        if not isinstance(queries,list) or not all(isinstance(q,dict) and text(q.get('id')) for q in queries):
            return errors+['strategy.queries: ID 있는 객체 배열 필요']
        qindex={q['id']:q for q in queries}
        require(len(qindex)==len(queries),'queries: 중복 ID')
        for q in queries:
            label='query:'+q['id']
            texts(q,('query','intent','reason'),label)
            require(q.get('origin') in ('observed','hypothesis'),label+': 관측/가설 필요')
            require(q.get('decision') in ('target','exclude','hold'),label+': 채택/제외/보류 필요')
            require(q.get('fit') in ('match','mismatch','unknown'),label+': 적합성 필요')
            refs(q.get('fact_refs'),indexes['facts'],label,q.get('fit')=='match')
            refs(q.get('observation_refs'),indexes['observations'],label,q.get('origin')=='observed')
            if q.get('fit')=='mismatch': require(q.get('decision')=='exclude',label+': 조건 불일치는 제외')
            if q.get('fit')=='match': usable(q['fact_refs'],label)
            metric(q.get('demand'),label+'.demand')
        if st.get('status')=='supported':
            selected=[q for q in queries if q.get('decision')=='target']
            require(bool(selected) and all(q['fit']=='match' and q['observation_refs'] for q in selected),'strategy: 근거 확보에는 적합한 관측 검색어 필요')
        for q in data['questions']:
            label='question:'+q['id']
            texts(q,('question','priority','reason'),label)
            require(type(q.get('hypothesis')) is bool,label+': 가설 여부 필요')
            refs(q.get('source_refs'),indexes['sources'],label,not q.get('hypothesis'))
            refs(q.get('fact_refs'),indexes['facts'],label+'.facts')
            refs(q.get('issue_refs'),indexes['issues'],label+'.issues')
            require(bool(q.get('fact_refs')) or bool(q.get('issue_refs')),label+': 답 또는 확인 과제 필요')
        for f in data['fields']:
            label='field:'+f['id']; texts(f,('label','scope','note'),label)
            require(f.get('status') in ('ready','needs_confirmation','not_applicable'),label+': 상태 오류')
            refs(f.get('fact_refs'),indexes['facts'],label+'.facts',f.get('status')=='ready')
            refs(f.get('query_refs'),qindex,label+'.queries')
            refs(f.get('issue_refs'),indexes['issues'],label+'.issues',f.get('status')=='needs_confirmation')
            if f.get('status')=='ready':
                v=f.get('value'); require(text(v) or (isinstance(v,list) and bool(v) and all(text(x) for x in v)),label+': 입력값 필요')
                usable(f['fact_refs'],label)
                require(all(qindex[r]['decision']=='target' for r in f['query_refs'] if r in qindex),label+': 제외/보류 검색어 사용 금지')
            else: require(f.get('value') is None,label+': 미확인/해당 없음은 null')
        ch=data['channel']; texts(ch,('note','category_field_id'),'channel')
        require(ch.get('status') in ('verified','unverified'),'channel: 상태 오류')
        refs(ch.get('source_refs'),indexes['sources'],'channel',ch.get('status')=='verified')
        require(isinstance(ch.get('required_field_ids'),list) and all(text(x) for x in ch['required_field_ids']),'channel: 필수 필드 ID 배열 필요')
        if ch.get('status')=='verified':
            require(all(indexes['sources'][r]['access']=='available' for r in ch['source_refs']), 'channel: 미조회 출처로 필수 목록 확인 불가')
            require(bool(ch['required_field_ids']) and ch['category_field_id'] in ch['required_field_ids'],'channel: 카테고리를 포함한 실제 필수 목록 필요')
        for a in data['assets']:
            label='asset:'+a['id']; texts(a,('scope','alt','instruction'),label)
            require(a.get('status') in ('ready','missing'),label+': 준비 상태 오류')
            require(a.get('rights') in ('unknown','use','edit'),label+': 권한 범위 오류')
            require(a.get('task') in ('use','edit','acquire'),label+': 작업 오류')
            refs(a.get('source_refs'),indexes['sources'],label,a.get('status')=='ready')
            refs(a.get('rights_source_refs'),indexes['sources'],label+'.rights',a.get('rights')!='unknown')
            if a.get('rights')!='unknown':
                require(all(indexes['sources'][r]['access']=='available' for r in a['rights_source_refs']),label+': 미조회 출처로 권한 확인 불가')
            if a.get('derived_from') is not None:
                require(a['derived_from'] in indexes['assets'] and a['derived_from']!=a['id'],label+': 원본 참조 오류')
                require(a.get('task')=='edit',label+': 파생 이미지는 편집 작업')
            if 'dimensions' in a:
                dims=a['dimensions']
                require(isinstance(dims,list) and len(dims)==2 and all(type(v) is int and v>0 for v in dims),label+': dimensions는 양의 정수 두 개')
            if a.get('status')=='ready':
                p=local_file(root,a.get('path'))
                require(p.suffix.lower() in IMAGE_SUFFIXES,label+': 이미지 형식 오류')
                require(a.get('sha256')==sha_file(p),label+': 파일 변조')
                if 'dimensions' in a: require(a['dimensions']==image_size(p),label+': 실제 이미지 크기 불일치')
            else: require(a.get('path') is None and a.get('sha256') is None,label+': 미완성 경로는 null')
        content=data['content']
        require(content.get('layout') in (None,'photo'),'content: 지원하지 않는 layout')
        require(content.get('main_asset_id') is None or content['main_asset_id'] in indexes['assets'],'content: 대표 이미지 참조 오류')
        blocks=content['blocks']
        if not isinstance(blocks,list) or not all(isinstance(b,dict) for b in blocks): return errors+['blocks: 객체 배열 필요']
        bids=[]
        for b in blocks:
            label='block:'+str(b.get('id')); bids.append(b.get('id'))
            texts(b,('id','edit_reason'),label)
            require(isinstance(b.get('heading'),str) and isinstance(b.get('text'),str),label+': 제목·본문 문자열 필요')
            require(b.get('kind') in ('hero','feature','specs','notice'),label+': 블록 종류 오류')
            refs(b.get('question_refs'),indexes['questions'],label+'.questions',True)
            refs(b.get('fact_refs'),indexes['facts'],label+'.facts',True)
            usable(b.get('fact_refs',[]),label)
            refs(b.get('asset_ids'),indexes['assets'],label+'.assets')
            extras = ('kicker','composition','option_text','photos','photo_layout','diagram')
            if any(k in b for k in extras):
                require(content.get('layout')=='photo',label+': 사진 확장은 layout=photo 필요')
            for key in ('kicker','composition','option_text'):
                if key in b:
                    require(b.get('kind')=='hero' and text(b[key]),label+': 도입 정보는 hero의 비어 있지 않은 문자열')
            require(b.get('photo_layout','stack') in ('stack','grid'),label+': 사진 배치 오류')
            photos=b.get('photos',[])
            require(isinstance(photos,list),label+': photos 배열 필요')
            if isinstance(photos,list):
                require(not photos or not b['asset_ids'],label+': photos와 asset_ids 중복 금지')
                for photo in photos:
                    require(isinstance(photo,dict),label+': 사진 객체 필요')
                    if not isinstance(photo,dict): continue
                    require(set(photo)<= {'asset_id','region','caption','alt'},label+': 지원하지 않는 사진 필드')
                    aid=photo.get('asset_id'); region=photo.get('region')
                    require(isinstance(aid,str) and aid in indexes['assets'],label+': 사진 자산 참조 오류')
                    require(isinstance(photo.get('caption'),str),label+': 사진 설명 문자열 필요')
                    if 'alt' in photo: require(text(photo['alt']),label+': 사진 대체 설명 필요')
                    valid=isinstance(region,list) and len(region)==4 and all(type(v) is int for v in region)
                    require(valid,label+': 사진 영역은 정수 [x,y,width,height]')
                    if not valid or not isinstance(aid,str) or aid not in indexes['assets']: continue
                    a=indexes['assets'][aid]; dims=a.get('dimensions')
                    require(isinstance(dims,list) and len(dims)==2,label+': 사진 원본 dimensions 필요')
                    x,y,w,h=region
                    require(x>=0 and y>=0 and w>0 and h>0,label+': 사진 영역은 양의 크기')
                    if isinstance(dims,list) and len(dims)==2:
                        require(x+w<=dims[0] and y+h<=dims[1],label+': 사진 영역이 원본을 벗어남')
            if 'diagram' in b:
                diagram=b['diagram']
                require(isinstance(diagram,dict) and set(diagram)=={'width','height'} and all(text(v) for v in diagram.values()),label+': 도식에는 근거 연결된 width/height 문자열 필요')
            require(isinstance(b.get('rows'),list) and all(isinstance(r,list) and len(r)==2 and all(text(x) for x in r) for r in b['rows']),label+': 표는 [항목, 값] 배열')
            require(text(b['heading']) or text(b['text']) or bool(b['asset_ids']) or bool(photos) or bool(b.get('diagram')) or bool(b['rows']),label+': 빈 블록')
        require(len(bids)==len(set(bids)),'blocks: 중복 ID')
        timing=data['timing']; require(timing.get('unit')=='minutes','timing: minutes 단위')
        for k in ('preparation','research','review','correction','entry','manual_baseline'):
            v=timing[k]; require(v is None or (type(v) in (int,float) and 0<=v<=sys.float_info.max),'timing: 미측정은 null, 측정은 비음수')
    except (KeyError,TypeError,AttributeError,ValueError,OSError) as exc:
        errors.append('구조 또는 파일 오류: '+str(exc))
    return errors
