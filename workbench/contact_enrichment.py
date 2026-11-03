"""Guard the upstream contact collector before it can query or change store data."""
import argparse
from contextlib import redirect_stdout
from datetime import date
import importlib.util
import io
import json
from pathlib import Path
import sys


def enrich(module,folder,expected,start,end):
    if not str(expected).isdigit() or not 0 <= (date.fromisoformat(end)-date.fromisoformat(start)).days < 7:
        raise ValueError('Invalid store or contact window')
    path=folder/'conversations.json'
    original=path.read_bytes()
    contact_path=folder/'contacts.json'
    original_contacts=contact_path.read_bytes() if contact_path.is_file() else None
    data=json.loads(original.decode('utf-8-sig'))
    def validate(value):
        if (str(value.get('store',{}).get('aliId'))!=str(expected)
                or str(value.get('window',{}).get('since',''))[:10]!=start
                or str(value.get('window',{}).get('until',''))[:10]!=end):
            raise ValueError('Contact enrichment store/window mismatch')
    validate(data)
    resolve=module.resolve_identity
    call=module.call_tool
    failures=[]
    allowed_accounts=set()
    def guarded_identity():
        current,members=resolve()
        if str(current.get('CURRENT_SELF_ALIID') or '')!=str(expected):
            raise ValueError('Contact enrichment account mismatch')
        allowed_accounts.update(str(member.get('aliId')) for member in members)
        return current,members
    def guarded_call(tool,payload,timeout=180):
        if tool not in ('query_active_conversation_msg','query_conversation_info'):
            raise ValueError('Unsupported contact read')
        if str(payload.get('selfAliId')) not in allowed_accounts:
            raise ValueError('Contact account outside verified store members')
        result=call(tool,payload,timeout=timeout)
        if not isinstance(result,dict) or result.get('success') is not True:
            failures.append(tool)
        return result
    module.resolve_identity=guarded_identity
    module.call_tool=guarded_call
    arguments=sys.argv
    try:
        sys.argv=['fetch_buyer_contacts.py','--start-date',start,'--end-date',end]
        # Do not print customer details, tokens or account names from upstream logs.
        with redirect_stdout(io.StringIO()):
            status=module.main()
        if status!=0 or failures:
            raise ValueError('Contact enrichment incomplete; no new report published')
        validate(json.loads(path.read_text(encoding='utf-8-sig')))
        contacts=json.loads((folder/'contacts.json').read_text(encoding='utf-8-sig'))
        if (str(contacts.get('store',{}).get('CURRENT_SELF_ALIID') or '')!=str(expected)
                or contacts.get('window')!={'start':start,'end':end}):
            raise ValueError('Contact result store/window mismatch')
        rows=contacts.get('contacts') or {}
        return {'contacts':len(rows),'withEmail':sum(bool(r.get('email')) for r in rows.values()),
                'source':'platform_contact_details','complete':True}
    except BaseException:
        path.write_bytes(original)
        if original_contacts is not None:
            contact_path.write_bytes(original_contacts)
        elif contact_path.is_file():
            contact_path.unlink()
        raise
    finally:
        sys.argv=arguments
        module.resolve_identity=resolve
        module.call_tool=call


def main():
    parser=argparse.ArgumentParser()
    for name in ('engine','bridge','expected','start','end'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    engine=Path(args.engine).resolve();bridge=Path(args.bridge).resolve()
    sys.path.insert(0,str(engine))
    spec=importlib.util.spec_from_file_location('inquiry_contact_snapshot',engine/'fetch_buyer_contacts.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.BIN=str(bridge)
    module.CLI=str(bridge/('accio-mcp-cli.cmd' if sys.platform=='win32' else 'accio-mcp-cli'))
    if not Path(module.CLI).is_file():
        raise ValueError('Existing contact bridge is unavailable')
    print(json.dumps(enrich(module,engine/'inquiry',args.expected,args.start,args.end)))


if __name__=='__main__':
    main()
