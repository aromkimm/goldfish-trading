"""CLI bridge for the conversational agent; no autonomous web/model calls."""
import argparse
from pathlib import Path
import sys
from .package import prepare, build, check, record_review, approve, read, dump, CHECKS
from .schema import validate


def main(argv=None):
    parser=argparse.ArgumentParser(description='검색 의도 중심 판매 등록 에이전트 보조 도구 · listing-2')
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('prepare','build'):
        p=sub.add_parser(name); p.add_argument('input',type=Path); p.add_argument('--out',type=Path,required=True)
        if name=='build': p.add_argument('--previous',type=Path)
    p=sub.add_parser('validate'); p.add_argument('input',type=Path)
    for name in ('check','review-template','review','approve'):
        p=sub.add_parser(name); p.add_argument('directory',type=Path)
        if name=='review': p.add_argument('--report',type=Path,required=True)
        if name=='approve':
            p.add_argument('--reviewer',required=True); p.add_argument('--revision',required=True); p.add_argument('--decision')
    args=parser.parse_args(argv)
    try:
        if args.command=='prepare':
            prepare(args.input,args.out); result={'prepared':str(args.out),'next':'request.md를 에이전트에 전달'}
        elif args.command=='build': result=build(args.input,args.out,args.previous)['state']
        elif args.command=='review': result=record_review(args.directory,read(args.report))['state']
        elif args.command=='approve': result=approve(args.directory,args.reviewer,args.revision,args.decision)['state']
        else:
            errors=validate(read(args.input),args.input.parent) if args.command=='validate' else check(args.directory)
            if errors: raise ValueError('\n'.join(errors))
            if args.command=='review-template':
                d=read(args.directory/'listing-package.json')
                result=dict(revision=d['revision'],reviewer='검토자 입력',checks=[dict(id=c,status='not_run',detail='미실행',evidence='미실행') for c in CHECKS])
            else: result={'structure':'pass','note':'의미 검수·채널 검수·게시 승인과 별개'}
        print(dump(result),end=''); return 0
    except (ValueError,OSError,TypeError,KeyError,AttributeError) as exc:
        print('실행 중단: '+str(exc),file=sys.stderr); return 1
