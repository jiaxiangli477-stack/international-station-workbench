# 调用入口：直接给填写模板，再保存确认资料

## 首次／换公司／尚无确认配置

Agent读取上品SKILL后，第一个可执行动作是运行 scripts/init_workspace.py --output <D/E盘本次独立填写目录>。它复制assets/intake-folder-template母版并生成ZIP，返回folder、zip、guide三个实际路径。已有目录或ZIP不覆盖，另选新的工作目录。

必须把生成的模板ZIP和使用说明具体链接直接给使用者，并说明：解压后按每个目录的TXT说明放资料、填写根部状态说明、保存副本，完成后交整个文件夹／ZIP或给出授权路径。不要仅说“请提供资料”，也不让使用者自己寻找Skill内部assets路径。母版不可直接作为用户填写目录。

Agent支持创建和链接本地文件时就实际生成；不能执行时，明确当前能力限制，并给已随包提供的真实模板文件或目录，不能谎称已创建。已有公司配置可直接读取复用；用户要换公司或重新收集时再给新副本。

## 使用者填写与保存

使用者只放现成文件和填写TXT，不需要写JSON。没有的标待补，不适用的标明；不要求先做标题或成品图片。工作区保存的是原始输入与状态，不能自动成为确认事实。

## Agent读取、集中核对、确认后入参考库

核实页面结构后对应产品资料；整理公司、类目引用、业务、视觉、来源、就绪范围和单产品记录，给摘要与集中缺口表。确认前只保持草稿状态。

收到用户对摘要的明确确认后，Agent组织内部confirmed-profile输入，运行 scripts/save_profile.py --input <路径>。输入包括company_id、安全的产品标识、confirmation(user_confirmed=true、confirmed_at、source)、documents(company/sources/readiness必需，其他按需)、products(按需)。用户不需要手填这个内部对象。

脚本实际在当前Skill的references/companies/<company_id>/写入并读回公司参考；已有公司目录不覆盖，更新必须先核对版本与差异，并依用户确认更新。该脚本保存的是Agent整理过的参考文字，不会自动解析任意附件，也不能代替用户确认或证明输入真实。

两套Skill共享已确认资料时记录同一主体与版本；只传必要资料，不自动复制到另一公司。再分享通用包必须排除所有companies和实际categories记录，只带规则及空白模板。
