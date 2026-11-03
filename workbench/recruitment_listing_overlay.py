"""Proposed recruitment attributes for the original listing Skill, without I/O."""
import copy
import re


ALIASES = {
    'benefits': ('Function', '功效', '功能'),
    'product_advantages': ('Product Benefits', 'Product Benefit', 'Product Advantages', '产品优势'),
    'target_audience': ('Applicable People', 'Applicable Population', '适用人群'),
    'unsuitable_audience': ('Not Applicable People', 'Unsuitable People', '不适宜人群'),
    'shelf_life': ('Shelf-Life', 'Shelf Life', '保质期'),
    'dosage_form': ('Dosage Form', '剂型'),
    'protein_per_serving': ('Protein Grams Per Serving', 'Protein Per Serving', '每份蛋白质克数'),
    'material_features': ('Material Features', '材料特征'),
    'dietary_labels': ('Dietary Labels', '饮食特色'),
    'main_ingredient': ('Main Ingredient', '主要成分'),
}


def _name(value):
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', str(value).casefold())


def _label(value):
    return re.sub(r'\s+', '', str(value)).casefold()


def _key(value):
    for key, aliases in ALIASES.items():
        if value == key or _name(value) in {_name(name) for name in aliases}:
            return key
    return None


def _select(row, assignments, previous):
    expected = row.get('expected') or []
    options = [dict(option) for option in row.get('options') or []
               if isinstance(option, dict) and option.get('name')
               and (not expected or _label(option['name']) in {_label(v) for v in expected})]
    if not row.get('options'):
        options = [{'name': value, 'id': ''} for value in expected if isinstance(value, str) and value.strip()]
    candidates = [item for item in assignments if row.get('fieldId')
                  and str(item.get('fieldId')) == str(row['fieldId'])]
    if row.get('assignment'):
        candidates.append(row['assignment'])
    if candidates:
        chosen = []
        for assignment in candidates:
            if str(assignment.get('categoryId', row.get('categoryId', ''))) != str(row.get('categoryId', '')):
                return None, 'assignment_category_mismatch'
            ids = [str(value) for value in assignment.get('valueIds') or []]
            matching = [option for option in options if (not ids or str(option.get('id', '')) in ids)
                        and (not assignment.get('value') or _label(option['name']) == _label(assignment['value']))]
            if len(ids) > 1 or len(matching) != 1:
                return None, 'ambiguous_assignment'
            chosen.append(matching[0])
        if len({(str(item.get('id', '')), _label(item['name'])) for item in chosen}) != 1:
            return None, 'conflicting_assignments'
        return chosen[0], ''
    if len(options) == 1:
        return options[0], ''
    values = previous if isinstance(previous, list) else [previous]
    matching = [option for option in options if _label(option['name']) in {_label(v) for v in values if v}]
    return (matching[0], '') if len(matching) == 1 else (None, 'ambiguous_option')


def compose(manifest, handoff, category_id, page_fields=None, category_config=None):
    """Return a DESIGN manifest plus native-ID audit; never mutate the input.

    Offline proposals use the original Skill keys/configuration and retain its
    runtime filling/readback gate. Optional current-page fields use the shape
    [{key, fieldId, categoryId, options:[{id,name}]}] and must agree with topic IDs.
    Price/MOQ, certificate and image requirements are never attribute overrides.
    """
    if not isinstance(manifest, dict) or not isinstance(manifest.get('fields'), dict):
        raise ValueError('Original Skill manifest.fields is required')
    result = {'manifest': copy.deepcopy(manifest), 'field_replacements': [], 'field_sources': {},
              'pending': [], 'passthrough': [], 'category_constraint': {
                  'expected': [], 'actual': str(category_id), 'matched': True}, 'ready': True}
    if not handoff:
        return result
    rows = handoff.get('requirements') or []
    assignments = handoff.get('attributeAssignments') or []
    config = category_config or {}
    constraint = result['category_constraint']
    categories = [row for row in rows if row.get('kind') == 'category']
    constraint['expected'] = list(dict.fromkeys(str(value) for row in categories for value in row.get('expected') or []))
    constraint['matched'] = all(str(category_id) in [str(v) for v in row.get('expected') or []] for row in categories)
    if config.get('category_id') and str(config['category_id']) != str(category_id):
        constraint.update(matched=False, reason='category_config_mismatch')
    plans = []

    def pending(row, code, field=None):
        result['pending'].append({'requirementKey': row.get('key', ''), 'name': row.get('name', ''),
            'field': field, 'fieldId': str(row.get('fieldId') or ''),
            'categoryId': str(row.get('categoryId') or category_id),
            'expected': copy.deepcopy(row.get('expected') or []),
            'options': copy.deepcopy(row.get('options') or []), 'code': code})

    for row in rows:
        if row.get('kind') == 'category':
            continue
        if row.get('kind') != 'attribute':
            result['passthrough'].append(copy.deepcopy(row))
            continue
        key = _key(row.get('name', ''))
        page = None
        if page_fields is not None:
            matches = [field for field in page_fields if
                       (row.get('fieldId') and str(field.get('fieldId')) == str(row['fieldId']))
                       or (not row.get('fieldId') and key and _key(field.get('key', '')) == key)]
            if len(matches) != 1:
                pending(row, 'page_field_not_unique', key); continue
            page = matches[0]
            actual_key = _key(page.get('key', ''))
            if not actual_key or (key and key != actual_key):
                pending(row, 'page_field_key_mismatch', key); continue
            key = actual_key
            if str(page.get('categoryId', '')) != str(category_id) or not page.get('fieldId'):
                pending(row, 'page_category_or_field_id_mismatch', key); continue
        if not key:
            pending(row, 'unknown_field'); continue
        if (not constraint['matched'] or (row.get('categoryId') and str(row['categoryId']) != str(category_id))):
            pending(row, 'category_mismatch', key); continue
        skipped = set(config.get('skip_fields') or [])
        for name in ('removed_fields', 'skip_fields'):
            skipped.update((config.get('diff') or {}).get(name) or [])
        if key in skipped:
            pending(row, 'unsupported_field', key); continue
        previous = manifest['fields'].get(key)
        selected, problem = _select(row, assignments, previous)
        if problem:
            pending(row, problem, key); continue
        option_id = str(selected.get('id') or '')
        field_id = str(row.get('fieldId') or '')
        if page is not None:
            options = [option for option in page.get('options') or [] if
                       _label(option.get('name', '')) == _label(selected['name'])
                       and (not option_id or str(option.get('id')) == option_id)]
            if len(options) != 1 or not options[0].get('id'):
                pending(row, 'page_option_not_unique_or_id_mismatch', key); continue
            field_id, option_id = str(page['fieldId']), str(options[0]['id'])
        else:
            allowed = (config.get('dropdown_options') or {}).get(key) or []
            if allowed and _label(selected['name']) not in {_label(value) for value in allowed}:
                # A complete topic DTO can outdate the sampled local options;
                # it authorizes a DESIGN candidate, never a live-page claim.
                native_candidate = bool(str(handoff.get('topicId') or '').strip()
                    and str(handoff.get('sourceFingerprint') or '').strip()
                    and str(row.get('categoryId', '')) == str(category_id)
                    and re.fullmatch(r'[1-9][0-9]*', field_id)
                    and re.fullmatch(r'[1-9][0-9]*', option_id)
                    and _label(selected['name']) in {_label(value) for value in row.get('expected') or []}
                    and any(str(option.get('id', '')) == option_id
                            and _label(option.get('name', '')) == _label(selected['name'])
                            for option in row.get('options') or [] if isinstance(option, dict)))
                if not native_candidate:
                    pending(row, 'unsupported_option', key); continue
        value = [selected['name']] if isinstance(previous, list) else selected['name']
        source = {'kind': 'DESIGN', 'topicId': str(handoff.get('topicId', '')),
                  'fingerprint': handoff.get('sourceFingerprint', ''),
                  'source': '征品主题 ' + str(handoff.get('topicId', '')) + ' 快照 '
                            + str(handoff.get('sourceFingerprint', '')) + ' 属性 ' + str(row.get('key', ''))
                            + ' 的拟采用草稿值；不代表实测、已供货或征品通过'}
        plans.append({'requirementKey': row.get('key', ''), 'name': row.get('name', ''),
                      'field': key, 'fieldId': field_id, 'optionId': option_id,
                      'categoryId': str(category_id), 'previous': copy.deepcopy(previous),
                      'value': value, 'source': source,
                      'verification': 'current-page-verified' if page is not None else 'original-skill-runtime-required'})

    for plan in plans:
        if sum(item['field'] == plan['field'] for item in plans) != 1:
            row = next(item for item in rows if item.get('key', '') == plan['requirementKey'])
            pending(row, 'conflicting_requirements', plan['field']); continue
        result['manifest']['fields'][plan['field']] = copy.deepcopy(plan['value'])
        path = 'fields.' + plan['field']
        result['field_sources'][path] = copy.deepcopy(plan['source'])
        if isinstance(result['manifest'].get('field_sources'), dict):
            result['manifest']['field_sources'][path] = copy.deepcopy(plan['source'])
        result['field_replacements'].append(plan)
    result['ready'] = constraint['matched'] and not result['pending']
    return result
