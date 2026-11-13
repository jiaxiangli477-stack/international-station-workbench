---
name: b2b-alibaba-price-filler
description: Prepare and validate current-SKU Alibaba.com price tiers and MOQ from explicitly confirmed quotations, without legacy category base prices or automatic browser writes.
---

# 通用价格与MOQ子模块

主控准备交易字段前调用。先读references/pricing-rules.md；只读取当前产品报价及确认条件，不沿用旧公司基准价、折扣或类目默认MOQ。

内部输入为product_id及pricing.moq/currency/unit/tiers，每项使用value/status/source/product_id；tiers.value是按数量起点排列的min_quantity和unit_price清单。空白格式见references/quote-input.template.json，由Agent填，用户提交现成报价表即可。

运行scripts/prepare_pricing.py --input <完整输入路径> --output <D/E盘价格计划.json>。本地工具校验同SKU来源标记、数量、价格有限值、阶梯顺序、币种格式与单位。缺报价就阻断，不自动计算；MOQ与首档数量不同或价格随数量升高时给needs_review，不擅自改动。

把计划、来源、待确认项交主控；主控再按已核实的当前页面交易结构映射和操作。filled和publishable始终为false。没有实现通用浏览器填价、保存或发布，也没有照搬原price_calc的固定业务算法。
