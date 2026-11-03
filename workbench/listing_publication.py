"""Account-bound read-only Workctl product collector. No publishing operations."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading

COMMAND='icbu.product.query-product-by-id'
_poll_thread = None
_poll_start_lock = threading.Lock()
_poll_lock = threading.Lock()


def parse_product(payload, product_id):
    """Parse the observed wire shape; numeric status semantics remain unverified."""
    if payload.get('success') is not True or payload.get('truncated') is True:
        raise ValueError('Product query failed or incomplete')
    value = (payload.get('data') or {}).get('productQueryResult')
    value = json.loads(value) if isinstance(value, str) else value
    if (not isinstance(value, dict) or isinstance(value.get('productId'), bool)
            or str(value.get('productId')) != str(product_id)):
        raise ValueError('Product query response ID does not match the requested product')
    statuses = {name: value[name] for name in ('status', 'auditStatus') if name in value
                and (value[name] is None or type(value[name]) is int
                     or isinstance(value[name], str) and len(value[name]) <= 80)}
    return {'item_id':str(value['productId']),'status':'unknown',
            'status_field':'data.productQueryResult.status' if 'status' in statuses else '',
            'status_text':'','mapping_verified':False,
            'status_values':statuses,
            'reason':'商品ID及状态原值已回读，数字枚举含义尚未核实；未按正式版存在推断已上架'}


def verify_schema(schema):
    parameter=next((row for row in schema.get('params',[]) if row.get('name')=='productId'),{})
    if (schema.get('success') is not True or schema.get('mutating') is True or schema.get('requires_yes')
            or schema.get('command')!='workctl icbu product query-product-by-id'
            or parameter.get('agent_flag')!='--prod-id' or parameter.get('type')!='integer'
            or parameter.get('required') is not True):
        raise ValueError('Current product query schema changed; query blocked')


def verify_observation(observation, product_id):
    """Reparse hash-bound backend files, never trust a claimed normalized status."""
    source = observation.get('source') or {}
    if (source.get('kind') != 'workctl-tool' or source.get('method') != 'TOOLS/CALL'
            or source.get('command') != COMMAND or source.get('read_only') is not True
            or source.get('schema_verified') is not True):
        raise ValueError('Unverified product query source')
    output = Path(source.get('evidence_file', ''))
    schema_file = Path(source.get('schema_file', ''))
    if (not output.is_absolute() or not schema_file.is_absolute()
            or output.parent.resolve() != schema_file.parent.resolve()
            or output.is_symlink() or schema_file.is_symlink()):
        raise ValueError('Unverified query evidence paths')
    if os.name == 'nt' and output.drive.upper() != 'D:':
        raise ValueError('Query evidence must stay on D drive')
    payload_bytes, schema_bytes = output.read_bytes(), schema_file.read_bytes()
    if (hashlib.sha256(payload_bytes).hexdigest() != source.get('payload_sha256')
            or hashlib.sha256(schema_bytes).hexdigest() != source.get('schema_sha256')):
        raise ValueError('Product query evidence changed')
    verify_schema(_json(schema_bytes.decode('utf-8-sig')))
    parsed = parse_product(_json(payload_bytes.decode('utf-8-sig')), product_id)
    row = observation.get('row') or {}
    if any(row.get(key) != value for key, value in parsed.items()):
        raise ValueError('Product status row differs from original query evidence')
    return parsed


def _json(text):
    data=json.loads(text)
    if not isinstance(data,dict): raise ValueError('CLI object response required')
    return data


def collect(target, root, bridge=None, run=None, require_identity=None):
    """Only schema + query-product-by-id; identity is checked on both sides.

    Dependencies may be injected for offline verification. Backend callers never
    accept command names, schema claims or observations supplied by a web client.
    """
    if (not re.fullmatch(r'[1-9][0-9]{0,24}',str(target.get('product_id','')))
            or not re.fullmatch(r'[1-9][0-9]{0,24}',str(target.get('draft_id','')))
            or not target.get('expected_account') or not target.get('store')):
        raise ValueError('Explicit platform product/draft/account/store required')
    if bridge is None:
        import bridge_catalog
        bridge=bridge_catalog.current_bridge()
    if run is None or require_identity is None:
        import weekly_update
        run=run or weekly_update.run
        require_identity=require_identity or weekly_update.require_identity
    bridge=Path(bridge); root=Path(root).resolve()
    # Production callers use a project .state directory; keep all configurable
    # workctl state and temporary files alongside this isolated evidence run.
    if os.name=='nt' and root.drive.upper()!='D:': raise ValueError('Publication evidence must stay on D drive')
    root.mkdir(parents=True,exist_ok=True)
    config=root/'workctl-config'; config.mkdir(exist_ok=True)
    temporary=root/'tmp'; temporary.mkdir(exist_ok=True)
    env=dict(os.environ,WORKCTL_CONFIG_DIR=str(config),TMP=str(temporary),TEMP=str(temporary),
             PYTHONIOENCODING='utf-8')
    executable=str(bridge/'workctl.cmd')
    require_identity(bridge,root/'identity-before.json',target['expected_account'],env=env)
    try:
        schema=_json(run([executable,'schema',COMMAND,'--format','json'],cwd=root,timeout=45,env=env))
        verify_schema(schema)
        schema_bytes=json.dumps(schema,ensure_ascii=False,sort_keys=True).encode('utf-8')
        (root/'schema.json').write_bytes(schema_bytes)
        output=root/'query-product.json'
        output.unlink(missing_ok=True)
        run([executable,'icbu','product','query-product-by-id','--prod-id',str(target['product_id']),
             '--format','json','--output',str(output)],cwd=root,timeout=90,env=env)
        payload_bytes=output.read_bytes(); payload=_json(payload_bytes.decode('utf-8-sig'))
        if payload.get('success') is not True or payload.get('truncated') is True:
            raise ValueError('Product query failed or incomplete')
        row=parse_product(payload,target['product_id'])
        row['draft_id']=str(target['draft_id'])
    finally:
        require_identity(bridge,root/'identity-after.json',target['expected_account'],env=env)
    observation={'identity':{'verified':True,'account_id':str(target['expected_account'])},
        'source':{'kind':'workctl-tool','method':'TOOLS/CALL','command':COMMAND,'read_only':True,
            'schema_verified':True,'schema_sha256':hashlib.sha256(schema_bytes).hexdigest(),
            'schema_file':str(root/'schema.json'),
            'evidence_file':str(output),'payload_sha256':hashlib.sha256(payload_bytes).hexdigest()},
        'observed_at':datetime.now(timezone.utc).isoformat(),'row':row}
    (root/'observation.json').write_text(json.dumps(observation,ensure_ascii=False,indent=2),encoding='utf-8')
    return observation


def poll_once(products=None, refresh=None):
    """One bounded read-only pass; the API owns revision/draft compare-and-write."""
    import weekly_update
    if not _poll_lock.acquire(blocking=False):
        return {'refreshed': 0, 'failed': 0, 'skipped': 0}
    try:
        if products is None:
            import task_store
            products = task_store.records('products')
        result = {'refreshed': 0, 'failed': 0, 'skipped': 0}
        for product in products:
            # Browser-based status reads create visible tabs. Run them only from
            # an explicit user refresh, never from the background polling loop.
            if (product.get('workflow') or {}).get('listingMechanism') == 'original-skill-v1':
                result['skipped'] += 1
                continue
            draft = product.get('draft') or {}
            key = (product.get('facts') or {}).get('store')
            if (not weekly_update.STORES.get(key, {}).get('expected_id')
                    or draft.get('store') not in (None, '', key)
                    or not re.fullmatch(r'[1-9][0-9]{0,24}', str(draft.get('draft_id', '')))
                    or not re.fullmatch(r'[1-9][0-9]{0,24}', str(draft.get('product_id') or draft.get('draft_id', '')))):
                result['skipped'] += 1
                continue
            try:
                if refresh is None:
                    import operations_api
                    refresh = operations_api.command
                refresh({'action': 'publication.refresh', 'id': product['id']})
                result['refreshed'] += 1
            except Exception:
                result['failed'] += 1  # No immediate retries or credential-bearing exception logs.
        return result
    finally:
        _poll_lock.release()


def start_polling():
    """Start once per process; no platform call when there is no bound draft."""
    global _poll_thread
    with _poll_start_lock:
        if _poll_thread is not None and _poll_thread.is_alive():
            return
        def loop():
            interval = threading.Event()
            while True:
                try:
                    poll_once()
                except Exception:
                    pass
                interval.wait(60)
        _poll_thread = threading.Thread(target=loop, name='listing-publication-readback', daemon=True)
        _poll_thread.start()
