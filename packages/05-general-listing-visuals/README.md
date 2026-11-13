# 通用上品与商品视觉 Skill（阿里巴巴国际站）

## 先看结构与协作思路

- [文件级思路说明](docs/思路与结构说明.md)：实际目录、四个sub skill、两侧references逐文件分工、输入输出和实现边界。
- [HTML思路说明](通用Skill思路与结构说明.html)：下载本地打开；原使用说明地址也更新为同一份结构说明。
- [模板交付与确认存档](docs/模板交付与确认存档.md)：使用上品Skill时如何直接交模板给使用者填写保存，确认后如何入参考库。

## 下载

- [单独上品Skill包](阿里巴巴国际站通用上品Skill.zip)
- [单独商品生图Skill：Codex原生版](阿里巴巴国际站通用商品生图Skill.zip)
- [生图填写模板](生图资料文件夹模板.zip)
- [原生生图说明](docs/原生商品生图Skill-发送说明.txt)
- [通用Skill合集](通用上品与商品视觉Skills.zip)
- [空白资料文件夹模板](资料准备文件夹模板.zip)

## 实际模块入口

| 主控／子模块 | 职责与实现 |
| --- | --- |
| [上品主控](skills/b2b-listing-assistant/SKILL.md) | 直接导出填写模板、统一收集与确认、实际保存公司参考、调度子任务 |
| [标题子模块](skills/b2b-listing-assistant/subskills/title-scout/SKILL.md) | Agent标题候选与来源／风险规则 |
| [卖点子模块](skills/b2b-listing-assistant/subskills/selling-points/SKILL.md) | Agent逐条文案与证据规则 |
| [价格子模块](skills/b2b-listing-assistant/subskills/price-filler/SKILL.md) | 当前SKU确认报价的本地计划校验，无旧固定价与默认折扣 |
| [图片交接子模块](skills/b2b-listing-assistant/subskills/image-upload/SKILL.md) | 文件、顺序、模块清单检查，无通用浏览器上传器 |
| [商品视觉](skills/b2b-product-visuals/SKILL.md) | 单一Codex原生生成／编辑入口，支持真实图、命名产品库、图中文字名称与明确新概念；无脚本和旧版板块 |

## 使用入口

首次、换公司或尚无确认配置时，上品主控运行init_workspace.py，直接给出独立填写目录、模板ZIP与说明链接。使用者按说明放资料、填写并保存，再交回。Agent读完后集中核对，用户确认摘要后由save_profile.py保存并读回公司参考。已有有效配置优先复用，避免重复填写。

通用包只附规则、空白模板、占位结构和技术约束，不附具体公司、产品、类目、报价或演练数据。实际公司资料在使用后才形成，后续分享须排除。

## 商品视觉原生版

独立生图包只有SKILL、六份通用reference和空白TXT／ZIP模板。没有Python、Node、SDK、API配置、HTML/CSS渲染、旧公司／产品／类目素材或固定旧板块。公司品牌、规格与B端事实由使用者提供后才形成。

新作须有明确产品描述并标概念；有实拍则实际读图后用原生图像编辑，产品库先建立对应关系与本次处理范围。主图清晰呈现产品，详情按采购决策组织真实信息，不要求固定图量或原行业版式。

## 验证与边界

原生版已独立检查所有源码与模板ZIP，并进行五种场景文字推演；尚未实际生成真实商品图片。原生能力取决于当前Codex会话工具，不能由Skill本身提供；工具缺失不切换外部接口。[当前检查范围](docs/Subagent实验检查与修复报告.md)。

上品通用浏览器填写、上传、草稿保存与回读仍需现场适配。旧视觉代码与模板已从当前视觉源码移出，不将过去的脚本测试认作当前原生成品验收。
