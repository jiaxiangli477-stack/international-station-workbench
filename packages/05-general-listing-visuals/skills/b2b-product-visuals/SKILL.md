---
name: b2b-product-visuals
description: Configure Alibaba.com product visuals for a new company and category. Send one complete onboarding checklist covering category-page evidence, brand rules and real assets required by the original modules, persisting confirmed company references before creation.
---

# 通用 B2B 商品视觉

## 新类目入口：页面结构优先

首次提供 `assets/intake-folder-template/` 的资料文件夹模板，并按 `references/company-onboarding.md` 一次性列出类目、发布页 URL 与截图、公司、产品、交易和视觉资料准备清单，不逐项等待用户回复。内部先核实 `references/category-page-intake.md` 要求的真实字段、必填项、下拉选项与联动，再匹配已收到的资料。可直接读取真实页面时自行核查，不重复索取截图。不能仅凭类目名称推断字段。

## 首次使用先收集资料

平台固定为阿里巴巴国际站，不询问平台或市场。以原包实际模块为依据一次性发完整准备清单，收到后统一读取和核对；先汇总已取得、缺少、不适用和冲突项，确有缺口时集中反馈一张补充表，避免零碎追问。具体产品字段由真实类目页面决定，没有的能力或素材不补造。

确认摘要后，把公司事实、视觉规则、来源和启用检查记录放进本 Skill 的 `references/companies/<公司标识>/`；使用 `references/company-profile.template.md`，按需创建 company.md、category-rules.md、visual-guide.md、sources.md、readiness.md，产品独立记录。不同公司分别存放。真实素材保存在获授权的 D/E 目录并记录路径。未确认事实、设计建议和真实公司能力分开标记，不存账号、密钥和客户隐私。已有上品助手的同主体参考资料时，在现有授权范围内复用仍有效的必要资料并记录版本，不让用户重复提供已有信息。

## 确认资料后制作

1. 读取已确认公司配置和具体产品资料，核对产品身份、外观、规格与素材权利；实物商品优先使用真实照片，概念商品须明确标记，不把生成图当真实产品证明。缺资料时按 readiness.md 只暂停依赖它的部分。
2. 按类目与任务规划主图、细节、结构或使用示意、应用场景和采购说明，数量和版式按需要决定。所有规格、认证、兼容性及服务表述都要有适用证据。示意图说明其性质。
3. `scripts/render.py --photo <照片> --output <D/E盘PNG>` 可制作 1000×1000 中性预览，保持照片和纵横比；需要 Pillow，仅为基础排版工具。真实产品结构、标签及关键细节不得被任意改动。
4. 需要 AI 生成或编辑图片时使用当前可用的图像工具，遵守素材使用、外部处理和费用授权。生成后逐项对照真实产品，不修改关键结构和标识，不虚构工厂、证书、客户或测试结果。
5. 按实际平台要求逐张检查尺寸、清晰度、可读性、产品一致性、事实来源、权利和版式，交付图片、素材说明和未解决项。公开上传或发布遵循具体授权。

## 能力范围

本 Skill 提供资料收集、公司配置、视觉制作与检查的 Agent 工作流程，和真实照片基础预览脚本。旧包的完整模板、批量场景生成、抠图和自动视觉质检未完成通用迁移；不得将基础预览说成全部能力已适配。

## 成品图片交接

制作完成后按 `references/image-handoff.md` 交付单SKU成品目录和明确模块映射。文件命名与检查不替代实际看图或页面上传核验；原始素材不强制改名。
