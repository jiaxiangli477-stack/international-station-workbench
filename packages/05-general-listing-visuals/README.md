# 通用上品与商品视觉 Skill（阿里巴巴国际站）

## 先看结构与协作思路

- [文件级思路说明](docs/思路与结构说明.md)：实际目录、四个sub skill、两侧references逐文件分工、输入输出和实现边界。
- [HTML思路说明](通用Skill思路与结构说明.html)：下载本地打开；原使用说明地址也更新为同一份结构说明。
- [模板交付与确认存档](docs/模板交付与确认存档.md)：使用上品Skill时如何直接交模板给使用者填写保存，确认后如何入参考库。

## 下载

- [通用Skill完整包](通用上品与商品视觉Skills.zip)
- [空白资料文件夹模板](资料准备文件夹模板.zip)

## 实际模块入口

| 主控／子模块 | 职责与实现 |
| --- | --- |
| [上品主控](skills/b2b-listing-assistant/SKILL.md) | 直接导出填写模板、统一收集与确认、实际保存公司参考、调度子任务 |
| [标题子模块](skills/b2b-listing-assistant/subskills/title-scout/SKILL.md) | Agent标题候选与来源／风险规则 |
| [卖点子模块](skills/b2b-listing-assistant/subskills/selling-points/SKILL.md) | Agent逐条文案与证据规则 |
| [价格子模块](skills/b2b-listing-assistant/subskills/price-filler/SKILL.md) | 当前SKU确认报价的本地计划校验，无旧固定价与默认折扣 |
| [图片交接子模块](skills/b2b-listing-assistant/subskills/image-upload/SKILL.md) | 文件、顺序、模块清单检查，无通用浏览器上传器 |
| [商品视觉](skills/b2b-product-visuals/SKILL.md) | 品牌、主图、详情、场景、文字和质检按reference分流 |

## 使用入口

首次、换公司或尚无确认配置时，上品主控运行init_workspace.py，直接给出独立填写目录、模板ZIP与说明链接。使用者按说明放资料、填写并保存，再交回。Agent读完后集中核对，用户确认摘要后由save_profile.py保存并读回公司参考。已有有效配置优先复用，避免重复填写。

通用包只附规则、空白模板、占位结构和技术约束，不附具体公司、产品、类目、报价或演练数据。实际公司资料在使用后才形成，后续分享须排除。

## 验证与边界

新增11项模板／存档／价格测试和既有28项本地回归通过，独立审查者实际复核导出、存档、价格及入口引用。[检查摘要](docs/Subagent实验检查与修复报告.md)。

尚未完成通用真实页面填写、上传、草稿保存与回读，以及完整视觉模板和批量制作迁移。子Skill或reference存在不代表其自动化程序全部存在，本地ready也不表示平台已操作。
