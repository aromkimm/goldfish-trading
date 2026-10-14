"""Structural validation, immutable bundles and explicit review records."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from datetime import date

FIELD_SPECS = json.loads(Path(__file__).with_name('fields.json').read_text())
CHECKS = ('identity', 'facts', 'additional_value', 'local_render', 'channel')
OPTIONAL_FIELDS = {'seller_code', 'brand_model', 'tags', 'page_title', 'meta_description', 'extras', 'benefits'}
ALWAYS_APPLICABLE = {'title', 'scope', 'category', 'cost', 'price', 'stock', 'main_image', 'detail'}
RESERVED = {'listing-package.json', 'listing-package.md', 'preview.html'}


def read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f'JSON 읽기 실패: {path}: {exc}') from exc


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def local_file(root, name):
    if not isinstance(name, str) or not name or '\\' in name:
        raise ValueError(f'잘못된 자료 경로: {name}')
    p = Path(name)
    if not p.parts or p.is_absolute() or '..' in p.parts or p.parts[0] in RESERVED:
        raise ValueError(f'자료 경로 이탈 또는 예약 이름: {name}')
    target = Path(root).joinpath(p)
    cursor = Path(root)
    for part in p.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(f'심볼릭 링크 자료 금지: {name}')
    if not target.resolve().is_relative_to(Path(root).resolve()) or not target.is_file():
        raise ValueError(f'자료 없음 또는 경로 이탈: {name}')
    return target


def material_revision(data):
    body = {k:v for k,v in data.items() if k not in
            ('revision', 'prepared_at', 'review', 'publication', 'integrity')}
    return 'r-' + digest(body)[:16]


def seal(data):
    data.pop('integrity', None)
    data['integrity'] = digest(data)


def gates(data):
    refs = [i['id'] for i in data['issues'] if i['severity']=='blocker' and i['status']=='open']
    if any(f['id'] not in OPTIONAL_FIELDS and f['status']=='needs_confirmation' for f in data['fields']):
        refs.append('gate-fields')
    if data['content_decision']['type'] in ('pending', 'C'):
        refs.append('gate-content')
    passed = {c['id'] for c in data['review']['checks'] if c['status']=='pass'}
    refs += ['gate-'+c for c in CHECKS if c not in passed]
    if any(a['rights']!='confirmed' or not a.get('source_refs') for a in data['assets']):
        refs.append('gate-rights')
    return refs


def validate(data, root):
    """Return diagnostics, including malformed shapes. This is not a semantic judge."""
    errors = []
    def require(ok, message):
        if not ok: errors.append(message)
    def text(value):
        return isinstance(value, str) and bool(value.strip())
    def refs(values, index):
        return isinstance(values,list) and all(isinstance(v,str) and v in index for v in values)
    try:
        require(isinstance(data,dict), '패키지는 객체여야 함')
        if errors: return errors
        for key in ('package_id','revision','prepared_at','purpose'):
            require(text(data.get(key)), f'{key}: 비어 있는 문자열')
        require(data.get('schema_version') in ('draft-1','mvp-1'), '지원하지 않는 schema_version')
        indexes = {}
        for key in ('sources','facts','fields','issues','assets'):
            rows=data.get(key)
            require(isinstance(rows,list) and all(isinstance(v,dict) for v in rows), f'{key}: 객체 배열 필요')
            if errors: return errors
            idkey='path' if key=='assets' else 'id'
            ids=[r.get(idkey) for r in rows]
            require(all(text(v) for v in ids), f'{key}: ID 필요')
            if errors: return errors
            require(len(ids)==len(set(ids)), f'{key}: 중복 ID')
            indexes[key]={r[idkey]:r for r in rows}
        require(bool(data['sources']), '자료 출처 없음')
        require({f['id'] for f in FIELD_SPECS} <= indexes['fields'].keys(), '기본 등록 필드 누락')
        for s in data['sources']:
            require(all(text(s.get(k)) for k in ('kind','location','observed_at')), f"출처 {s['id']}: 위치·종류·확인일 필요")
            require(isinstance(s.get('note'),str), f"출처 {s['id']}: 적용 한계 필요")
        for f in data['facts']:
            require(text(f.get('value')), f"사실 {f['id']}: 값 필요")
            require(f.get('status') in ('supplier_stated','user_provided','verified','conflict'), f"사실 {f['id']}: 상태 오류")
            require(bool(f.get('source_refs')) and refs(f.get('source_refs'),indexes['sources']), f"사실 {f['id']}: 출처 참조 오류")
        for i in data['issues']:
            require(i.get('severity') in ('blocker','warning') and i.get('status') in ('open','resolved'), f"과제 {i['id']}: 상태 오류")
            require(text(i.get('question')) and text(i.get('resolve_by')), f"과제 {i['id']}: 질문·확인 방법 필요")
            if i.get('status')=='resolved':
                require(text(i.get('resolution')) and bool(i.get('source_refs')) and refs(i['source_refs'],indexes['sources']), f"과제 {i['id']}: 해결 근거 필요")
        for f in data['fields']:
            name=f['id']; status=f.get('status'); kind=f.get('evidence_kind')
            require(text(f.get('label')) and isinstance(f.get('note'),str), f'{name}: 표시명·비고 필요')
            require(status in ('ready','needs_confirmation','not_applicable'), f'{name}: 상태 오류')
            require(kind in ('confirmed','proposal','unknown'), f'{name}: 근거 구분 오류')
            require(refs(f.get('fact_refs'),indexes['facts']), f'{name}: 사실 참조 오류')
            require(refs(f.get('issue_refs'),indexes['issues']), f'{name}: 과제 참조 오류')
            if f.get('value') is not None:
                if name=='tags': require(isinstance(f['value'],list) and bool(f['value']) and all(text(v) for v in f['value']), 'tags: 비어 있지 않은 문자열 배열 필요')
                else: require(text(f['value']), f'{name}: 단위가 드러나는 문자열 필요')
            if status=='ready': require(f.get('value') not in (None,'',[]), f'{name}: 준비된 값 없음')
            if kind=='unknown': require(f.get('value') is None and status=='needs_confirmation', f'{name}: 모름은 null·확인 필요')
            if status=='needs_confirmation':
                require(bool(f.get('issue_refs')) and any(indexes['issues'].get(i,{}).get('status')=='open' for i in f.get('issue_refs',[])), f'{name}: 열린 확인 과제 필요')
            if name in ALWAYS_APPLICABLE: require(status!='not_applicable', f'{name}: 필수값은 해당 없음으로 대체 불가')
            if name=='main_image' and status=='ready': require(isinstance(f.get('value'),str) and f['value'] in indexes['assets'], '대표이미지는 등록된 로컬 자산 경로 필요')
            if status=='not_applicable': require(text(f.get('note')) and kind!='unknown', f'{name}: 해당 없음의 근거 필요')
            if kind=='confirmed': require(bool(f.get('fact_refs')), f'{name}: 확인값 근거 없음')
            if any(indexes['facts'].get(r,{}).get('status')=='conflict' for r in f.get('fact_refs',[])):
                require(status=='needs_confirmation' and f.get('value') is None, f'{name}: 충돌값 확정 금지')
        content=data['content']; decision=data['content_decision']
        require(isinstance(content,dict) and isinstance(decision,dict), 'content·content_decision 객체 필요')
        if errors: return errors
        kind=decision.get('type')
        require(kind in ('A','B','C','pending') and text(decision.get('reason')), '분류·진단 근거 필요')
        blocks=content.get('blocks')
        require(isinstance(blocks,list) and all(isinstance(b,dict) for b in blocks), 'blocks 객체 배열 필요')
        if errors: return errors
        if kind=='A': require(not blocks and not any(content.get(k) for k in ('intro_title','supplier_heading','supplier_note')), 'A에는 추가 문구 없음')
        if kind=='B': require(bool(blocks), 'B에는 근거 있는 보완 문구 필요')
        for b in blocks:
            require(text(b.get('text')) and text(b.get('reason')) and text(b.get('kind')), '보완 문구·이유·구분 필요')
            require(bool(b.get('fact_refs')) and refs(b.get('fact_refs'),indexes['facts']), '보완 문구 사실 참조 오류')
            require(not any(indexes['facts'].get(r,{}).get('status')=='conflict' for r in b.get('fact_refs',[])), '충돌 사실로 문구 생성 금지')
        require(refs(content.get('image_order'),indexes['assets']), '이미지 참조 오류')
        require(content.get('local_preview')=='preview.html', '프리뷰 경로는 preview.html')
        require(isinstance(content.get('transfer_instructions'),list) and all(text(s) for s in content['transfer_instructions']), '입력 안내 배열 필요')
        for a in data['assets']:
            p=local_file(root,a['path']); raw=p.read_bytes()
            require(p.suffix.lower() in ('.jpg','.jpeg','.png','.webp','.gif'), '지원하지 않는 이미지 형식')
            require(a.get('sha256')==hashlib.sha256(raw).hexdigest() and a.get('bytes')==len(raw), f"파일 변조: {a['path']}")
            require(isinstance(a.get('edited'),bool) and text(a.get('rights')) and text(a.get('role')), f"이미지 메타데이터 오류: {a['path']}")
            if a.get('rights')=='confirmed': require(bool(a.get('source_refs')) and refs(a['source_refs'],indexes['sources']), '이미지 권한 근거 필요')
        review=data['review']; pub=data['publication']
        require(isinstance(review,dict) and isinstance(pub,dict), 'review·publication 객체 필요')
        require(isinstance(review['checks'],list), '검사 목록 필요')
        for c in review['checks']:
            require(c['status'] in ('pass','fail','not_run') and text(c['detail']), '검사 결과·범위 필요')
        require(isinstance(review.get('timing'),dict), '작업시간은 미측정 시 null로 기록')
        require(pub.get('status') in ('blocked','reviewable','approved'), '게시 상태 오류')
        approval=pub['approval']
        if data['schema_version']=='mvp-1':
            require(data['revision']==material_revision(data), '내용 변경: 버전 재생성 필요')
            expected=gates(data)
            require(pub['blocker_refs']==expected, '게시 차단 목록 불일치')
            require(pub['status']==('blocked' if expected else ('approved' if approval['status']=='approved' else 'reviewable')), '게시 판단 불일치')
            if any(c['status']!='not_run' for c in review['checks']):
                require(review.get('reviewed_revision')==data['revision'] and text(review.get('reviewer')), '검토자·검토 버전 필요')
            if 'integrity' in data:
                require(data['integrity']==digest({k:v for k,v in data.items() if k!='integrity'}), '패키지 변경: 재생성·재검수 필요')
        if approval['status']=='approved':
            require(pub['status']=='approved' and not pub['blocker_refs'] and text(approval.get('reviewer')) and approval.get('approved_revision')==data['revision'], '승인 조건·버전 불일치')
        else:
            require(approval['status']=='not_requested' and approval.get('reviewer') is None and approval.get('approved_revision') is None, '승인 메타데이터 오류')
    except (KeyError, TypeError, AttributeError, ValueError, OSError) as exc:
        errors.append(f'구조 또는 파일 오류: {exc}')
    return errors


def write_bundle(data, directory):
    from .render import render
    seal(data)
    md, html=render(data)
    if directory.is_symlink(): raise ValueError('출력 폴더 심볼릭 링크 금지')
    for name, body in [('listing-package.json',dump(data)),('listing-package.md',md),('preview.html',html)]:
        target=directory/name
        if target.is_symlink(): raise ValueError('출력 파일 심볼릭 링크 금지: '+name)
        # Replace the directory entry rather than following a changed destination.
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=directory,delete=False) as tmp:
            tmp.write(body); temporary=Path(tmp.name)
        try: temporary.replace(target)
        finally: temporary.unlink(missing_ok=True)


def build(candidate, output, previous=None):
    candidate=Path(candidate); output=Path(output)
    if output.exists(): raise ValueError('출력 폴더가 이미 있음. 새 폴더를 사용하세요.')
    data=read(candidate)
    # Candidate is untrusted, including its asserted approvals and completed reviews.
    if not isinstance(data,dict): raise ValueError('패키지는 객체여야 함')
    data.pop('integrity',None)
    data['publication']={'status':'blocked','blocker_refs':[], 'approval':{'status':'not_requested','reviewer':None,'approved_revision':None}}
    data['review']={'scope':'자동 구조 검사와 사람의 의미·화면·채널 검수를 구분',
                   'checks':[{'id':c,'status':'not_run','detail':'현재 버전 검수 필요'} for c in CHECKS],
                   'timing':{'unit':'minutes','manual_baseline':None,'preparation':None,'review':None,'correction':None,'entry':None}}
    data['schema_version']='draft-1'
    errors=validate(data,candidate.parent)
    if errors: raise ValueError('\n'.join(errors))
    if previous:
        errors=check(previous)
        if errors: raise ValueError('이전 패키지 오류: '+'; '.join(errors))
        old=read(Path(previous)/'listing-package.json')
        if old['package_id']!=data['package_id']: raise ValueError('다른 상품 패키지를 수정할 수 없음')
    data['schema_version']='mvp-1'; data['prepared_at']=date.today().isoformat()
    data['revision']=material_revision(data)
    data['publication']['blocker_refs']=gates(data)
    data['publication']['status']='blocked' if gates(data) else 'reviewable'
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.listing-',dir=output.parent) as tmp:
        stage=Path(tmp)/'bundle'; stage.mkdir()
        paths={a['path'] for a in data['assets']}
        for s in data['sources']:
            if s.get('local_path'): paths.add(s['local_path'])
        for name in paths:
            src=local_file(candidate.parent,name); dst=stage/name
            dst.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(src,dst)
        write_bundle(data,stage)
        errors=check(stage)
        if errors: raise ValueError('; '.join(errors))
        stage.rename(output)
    return data


def check(directory):
    from .render import render
    directory=Path(directory)
    try:
        if directory.is_symlink(): return ['패키지 폴더 심볼릭 링크 금지']
        for name in RESERVED:
            target=directory/name
            if target.is_symlink() or not target.is_file(): return ['출력 파일 누락 또는 심볼릭 링크: '+name]
        data=read(directory/'listing-package.json')
        errors=validate(data,directory)
        if data.get('schema_version')!='mvp-1' or not data.get('integrity'):
            errors.append('검증 가능한 빌드 패키지가 아님: build 필요')
        if errors: return errors
        md, html=render(data)
        for name, expected in [('listing-package.md',md),('preview.html',html)]:
            if (directory/name).read_text(encoding='utf-8')!=expected:
                errors.append(f'파생본 불일치: {name}')
        for s in data['sources']:
            if s.get('local_path'):
                p=local_file(directory,s['local_path'])
                if s.get('sha256')!=hashlib.sha256(p.read_bytes()).hexdigest(): errors.append(f"자료 변조: {s['id']}")
        return errors
    except (OSError,ValueError) as exc: return [str(exc)]


def record_review(directory, report):
    directory=Path(directory); errors=check(directory)
    if errors: raise ValueError('; '.join(errors))
    data=read(directory/'listing-package.json')
    if report.get('revision')!=data['revision'] or not report.get('reviewer'):
        raise ValueError('검토자와 현재 버전을 명시하세요.')
    rows=report.get('checks',[])
    if not isinstance(rows,list) or {c.get('id') for c in rows}!=set(CHECKS) or len(rows)!=len(CHECKS):
        raise ValueError('전체 검사 항목을 pass/fail/not_run으로 기록하세요.')
    data['review'].update(checks=rows,reviewer=report['reviewer'],reviewed_revision=data['revision'])
    data['publication']['approval']={'status':'not_requested','reviewer':None,'approved_revision':None}
    data['publication']['blocker_refs']=gates(data)
    data['publication']['status']='blocked' if gates(data) else 'reviewable'
    seal(data); errors=validate(data,directory)
    if errors: raise ValueError('; '.join(errors))
    write_bundle(data,directory)
    return data


def approve(directory, reviewer, revision):
    directory=Path(directory); errors=check(directory)
    if errors: raise ValueError('; '.join(errors))
    data=read(directory/'listing-package.json')
    if not isinstance(reviewer,str) or not reviewer.strip() or revision!=data['revision'] or gates(data):
        raise ValueError('현재 버전·검토자·차단 해소·검수 통과가 모두 필요합니다.')
    data['publication'].update(status='approved',approval={'status':'approved','reviewer':reviewer,'approved_revision':revision})
    write_bundle(data,directory)
    return data
