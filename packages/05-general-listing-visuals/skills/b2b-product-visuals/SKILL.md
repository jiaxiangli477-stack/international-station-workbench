---
name: b2b-product-visuals
description: Configure Alibaba.com product visuals for a new company and category. Issue a blank intake template directly on unconfigured use, persist confirmed references, then route brand, main-image, detail-page, scene, copy and review work from evidence-backed company and product material.
---

# 阿里巴巴国际站通用商品视觉

## 首次直接给模板，不让使用者自己找文件

无当前公司确认配置时，读取references/template-delivery.md，运行scripts/init_workspace.py --output <D/E盘独立填写目录>，直接给出模板ZIP、填写目录和说明链接，使用者填写、放资料并保存副本。读取全部材料后集中核对，用户确认摘要后由scripts/save_profile.py保存到本Skill公司专属参考。已有同主体有效配置先复用，不重复索取。

与配套上品主控共同使用时，由上品主控交模板和统一收资料；视觉分支只读取必要的同主体同版本确认资料，不再给一套重复问卷。平台固定为阿里巴巴国际站，不问平台和市场。

## 参考文件是具体工作规则，不是独立sub skill

本Skill没有额外的subskills目录。原视觉包通过references按场景分流，本版保留这一结构；以下均是本Skill执行时按需读取的规则：

| 当前工作 | 读取 | 输入 → 输出 |
| --- | --- | --- |
| 一次收资料与公司确认 | references/company-onboarding.md、template-delivery.md、company-profile.template.md | 已有材料 → 索引、集中缺口、用户确认及专属资料 |
| 页面结构与限制 | references/category-page-intake.md、category-fields.template.json | 实际页面证据 → 类目与图片模块规则 |
| 品牌配置 | references/brand-tokens.md | 授权Logo、已有规范、确认偏好 → 本公司视觉规则与待审方案 |
| 主图规划 | references/main-images.md | 同SKU事实、照片与视觉规则 → 逐图计划及制作需求 |
| 详情页规划 | references/detail-page.md | 产品与适用公司证据 → 模块、文案、图稿与页面对应关系 |
| 场景和真实产品处理 | references/scene-swap.md | 真实／概念／参考素材与改动范围 → 制作方法及保真检查项 |
| 文字与事实审查 | references/copy-compliance.md | 图中文字与来源 → 风险和修正项 |
| 逐图质检 | references/visual-review.md | 实际导出图、原照片和规则 → 通过、失败、待核验项 |
| 交接上品主控 | references/image-handoff.md | 确认成品＋当前页面模块证据 → 单SKU目录、detail-map和状态 |

这里保留方法规则，但不附旧公司Logo、配色、证书、工厂、商品照片或历史参数。用户确认资料后才把具体值放进references/companies/<公司标识>/，实际类目配置同样核实后再建。准备模板本身不是证据。

## 与上品和内容子模块的协作

上品主控整理的公司和SKU事实是共同输入。标题、卖点草稿可供图片组织信息参考，但未确认草稿不是产品事实；视觉方案也不能给属性增加无依据参数。两分支的图文、规格、包装和交易必须一致。

没有事实或素材的工厂、资质、客户和评价主题不启用；真实商品使用授权实拍并保留关键结构，概念图明确标注，参考作品不当实物证明。生成和编辑使用当前真实可用的图像工具，遵守资料与费用授权。

最终成品与原图、草稿分开存；按image-handoff.md命名并提供明确模块映射。主控的image-upload子模块检查文件清单后，还要实际核验图片内容和真实上传结果。

## 已有程序与尚缺能力

scripts/init_workspace.py和save_profile.py处理模板交付及确认参考存档。scripts/render.py只能将真实照片等比例排成中性预览，不是完整主图或详情页渲染器。

brand-tokens、main-images、detail-page等是可供Agent执行的规则，原包固定模板、批量场景生成、抠图、文字锁定及自动质检程序未完整迁移。不能将新增参考文件的存在说成这些程序都已经实现。
