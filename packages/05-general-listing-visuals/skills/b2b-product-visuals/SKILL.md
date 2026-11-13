---
name: b2b-product-visuals
description: Create generic Alibaba.com B2B product main and detail images with Codex's available native image-generation/editing tool. Accept real photos, named product folders, names visible in photos, or an explicitly requested new concept. Collect facts once, identify each product, plan buyer-facing content, generate and review without bundled scripts or company/category presets.
---

# 通用B端商品图片｜Codex原生生图版

## 唯一出图路径与边界

只调用当前Codex会话实际提供的原生图像生成／编辑工具。工具可能显示为image_gen或imagegen，按当前工具说明调用，不固定模型版本或假定所有账户都可用。这里不包含Python、Node、SDK、API密钥、HTML/CSS渲染、固定行业板块、旧素材或外部生图接口。

用户给实物图时以真实产品图生图／编辑；明确要求新作且无实物图时可按确认描述做新概念图，必须说明不是已存在实物。工具不可用就说明阻塞，仍可整理索引和提示词；不切API、不跑旧脚本，也不能将提示词交付说成图片已生成。

## 第一次：直接给填写模板，已有资料不重复收

读references/intake.md。首次、新公司或资料不足时，直接提供当前Skill内assets/产品资料文件夹模板.zip的真实文件链接与说明，告诉使用者解压到独立工作区、填写和放资料后保存。可用宿主文件工具复制独立副本，不运行打包脚本；不要让使用者自己找路径或编辑母版。

使用者也可以直接发送图片或产品库路径，不强制先填表。一次说明需要的身份／事实／素材／输出要求，读完统一反馈缺口。平台固定为阿里巴巴国际站，不问平台或市场。已知且确认的信息不重复问。

## 可接受的输入方式

- 一张或多张真实产品图：先实际查看，核对是否同款及需保留细节。
- 产品资料文件夹：名称、子目录或清单已标产品名，按references/product-library.md建立映射。
- 图片里有产品名称：实际读图中文字，结合文件名和资料核对；识别不清或冲突的项集中请确认，不假装已识别。
- 用户明确要求新作：有确认的产品／外观描述就生成概念；只有风格参考时不能推断产品事实。

图片库模式先建立产品索引和文件对应关系，再对选定产品制作；不能把一张产品图用于另一款。所有输入图标注角色：真实编辑对象、结构／标签补充、风格参考、其他参考。具体看图与工具使用读references/native-image-generation.md。

## 工作顺序与参考路由

1. 接收资料：references/intake.md；模板只是收集说明，不是业务证据。
2. 识别与映射：references/product-library.md；产出产品索引、对应文件、识别来源、冲突与待确认项。
3. B端内容和画面规划：references/b2b-planning.md；先讲买家需要判断什么，再选图文形式。不复用原公司／原类目的固定面板或布局。
4. 统一原生生图／编辑：references/native-image-generation.md；使用真实可用工具，每个目标图明确SKU、输入角色、要保留的事实和要改变的内容。
5. 看图复核与交付：references/review-and-delivery.md；实际核对产品身份、结构、文字、证据及清晰度后保存，不用“模型应该没改”代替检查。
6. 公司资料复用：references/company-memory.md；用户确认后才在自己的授权环境保存专属参考。通用公开包永远不带具体主体、产品、类目、价格或素材。

## 最重要的B端原则

图要帮助采购者判断：商品是什么、规格是否合适、有什么真实依据、怎样选择与合作。先给出清晰产品和决策信息，少堆形容词；材质、性能、认证、定制、MOQ、交期和产能只在真实且适用时呈现。没有证据的工厂、客户、资质和评价主题不启用。

主图与详情页按当前产品、用户要求和实际页面限制规划，不强制固定张数或旧模块顺序。原始图可保留原名，确认的成品再按交接规范命名。生成图、概念图、看过但未核实的图都不能被说成实物事实或已经上架。
