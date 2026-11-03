"""Copy the explicitly approved m1 unchanged into the following suite job."""
import shutil
import task_store as store


def prepare_reuse(product, root, policy):
    from single_approval_flow import require_hero, image_path
    from native_template_runner import image_hash
    scope = require_hero(product)
    source = image_path(product['hero'], product['hero']['images'][0])
    if image_hash(source) != scope['pixelHash']:
        raise ValueError('已确认首图发生变化，不能生成套图')
    destination = root / 'images/m1.png'
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    policy['heroReuse'] = dict(scope, file='images/m1.png')
    return destination


def verify_reuse(product, root, row, policy):
    from single_approval_flow import require_hero
    from native_template_runner import image_hash
    from skill_jobs import artifact
    scope = require_hero(product)
    expected = policy.get('heroReuse') or {}
    if (row.get('slot') != 'm1' or row.get('file') != expected.get('file')
            or any(expected.get(key) != value for key, value in scope.items())
            or image_hash(artifact(root, row['file'])) != scope['pixelHash']):
        raise ValueError('套图首图与已确认的实际首图不一致，不能重新设计或替换')
    return dict(row, approvedHeroJob=scope['heroJob'], specCheck='ok',
                quality={'reviewRequired':False,'reviewSource':'explicit-hero-approval'},
                reviewRequirements=[], sourceSpecCheck=product['hero']['images'][0].get('specCheck','unchecked'))
