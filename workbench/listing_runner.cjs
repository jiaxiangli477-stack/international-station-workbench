/* Adapter around the installed Skill. No replacement field-filling engine. */
const fs = require('node:fs');
const path = require('node:path');

function runtimePath(file, root, skill) {
  if (typeof file !== 'string') return file;
  const absolute = path.resolve(file);
  const reports = path.join(skill, 'assets/reports');
  const relative = path.relative(reports, absolute);
  if (relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative)))
    return path.join(root, 'reports', relative);
  const temporary = path.relative(path.join(skill, 'assets'), absolute);
  if (/^_tmp_[^/\\]+$/.test(temporary)) return path.join(root, 'skill-tmp', temporary);
  return file;
}

function isolateSkillRuntime(root, skill) {
  // Only a vetted source subset is loaded. Never use the ZIP's portable runtimes.
  if (fs.existsSync(path.join(skill, 'node_modules')) || fs.existsSync(path.join(skill, 'runtime')))
    throw Error('工作台只运行审核后的source-only Skill；请排除包内node_modules/runtime');
  const approved = process.env.WORKBENCH_NODE_MODULES || process.env.NODE_PATH;
  if (!approved || path.delimiter && approved.includes(path.delimiter))
    throw Error('请配置单一已批准Node模块根目录');
  const resolved = require('node:module').createRequire(path.join(skill, 'package.json')).resolve('playwright');
  const relative = path.relative(path.resolve(approved), resolved);
  if (relative.startsWith('..') || path.isAbsolute(relative)) throw Error('拒绝加载未经批准的Playwright依赖');
  const python = process.env.CODEX_PYTHON;
  if (!python || !path.isAbsolute(python) || path.resolve(python).startsWith(path.resolve(skill) + path.sep))
    throw Error('请绑定现有已批准Python，禁止执行Skill便携runtime');
  fs.mkdirSync(path.join(root, 'skill-tmp'), {recursive:true});
  for (const name of ['writeFileSync', 'readFileSync', 'mkdirSync', 'existsSync', 'unlinkSync']) {
    const original = fs[name];
    fs[name] = function(file, ...args) { return original.call(this, runtimePath(file, root, skill), ...args); };
  }
  for (const name of ['writeFile', 'readFile', 'mkdir']) {
    const original = fs.promises[name];
    fs.promises[name] = function(file, ...args) { return original.call(this, runtimePath(file, root, skill), ...args); };
  }
  const child = require('node:child_process');
  const spawn = child.spawnSync;
  const generators = ['subskills/title-scout/scripts/generate.py', 'subskills/selling-points/scripts/generate_selling_points.py']
    .map(file=>path.resolve(skill, file));
  child.spawnSync = function(executable, argv, options) {
    if (path.resolve(executable) !== path.resolve(python) || options?.shell ||
        !(argv.length === 1 && argv[0] === '--version') && !generators.includes(path.resolve(argv[0] || '')))
      throw Error('原Skill尝试执行未批准的子进程，已阻止');
    const args = argv.map(value=>runtimePath(value, root, skill));
    return spawn.call(this, executable, argv[0] === '--version' ? args : ['-B', ...args],
      {...options, cwd:root, env:{...process.env, PYTHONDONTWRITEBYTECODE:'1'}, windowsHide:true});
  };
}
const norm = value => String(value ?? '').replace(/\s+/g, '').toLowerCase();
const BLANK_NET_WEIGHT_NOTICE='用户要求净重留空，后台是否允许保存尚待实际校验';
function allowMissingNetWeight(context={}) {
  return context.listingMechanism==='original-skill-v1'&&context.allowMissingNetWeight===true;
}
function originalSkillRuntimeArgs(context={}) {
  return context.listingMechanism==='original-skill-v1'
    ? ['--cdp-url','http://127.0.0.1:9322',...(allowMissingNetWeight(context)?['--allow-missing-net-weight','1']:[])]:[];
}
function contentGenerationInput(manifest, defaults={}) {
  const value=JSON.parse(JSON.stringify(manifest));
  for(const [key,item] of Object.entries(defaults))if(!value.fields[key]||String(value.fields[key]).includes('TO_CONFIRM'))value.fields[key]=item;
  // Incomplete inputs are allowed only in the offline generation stage. The
  // original execution gate still receives the recomputed missing-field list.
  delete value.missing_required;
  return value;
}
function finishContentGeneration(manifest, required, context={}) {
  if(allowMissingNetWeight(context))manifest.fields.net_weight='';
  const value=key=>manifest.fields?.[key];
  manifest.missing_required=(required||[]).filter(key=>{
    if(key==='net_weight'&&allowMissingNetWeight(context))return false;
    const v=value(key);return v==null||v===''||Array.isArray(v)&&!v.length||typeof v==='string'&&v.includes('TO_CONFIRM');
  });
  return manifest;
}
function skillGeneratedSuggestions(manifest,skill,engine) {
  const {calcPrice}=require(path.join(skill,'subskills/price-filler/scripts/price_calc.cjs'));
  return {kind:'DESIGN',status:'DRAFT_REVIEW',
    fixed_fields:{...engine.FIXED_VALUES},pricing:calcPrice({...manifest,fields:{...manifest.fields,product_type:manifest.fields?.product_type||require(path.join(skill,'scripts/route_category.cjs')).routeManifest(manifest).category}}),
    source:'原上品Skill固定字段、剂型MOQ原表和价格计算脚本；候选方案，不代表实测或已确认SKU报价'};
}
function assertReviewedContent(before,after){
  for(const [key,value] of Object.entries(before.fields||{})){
    if(norm(JSON.stringify(after.fields?.[key]))!==norm(JSON.stringify(value)))
      throw Error(`原Skill执行更改已审核字段${key}，须重新准备方案`);
  }
  for(const key of ['custom_attributes','selling_points','faqs','company_intro','pricing','lead_time','logistics']){
    if(JSON.stringify(before[key]??null)!==JSON.stringify(after[key]??null))
      throw Error(`原Skill执行更改已审核内容${key}，禁止自动覆盖后保存`);
  }
}
function readbackMatches(expected,actual){
  const tokens=value=>new Set((Array.isArray(value)?value:String(value||'').split(/[;,]/)).map(norm).filter(Boolean));
  const wanted=tokens(expected),seen=tokens(actual);
  return wanted.size>0&&wanted.size===seen.size&&[...wanted].every(value=>seen.has(value));
}
function actualFieldReadback(expectedFields,observedFields,skipKeys,context={}) {
  const actualFields={};
  for(const [key,expected] of Object.entries(expectedFields||{})) {
    if(skipKeys?.has(key))continue;
    const actual=observedFields[key]??'';
    if(key==='net_weight'&&allowMissingNetWeight(context)&&String(expected??'').trim()==='') {
      if(String(actual).trim()!=='')throw Error('净重按用户要求应留空，草稿回读却出现非空值，未通过核验');
      continue;
    }
    if(context.listingMechanism==='original-skill-v1'&&String(expected??'').trim()===''&&String(actual).trim()==='')continue;
    actualFields[key]={expected,actual,matched:readbackMatches(expected,actual)};
  }
  return actualFields;
}
async function readSavedListing(page,labels) {
  return page.evaluate(labels=>{
    const fields={};
    for(const [key,label] of Object.entries(labels)){
      const item=Array.from(document.querySelectorAll('.sell-catProp-item')).find(n=>
        Array.from(n.querySelectorAll('label,span,div')).some(e=>e.textContent?.trim()===label));
      if(item)fields[key]=Array.from(item.querySelectorAll('input:not([type="hidden"]),textarea,.next-tag-body,.next-select-values em[title]'))
        .map(n=>n.value||n.getAttribute('title')||n.textContent?.trim()).filter(Boolean).join('; ');
    }
    const title=document.querySelector('input#productTitle,textarea#productTitle')||document.querySelector('input[name="subject"],textarea[name="subject"],input#subject');
    if(title?.value)fields.product_name=title.value;
    const model=window.GPF_GLOBAL_STORE?.json?.models?.global;
    const modelIds=[model?.catId,model?.value?.catId].filter(v=>typeof v==='string'||typeof v==='number').map(String);
    const ids=[...new Set(modelIds.length?modelIds:[new URLSearchParams(location.search).get('catId'),
      document.querySelector('input[name="catId"]')?.value].filter(Boolean))];
    return {fields,category_id:ids.length===1?ids[0]:''};
  },labels);
}
const FIELD_ALIASES = {
  function: 'benefits', dosageform: 'dosage_form', notapplicablepeople: 'unsuitable_audience',
  applicablepeople:'target_audience',productbenefits:'product_advantages',productadvantages:'product_advantages',
  shelflife: 'shelf_life', 剂型: 'dosage_form', 功能: 'benefits', 功效: 'benefits',
  不适宜人群: 'unsuitable_audience', 保质期: 'shelf_life', 主要成分: 'main_ingredient',
};

// Contract supplied by the original Skill, never inferred from DOM image counts.
function bindUploadEvidence(root, delivery, files, response) {
  if (response?.evidenceVersion !== 1 || !Array.isArray(response.assets) || response.assets.length !== files.length)
    throw Error('原Skill未交回可核验file/hash/asset映射，保存已阻止');
  const rows = files.map(file => {
    const entry = delivery.find(row => path.resolve(root, row.file) === path.resolve(file));
    const assets = response.assets.filter(row => path.resolve(root, row.file || '') === path.resolve(file));
    const asset = assets[0];
    if (!entry || assets.length !== 1 || asset.sha256 !== entry.exportHash || !asset.assetId ||
        typeof asset.url !== 'string' || !asset.url.startsWith('https://'))
      throw Error('原Skill图片文件/hash/asset证据不一致，保存已阻止');
    return {slot:entry.slot, file:entry.file, exportHash:entry.exportHash,
      section:entry.section,groupValue:asset.groupValue,groupIndex:asset.groupIndex,
      identityKind:asset.identityKind,requestHash:asset.requestHash,responseHash:asset.responseHash,evidence:asset.evidence,
      assetId:String(asset.assetId),
      actual:asset.url, uploaded:true};
  });
  if (new Set(rows.map(row=>row.assetId)).size !== rows.length) throw Error('上传asset身份重复');
  return rows;
}

function verifyImageEvidence(delivery, uploaded, readback) {
  const positions = {};
  return delivery.map(entry => {
    const index = positions[entry.section] || 0; positions[entry.section] = index + 1;
    const matches = uploaded.filter(row=>row.slot===entry.slot);
    const expected = matches[0];
    const section = readback?.sections?.[entry.section];
    const actual = readback?.evidenceVersion === 1 && Array.isArray(section) ? section[index] : null;
    const same = matches.length===1 && expected?.exportHash===entry.exportHash && expected?.assetId &&
      actual?.assetId && String(actual.assetId)===expected.assetId;
    return {...expected, slot:entry.slot, exportHash:entry.exportHash, evidenceVersion:1,
      groupValue:actual?.groupValue,groupIndex:actual?.groupIndex,
      expectedAssetId:expected?.assetId || '', assetId:actual?.assetId ? String(actual.assetId) : '',
      actual:actual?.url || '', section:entry.section, index,
      matched:Boolean(same && actual.url === expected.actual)};
  });
}

function imageEvidenceSupport(skill, uploader, engine) {
  let version='unverified';
  try { version=JSON.parse(fs.readFileSync(path.join(skill,'package.json'),'utf8')).version || version; } catch (_) {}
  const nativeReady=uploader.uploadEvidenceContractVersion===1 && typeof engine.readSavedImageSections==='function';
  const adapter=require('./listing_image_evidence.cjs').capability();
  const ready=nativeReady||adapter.canAttemptCapture===true;
  return {ready, version,nativeReady,adapter,liveVerified:false,
    original_source:version==='9.2.38' ? {
      upload:'scripts/upload_images.cjs: uploadMainImages/uploadDetailImages only setInputFiles and fixed waits; no asset response returned',
      main_input:'.upload-select-inner input[type="file"]',
      detail_input:'.next-upload.upload-image last() — source does not prove which checked section owns this input',
      parameter_groups:[110,170],
      detail_groups:[200,110,400,450,500,550,600],
      saved_response:'/product/asyRender.json observed by verifySavedDraft, but image node schema is not exposed'
    } : {},
    required_live_evidence:nativeReady ? [] : [
      '脱敏单文件上传请求/响应样本：本地filename/文件sha256与平台assetId、URL的真实字段绑定',
      '保存后重新打开目标itemId的asyRender响应：主图及各详情checkbox分组的有序asset节点/字段',
      '目标类目110或170参数分区与上传input容器的DOM对应；d2、m7(d3@1x)、d3同组时的实际顺序'
    ]};
}

function effectiveBusinessValues(manifest, profile, engine) {
  const output={};
  const company=manifest.company_intro || profile.company_intro;
  if (company) output.company_intro=company;
  const lead=engine.resolveLeadTime(profile,manifest);
  if (lead && (lead.quantity!=='' || lead.days!=='')) output.lead_time=lead;
  const logistics=manifest.clear_unverified_logistics ? null : manifest.logistics || profile.logistics;
  if (logistics) output.logistics=logistics;
  const flavor=manifest.flavor || profile.flavor;
  if (flavor) output.flavor=flavor;
  return output;
}

function sameBusinessValue(key, actual, expected) {
  if (key==='lead_time') return ['quantity','days'].every(name=>String(actual?.[name] ?? '')===String(expected?.[name] ?? ''));
  const stable=value=>Array.isArray(value) ? value.map(stable) : value && typeof value==='object'
    ? Object.fromEntries(Object.keys(value).sort().map(name=>[name,stable(value[name])])) : value;
  return JSON.stringify(stable(actual))===JSON.stringify(stable(expected));
}

function materializeBusinessDefaults(manifest, profile, engine) {
  const changes={...(manifest._adapter_effective_defaults || {})};
  for (const [key,value] of Object.entries(effectiveBusinessValues(manifest,profile,engine))) {
    if (!sameBusinessValue(key,manifest[key],value)) {
      changes[key]={status:'TO_CONFIRM',source:key==='lead_time'
        ? '原Skill resolveLeadTime + assets/_profile.json + references/company/moq-by-dosage-form.json'
        : '原Skill assets/_profile.json 隐式默认；非当前SKU实测资料'};
      manifest[key]=value;
    }
  }
  if (Object.keys(changes).length) manifest._adapter_effective_defaults=changes;
  return manifest;
}

function preflight(manifest, context, skill) {
  const {routeManifest, CATEGORY_MAP} = require(path.join(skill, 'scripts/route_category.cjs'));
  const engine = require(path.join(skill, 'scripts/browser_runner.cjs'));
  const route = routeManifest(manifest);
  const originalFlow=context.listingMechanism==='original-skill-v1';
  if(context.categoryOverride){
    const override=context.categoryOverride;
    if(override.source!=='recruitment-requirement'||!CATEGORY_MAP[override.category]||String(CATEGORY_MAP[override.category].catId)!==String(override.categoryId))throw Error('征品类目覆盖未绑定原Skill配置');
    route.category=override.category;
  }
  const info = CATEGORY_MAP[route.category];
  const blockers = [];
  const checkedManifest=allowMissingNetWeight(context)&&Array.isArray(manifest.missing_required)
    ? {...manifest,missing_required:manifest.missing_required.filter(key=>key!=='net_weight')}:manifest;
  try { engine.assertManifestReady(checkedManifest); }
  catch (error) { blockers.push(error.message); }
  const uploader = require(path.join(skill, 'scripts/upload_images.cjs'));
  const imageEvidence=imageEvidenceSupport(skill,uploader,engine);
  if (!originalFlow&&!imageEvidence.ready)
    blockers.push('原Skill上传仅setInputFiles且未返回file→asset映射；缺保存后图片分区/顺序真实schema，待现场脱敏response/DOM证据，禁止保存');
  const profile=JSON.parse(fs.readFileSync(path.join(skill,'assets/_profile.json'),'utf8'));
  for (const [key,value] of Object.entries(effectiveBusinessValues(manifest,profile,engine)))
    if (!sameBusinessValue(key,manifest[key],value))
      if(!originalFlow)blockers.push(`原Skill隐式默认将覆盖或补入${key}，请先将实际拟填值显式写入方案并核验来源`);
  if (route.error || !info) blockers.push('原Skill无法确定产品类目');
  const category = String(info?.catId || '');
  const cfg = info ? JSON.parse(fs.readFileSync(path.join(skill, 'categories', info.categoryDir, 'config.json'), 'utf8')) : {};
  const fields = manifest.fields || {};
  if(originalFlow){
    const content=require('./listing_completion.cjs').coverage(manifest,engine,cfg,context);
    blockers.push(...content.missing.map(key=>'原Skill完整内容缺项：'+key));
  }
  const pricing = manifest.pricing || {};
  if (!originalFlow&&(!pricing.unit || !pricing.source || !Array.isArray(pricing.tiers) || pricing.tiers.length !== 3 ||
      pricing.tiers.some(t => !(Number(t.qty) > 0 && Number(t.price) > 0)))) blockers.push('请确认有来源的销售单位及3档价格/MOQ，禁止套用默认估价');
  for (const [key, value] of Object.entries(engine.FIXED_VALUES)) {
    if (fields[key] && norm(fields[key]) !== norm(value)) blockers.push(`固定值冲突：${key}（原Skill会覆盖输入）`);
    if (!fields[key] && (key === 'origin_country' || key === 'origin_province')) blockers.push(`请确认原Skill固定产地字段：${key}`);
  }
  for (const key of cfg.required_fields || []) if (!fields[key]&&!(key==='net_weight'&&allowMissingNetWeight(context))) blockers.push(`当前类目必填：${key}`);
  const comparisons = [],warnings=[];
  if(allowMissingNetWeight(context))warnings.push(BLANK_NET_WEIGHT_NOTICE);
  if(!originalFlow&&!imageEvidence.liveVerified)warnings.push('图片证据适配器已接入；真实上传与保存分区仍须当次核验，未声明现场通过');
  if(originalFlow)warnings.push('复用原Skill本地图片与保存流程；后台草稿图片仍需最终检查，不要求独立CDN清单');
  const themeIssue=message=>(context.recruitmentMatchPolicy==='visual-reference'?warnings:blockers).push(message);
  for (const row of context.recruitment?.requirements || []) {
    if (row.kind === 'category') {
      const matched = row.expected?.map(String).includes(category);
      comparisons.push({name: row.name, expected: row.expected, actual: category, matched});
      if (!matched) themeIssue('原Skill自动类目与征品叶子类目不一致');
    } else if (row.kind === 'attribute') {
      const key = FIELD_ALIASES[norm(row.name).replace(/[-_:]/g,'')] || Object.keys(engine.FIELD_LABELS).find(k => norm(engine.FIELD_LABELS[k]) === norm(row.name));
      const actual = fields[key];
      const values = Array.isArray(actual) ? actual : String(actual || '').split(/[;,]/);
      const matched = Boolean(key && row.expected?.some(expected => values.some(v => norm(v) === norm(expected))));
      comparisons.push({name: row.name, key, fieldId: row.fieldId, expected: row.expected, actual, matched});
      if (!matched) themeIssue(`征品属性待核对：${row.name}`);
      if (!row.fieldId || !row.options?.length) {
        if(originalFlow)warnings.push(`征品字段由原Skill页面定位并回读：${row.name}`);
        else themeIssue(`征品字段/选项ID缺失：${row.name}`);
      }
    } else if (row.kind === 'range') {
      const tier = manifest.pricing?.tiers?.[0];
      const raw = row.key === 'price' ? tier?.price : manifest.pricing?.moq ?? tier?.qty;
      const value = Number(raw);
      const matched = raw !== undefined && Number.isFinite(value) && value >= 0 &&
        (row.minimum == null || value >= Number(row.minimum)) && (row.maximum == null || value <= Number(row.maximum));
      comparisons.push({name: row.name, actual: raw, matched});
      if (!matched) themeIssue(`征品价格/MOQ或单位待核对：${row.name}`);
    }
  }
  return {category, route, blockers: [...new Set(blockers)], warnings, comparisons, imageEvidence,
    recruitmentVerified:false};
}

async function main() {
  const [mode, rootArg, skillArg] = process.argv.slice(2);
  if (!['inspect','preflight', 'content', 'execute','readback','complete'].includes(mode)) throw Error('Invalid adapter mode');
  const root = path.resolve(rootArg), skill = path.resolve(skillArg);
  const manifestFile = path.join(root, 'manifest.json');
  const manifest = JSON.parse(fs.readFileSync(manifestFile, 'utf8'));
  const contextFile = path.join(root, 'listing-context.json');
  const context = fs.existsSync(contextFile) ? JSON.parse(fs.readFileSync(contextFile, 'utf8')) : {};
  if(!['inspect','readback'].includes(mode)&&allowMissingNetWeight(context)) {
    manifest.fields.net_weight='';
    if(Array.isArray(manifest.missing_required))manifest.missing_required=manifest.missing_required.filter(key=>key!=='net_weight');
    fs.writeFileSync(manifestFile,JSON.stringify(manifest,null,2));
  }
  if(mode==='inspect'){
    const {routeManifest,CATEGORY_MAP}=require(path.join(skill,'scripts/route_category.cjs'));
    const route=routeManifest(manifest),category=CATEGORY_MAP[route.category];
    if(!category)throw Error('原Skill无法识别类目');
    const categories=Object.fromEntries(Object.entries(CATEGORY_MAP).map(([key,info])=>[key,{...info,config:JSON.parse(fs.readFileSync(path.join(skill,'categories',info.categoryDir,'config.json'),'utf8'))}]));
    fs.writeFileSync(path.join(root,'skill-routing.json'),JSON.stringify({route,categories},null,2));return;
  }
  isolateSkillRuntime(root, skill);
  if (!['content','readback'].includes(mode)) {
    const check = preflight(manifest, context, skill);
    fs.writeFileSync(path.join(root, 'listing-preflight.json'), JSON.stringify(check, null, 2));
    if (check.blockers.length) throw Error(check.blockers.join('; '));
    if (mode === 'preflight') return;
  }
  // Keep original Skill sources immutable; all reports and generator temp files stay in this run.
  const reports = path.join(root, 'reports');
  fs.mkdirSync(reports, {recursive: true});
  const engine = require(path.join(skill, 'scripts/browser_runner.cjs'));
  if(mode==='complete'){
    const pre=preflight(manifest,context,skill);
    const cfg=JSON.parse(fs.readFileSync(path.join(skill,'categories',pre.route.category,'config.json'),'utf8'));
    await require('./listing_completion.cjs').complete(root,skill,manifest,context,engine,cfg);return;
  }
  if (mode === 'content') {
    const read=fs.promises.readFile;
    fs.promises.readFile=async function(file,...args){
      if(path.resolve(String(file))===manifestFile){
        const text=JSON.stringify(contentGenerationInput(manifest,context.listingMechanism==='original-skill-v1'?engine.FIXED_VALUES:{}));
        return args[0] ? text : Buffer.from(text);
      }
      return read.call(this,file,...args);
    };
    const profile=JSON.parse(fs.readFileSync(path.join(skill,'assets/_profile.json'),'utf8'));
    const write=fs.writeFileSync;
    fs.writeFileSync=function(file,data,...args) {
      if (String(file).endsWith('-fill-manifest.json')) {
        const parsed=JSON.parse(String(data));
        const manifest=Array.isArray(parsed) ? parsed[0] : parsed;
        materializeBusinessDefaults(manifest,profile,engine);
        manifest.skill_generated_suggestions=skillGeneratedSuggestions(manifest,skill,engine);
        finishContentGeneration(manifest,JSON.parse(fs.readFileSync(manifestFile,'utf8')).missing_required,context);
        if(context.listingMechanism==='original-skill-v1'){
          const route=context.categoryOverride?.category||require(path.join(skill,'scripts/route_category.cjs')).routeManifest(manifest).category;
          const cfg=JSON.parse(fs.readFileSync(path.join(skill,'categories',route,'config.json'),'utf8'));
          const coverage=require('./listing_completion.cjs').coverage(manifest,engine,cfg,context);
          write.call(fs,path.join(root,'listing-content-coverage.json'),JSON.stringify(coverage,null,2));
          manifest.missing_required=[...new Set([...manifest.missing_required,...coverage.missing])];
        }
        const auditFile=path.join(root,'reports',manifest.product_id+'-fill-content-audit.json');
        if(fs.existsSync(auditFile)){
          const audit=JSON.parse(fs.readFileSync(auditFile,'utf8'));
          audit.blockers=[...(audit.blockers||[]),...manifest.missing_required.map(key=>({key:'required_'+key,message:'原Skill生成后仍缺平台字段：'+key}))];
          if(audit.blockers.length)audit.status='blocked';
          write.call(fs,auditFile,JSON.stringify(audit,null,2));
        }
        data=JSON.stringify(parsed,null,2);
      }
      return write.call(this,file,data,...args);
    };
  }
  if (mode === 'execute'||mode==='readback') {
    const uploader = require(path.join(skill, 'scripts/upload_images.cjs'));
    const delivery = JSON.parse(fs.readFileSync(path.join(root, 'upload-map.json'), 'utf8'));
    const uploaded = [];
    const evidenceAdapter=require('./listing_image_evidence.cjs');
    const nativeEvidence=uploader.uploadEvidenceContractVersion===1&&typeof engine.readSavedImageSections==='function';
    const originalFlow=context.listingMechanism==='original-skill-v1';
    const originalUploads=new Set(),uploadProblems=[];
    let identity = null;
    async function assertIdentity(page) {
      const observed = await page.evaluate(() => {
        if(location.hostname!=='post.alibaba.com'||location.pathname!=='/product/publish.htm')return [];
        // The current publish shell exposes the shop owner separately from its staff user.
        const current=window.GPF_GLOBAL_STORE?.json?.models?.global;
        const owners=[current?.adminAliId,current?.value?.adminAliId]
          .filter(v=>typeof v==='string'||typeof v==='number').map(String);
        if(owners.length)return owners;
        const values = [document.querySelector('header [data-ali-id],.layout-hd [data-ali-id],#header [data-ali-id]')?.getAttribute('data-ali-id'),
          document.querySelector('header [data-member-id],.layout-hd [data-member-id],#header [data-member-id]')?.getAttribute('data-member-id'),
          window.__INITIAL_STATE__?.userInfo?.aliId, window.__INITIAL_STATE__?.userInfo?.memberId,
          window._page_config_?.aliId, window._config_?.aliId];
        return values.filter(v => typeof v === 'string' || typeof v === 'number').map(String);
      });
      if (!observed.length||!observed.every(value=>value===String(context.expectedAccount))) throw Error('实际发布页身份尚未核验或与目标店铺不同，已阻止写入');
      identity = {verified: true, time: new Date().toISOString()};
      if (!originalFlow) {
        const parameter = page.locator('input[type="checkbox"][value="110"], input[type="checkbox"][value="170"]');
        if (!await parameter.count()) throw Error('当前类目未找到参数图板块，m7去向需核对，已阻止填写');
      }
    }
    for (const name of ['fillConfiguredField', 'fillCustomAttributes', 'fillCompanyIntroAndFAQ', 'fillSellingPoints', 'saveDraft',
        'dismissFloatingOverlays','fillBottleCapacity','fillFlavor','fillLeadTime','clearLogistics','fillLogistics']) {
      const original = engine[name];
      engine[name] = async (page, ...args) => {
        await assertIdentity(page);
        if(name==='fillCompanyIntroAndFAQ'||name==='fillSellingPoints')await require('./listing_completion.cjs').ensureContentEditors(page,name==='fillSellingPoints'?'selling':'company');
        if(name==='saveDraft'&&originalFlow&&(originalUploads.size!==delivery.length||uploadProblems.length))throw Error('原Skill图片处理存在明确异常，未保存草稿');
        if (name === 'saveDraft' && !originalFlow && (uploaded.length !== delivery.length ||
            new Set(uploaded.map(row=>row.assetId)).size !== delivery.length ||
            delivery.some(entry=>uploaded.filter(row=>row.slot===entry.slot && row.exportHash===entry.exportHash).length!==1)))
          throw Error('保存前图片文件到asset映射不完整，已阻止保存');
        return original(page, ...args);
      };
    }
    const pricingModule=require(path.join(skill,'subskills/price-filler/scripts/fill_pricing_section.cjs'));
    const fillPricing=pricingModule.fillPricingSection;
    pricingModule.fillPricingSection=async(page,...args)=>{
      await assertIdentity(page);
      return fillPricing(page,...args);
    };
    async function uploadWithEvidence(page, files, execute,groupValue=null) {
      await assertIdentity(page);
      if(originalFlow){
        const warning=console.warn;
        console.warn=(...args)=>{uploadProblems.push('原Skill图片步骤警告');warning(...args);};
        try{
          await execute();
          for(const file of files){
            const entry=delivery.find(row=>path.resolve(root,row.file)===path.resolve(file));
            if(!entry||require('node:crypto').createHash('sha256').update(fs.readFileSync(file)).digest('hex')!==entry.exportHash)throw Error('原Skill本地图片与审核文件不一致');
            originalUploads.add(entry.slot);
          }
        }catch(error){uploadProblems.push('原Skill图片步骤失败');throw error;}
        finally{console.warn=warning;}
        return;
      }
      const response = nativeEvidence ? await execute() : await evidenceAdapter.createUploadEvidenceCapture(page,
        {root,delivery,groupValue}).run(files,execute);
      uploaded.push(...bindUploadEvidence(root, delivery, files, response));
      fs.writeFileSync(path.join(root, 'upload-evidence.json'), JSON.stringify(uploaded, null, 2));
    }
    const mainUpload = uploader.uploadMainImages;
    uploader.uploadMainImages = (page, files) => uploadWithEvidence(page, files, () => mainUpload(page, files));
    const detailUpload = uploader.uploadDetailImages;
    uploader.uploadDetailImages = async (page, groups) => {
      for (const group of groups){
        let actualGroup=null;
        for(const choice of uploader.detailValueCandidates(group)){
          const count=await page.locator(`input[type="checkbox"][value="${choice.value}"]`).count();
          if(count>1)throw Error('详情分区不唯一，已阻止上传');
          if(count===1){actualGroup=choice.value;break;}
        }
        if(actualGroup===null)throw Error('详情分区未定位，已阻止上传');
        await uploadWithEvidence(page, group.images, () => detailUpload(page, [group]),actualGroup);
      }
    };
    const verify = engine.verifySavedDraft;
    engine.verifySavedDraft = async (page, data, extra) => {
      const result = await verify(page, data, extra);
      await assertIdentity(page);
      const url = new URL(page.url());
      const draftId = url.searchParams.get('itemId') || url.searchParams.get('productId');
      const imageSections = originalFlow ? null : nativeEvidence ? await engine.readSavedImageSections(page) :
        await evidenceAdapter.readSavedImageSections(page,{expectedDraftId:draftId,delivery,uploaded});
      const observed=await readSavedListing(page,engine.FIELD_LABELS);
      const actualFields = actualFieldReadback(data.fields,observed.fields,engine.SKIP_KEYS,context);
      const pre = JSON.parse(fs.readFileSync(path.join(root, 'listing-preflight.json'), 'utf8'));
      const category = observed.category_id;
      const imagePositions={};
      const originalChecks=delivery.map(entry=>({slot:entry.slot,file:entry.file,exportHash:entry.exportHash,section:entry.section,index:(imagePositions[entry.section]=(imagePositions[entry.section]||0)+1)-1,uploadInvoked:originalUploads.has(entry.slot),reviewRequired:true,matched:false}));
      const receipt = {draft_id: draftId, draft_url: page.url(), store: context.store, published: false,
        actualAccountVerified: identity?.verified === true, category_id: category, fields: actualFields,
        acceptancePolicy:originalFlow?'original-skill-draft-review':'strict-image-evidence',
        image_review_required:originalFlow,image_readback_verified:!originalFlow,
        intentional_blank_fields:allowMissingNetWeight(context)?['net_weight']:[],
        warnings:allowMissingNetWeight(context)?[BLANK_NET_WEIGHT_NOTICE]:[],
        unfilled_fields:Object.keys(data.fields||{}).filter(key=>!engine.SKIP_KEYS.has(key)&&String(data.fields[key]??'').trim()===''),
        image_checks: mode==='readback'?JSON.parse(fs.readFileSync(path.join(root,'readback.json'),'utf8')).image_checks:
          originalFlow?originalChecks:verifyImageEvidence(delivery, uploaded, imageSections),
        themeComparisons: pre.comparisons, verifiedAt: new Date().toISOString()};
      fs.writeFileSync(path.join(root, mode==='readback'?'readback-refresh.json':'readback.json'), JSON.stringify(receipt, null, 2));
      return result;
    };
    if(mode==='readback'){
      if(!originalFlow)throw Error('只读恢复仅用于原Skill已有草稿');
      const target=JSON.parse(fs.readFileSync(path.join(root,'readback-target.json'),'utf8'));
      const targetUrl=new URL(target.draft_url);
      if(target.product!==context.product||target.revision!==context.revision||target.store!==context.store||
          targetUrl.origin!=='https://post.alibaba.com'||targetUrl.pathname!=='/product/publish.htm'||
          targetUrl.searchParams.get('itemId')!==String(target.draft_id)||!/^\d+$/.test(String(target.draft_id)))throw Error('只读草稿目标不匹配');
      const originalReport=JSON.parse(fs.readFileSync(path.join(reports,'run-all-report.json'),'utf8'));
      const browser=await require('playwright').chromium.connectOverCDP('http://127.0.0.1:9322');
      let page;
      try{
        page=await browser.contexts()[0].newPage();
        await page.goto(target.draft_url,{waitUntil:'domcontentloaded',timeout:60000});
        await page.waitForFunction(()=>!!window.GPF_GLOBAL_STORE?.json?.models?.global?.adminAliId,null,{timeout:30000});
        await assertIdentity(page);
        console.log('只读核验已有草稿；未调用填写、上传或保存');
        const result=await engine.verifySavedDraft(page,manifest,{company_intro:manifest.company_intro,price:originalReport.price});
        const refreshed=JSON.parse(fs.readFileSync(path.join(root,'readback-refresh.json'),'utf8'));
        if(refreshed.draft_id!==String(target.draft_id))throw Error('只读回读返回其它草稿');
        fs.writeFileSync(path.join(root,'readback-refresh-report.json'),JSON.stringify({...originalReport,
          status:result.status==='verified'?'completed':'verification_failed',post_save_verification:result,
          readOnlyRefresh:true,refreshedAt:new Date().toISOString()},null,2));
        console.log('只读草稿回读：'+result.status);
      }finally{
        if(page)await page.close().catch(()=>{});
        await browser.close();
      }
      return;
    }
    // Prevent the original content normalization from silently changing reviewed field values.
    const write = fs.writeFileSync;
    fs.writeFileSync = function(file, data, ...args) {
      if (String(file).endsWith('-fill-manifest.json')) {
        const nextRaw = JSON.parse(String(data)), next = Array.isArray(nextRaw) ? nextRaw[0] : nextRaw;
        assertReviewedContent(manifest,next);
      }
      return write.call(this, file, data, ...args);
    };
  }
  process.argv = [process.execPath, path.join(skill, 'scripts/run_all.cjs'), '--manifest', manifestFile,
    '--image-dir', path.join(root, 'upload'), '--screenshots', reports,
    ...originalSkillRuntimeArgs(context),
    ...(context.categoryOverride?['--category',path.join(skill,'categories',context.categoryOverride.category),'--force-category','1','--url','https://post.alibaba.com/product/publish.htm?catId='+context.categoryOverride.categoryId]:[]),
    ...(mode === 'content' ? ['--content-only', '1'] : [])];
  require(path.join(skill, 'scripts/run_all.cjs'));
}

module.exports = {preflight, readbackMatches, FIELD_ALIASES, bindUploadEvidence, verifyImageEvidence, assertReviewedContent,
  runtimePath, imageEvidenceSupport, materializeBusinessDefaults, effectiveBusinessValues,
  contentGenerationInput,finishContentGeneration,skillGeneratedSuggestions,
  allowMissingNetWeight,originalSkillRuntimeArgs,actualFieldReadback,readSavedListing};
if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
