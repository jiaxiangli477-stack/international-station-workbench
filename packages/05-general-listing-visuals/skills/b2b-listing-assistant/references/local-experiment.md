# 本地实验：输入、属性准备与边界

1. Agent按资料模板一次收集资料，实际读取原文件。公司事实、商品事实、页面字段来源和冲突分别记录。没有通用原文件解析器，PDF/Excel/图片识别由当前Agent与可用文件工具完成；本地脚本不替代这一步。
2. Agent整理标准输入：root product_id指定本次SKU；company/product/pricing各项用value/status/source记录，product与pricing项必须带相同product_id，冲突项标conflict:true。company_profile_confirmed只有用户确认摘要后设true。无来源或推测值不得改成confirmed。
3. prepare.py只做基础字段和证据标记复核，输出CSV带状态，不能整表直接作为执行值。review.json保留来源记录；路径或来源文本存在不证明材料真实已读。
4. 进一步输入category_schema（来自真实发布页）和attributes。category_schema需包含publishing_url、category_id或category_path、source、observed_at、coverage=reviewed_for_product以及fields。每个field有唯一key、label、control_type、布尔required；下拉另需observed_options、options_evidence和布尔allows_custom_value，允许自定义时须有custom_value_evidence。联动字段需明确active与condition_evidence。字段定义可额外保留section、unit、limits、depends_on等证据。
5. attributes按key提供{value,status,source,product_id}。由Agent把产品、交易、生成后经确认的内容对应到实际字段；未知字段不擅自写入。自定义属性、价格与交期同样要映射到当前页面字段，不能仅因为在pricing中出现就认为build_plan已经处理过。
6. 运行python scripts/build_plan.py --input <完整输入.json> --output <D/E盘listing-plan.json>。无页面配置、必填状态不明、必填缺值、来源标记无效、SKU不一致、未知选项、超限数值等会阻断；可选不适用项列明原因。支持text/textarea/number/select/multiselect/autocomplete/tags，其他控件明确阻断，待现场适配。
7. 标题／卖点子Skill读取确认资料生成候选。草稿不要直接升级为confirmed；用户复核后标明来源再用于字段计划。当前子Skill是Agent工作规则，不含原包生成器移植。
8. 按image-handoff.md整理成品并生成图片清单，复核图片实际内容和平台要求。向用户展示字段、文件、来源、缺口和未验证项。
9. 之后才进入当前类目的现场填写、真实上传和授权草稿保存／回读测试。当前新包没有通用的浏览器填写、上传或发布程序；listing-plan不是旧版manifest的直接兼容替代，不能直接交旧run_all执行。

本地输出状态：needs_input或blocked为有缺口；ready_for_review为基础复核；ready_for_local_review为本地字段或文件计划通过。都不代表平台已操作、商品可发布或视觉内容已通过。publishable/uploaded一直为false。只有真实页面最终结果能证明上传、保存或发布。

证据核验的边界：脚本检查结构、声明来源、字段与SKU一致性，不联网核验来源存在性、证书真实性或人工确认的合法性。Agent需先实际读取、比对并取得所需用户确认，保存来源与授权。

重要：build_plan.py读取包含company、product、attributes和category_schema的完整输入，不读取prepare输出的review.json作为下一步输入；review.json只供基础审查。limits仅实现min/max/max_length，其他限制键会阻断，需要先补充适配或人工核验，不视为通过。
