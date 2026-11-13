---
name: b2b-alibaba-title-scout
description: Generate and review Alibaba.com product title candidates from confirmed product facts and current category page limits; optional existing titles or keywords serve only as reference.
---

# 通用标题子模块

由上品主控在公司和产品事实确认后调用，不单独重复向使用者索取整套资料。读取公司品牌、产品身份和该类目实际页面规则，以及07目录中选填的旧标题／关键词／禁用词。

原包的标题模块负责 fields.product_name，本模块延续标题与属性分工；不沿用旧公司品牌、成分／剂型模板、固定行业词和默认认证。

根据产品类目及真实资料给出3～5个自然英文候选和推荐理由。先保证产品是什么、核心规格能被识别；品牌、材质、型号、结构、用途等只在有依据且适用时使用。缺少关键词或旧标题不阻断生成；如果产品身份本身不明确，集中反馈缺口，不硬编。

按当前发布页限制核对字符数、风险词和属性一致性，不以凑满字数为目标。服务词是否适合由产品与实际规则决定，不默认堆入OEM／ODM或把贸易公司写成制造商。竞品标题与用户关键词不是事实证明，禁止照抄或引入无证据的性能、认证与效果。

交付候选、字符数、已使用的事实来源、缺失项和风险说明，推荐一条供用户复核；事实不足时草稿标记待确认。名称确认、页面实际填入及保存状态分别记录。本子模块为Agent工作指令，尚未移植原包的自动生成和清洗脚本。

开始当前子任务前读取 `references/title-rules.md`，按其输入、审查和交接格式返回主控。
