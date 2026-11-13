---
name: b2b-listing-assistant
description: Configure Alibaba.com listing workflows for a new company and product category. Send one complete onboarding checklist for the category, publishing-page evidence and company/product materials required by the original modules; persist confirmed company references before execution.
---

# 通用 B2B 上品助手

## 新类目入口：页面结构优先

首次提供 `assets/intake-folder-template/` 的资料文件夹模板，并按 `references/company-onboarding.md` 一次性列出类目、发布页 URL 与截图、公司、产品、交易和视觉资料准备清单，不逐项等待用户回复。内部先核实 `references/category-page-intake.md` 要求的真实字段、必填项、下拉选项与联动，再匹配已收到的资料。可直接读取真实页面时自行核查，不重复索取截图。不能仅凭类目名称推断字段。

## 先建立当前公司的使用配置

平台固定为阿里巴巴国际站，不询问平台或市场。以原包实际模块为依据一次性发完整准备清单，收到后统一读取和核对；先汇总已取得、缺少、不适用和冲突项，确有缺口时集中反馈一张补充表，避免零碎追问。具体产品字段由真实类目页面决定，没有的能力或素材不补造。

已有公司资料时先确认当前公司与资料版本，读取对应目录，复用仍适用的内容；只补变化项。用户确认整理摘要后，将资料依照 `references/company-profile.template.md` 保存到本 Skill 的 `references/companies/<公司标识>/`，按需生成 company.md、category-rules.md、business-rules.md、visual-guide.md、sources.md 和 readiness.md。具体产品放 `products/<产品标识>.md`，避免商品事实混入公司通用能力。文件职责和启用条件见 onboarding。当前流程允许按用户授权保存必要公司资料，不记录密码、Cookie、Token或客户隐私。不同公司分别存放，保留来源、确认日期、适用范围和未知项。原始附件保存在用户允许的 D/E 目录，参考中记录路径与授权，不复制无关或敏感材料。

另一套通用商品视觉 Skill 如有同主体的已确认资料，先核对来源、版本和本次适用性；在现有授权范围内复用必要资料并记录来源，信息有变化时让用户确认后更新。没有主体匹配证据不得混用。

## 资料确认后的工作流

1. 读取公司配置及 `references/product-evidence.md`，按当前类目建立字段、单位、来源及适用范围。每项值标记 confirmed / inferred / missing / blocked。无型号、无需认证或不存在某字段的产品，按实际情况记录不适用，不编造也不强求。
2. 用 `references/input.example.json` 表达证据数据。`scripts/prepare.py --input <路径> --output <D/E盘目录>` 输出 review.json / review.csv，只有有来源的 confirmed 值进入确认清单。`ready_for_review` 只表示基础本地复核条件满足，不等于公司配置已完备或商品可以发布；实际启用按 readiness.md 检查。
3. 先确认真实国际站类目和页面字段，再整理商品名称、属性、交易信息与说明。价格、MOQ、库存、交期、物流尺寸等只使用本产品适用且已确认的信息，不从模板或相似产品补造。
4. 核对规格、交易信息、公司能力及适用条件的一致性。只针对当前产品可能涉及的规则查询当前一手来源，不默认任何行业证书必需或已持有。
5. 当前任务获授权且平台工具可用时，观察真实页面，按控件依赖填写、逐项回读。页面字段、选择器和类目差异需要现场验证；旧行业脚本不能直接视为新类目适配器。执行失败记录原因，停止受影响的步骤，不把资料整理说成页面填写成功。
6. 报告资料已确认、页面实际已填、未填、失败和待人工处理项。保存、提交及正式发布按当前任务授权执行，核验最终状态后再报告结果。

## 实验前的字段计划

先读 `references/local-experiment.md`，用build_plan.py校验真实类目字段与attributes，用image_inventory.py检查成品清单。prepare.py只做基础复核，不能代替前述检查；本地计划仍不具备平台执行能力。

## 标题与卖点分工

资料确认后生成商品标题时读取 `subskills/title-scout/SKILL.md`，生成卖点时读取 `subskills/selling-points/SKILL.md`。两者由主控传递同一份确认资料和当前页面规则；旧标题、关键词和现成文案只选填参考，不要求用户先写成品。先给候选和来源供复核，再按授权处理页面。这两项是Agent子模块规则，原包生成器和自动清洗器仍未完整迁移。

## 能力范围

本 Skill 提供可复用的资料收集、公司配置与 Agent 工作流程，以及本地资料复核脚本。旧工具的自动填表、自动存草稿、上传和批量发布代码没有完成通用迁移；国际站页面操作依赖当前真实可用工具与现场适配。批量执行前先验证一款产品。

## 成品图片交接

制作完成后按 `references/image-handoff.md` 交付单SKU成品目录和明确模块映射。文件命名与检查不替代实际看图或页面上传核验；原始素材不强制改名。
