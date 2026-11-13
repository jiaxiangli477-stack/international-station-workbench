---
name: b2b-alibaba-image-handoff
description: Validate and hand off one product's confirmed main and detail images with explicit current-page module mapping; this entry does not implement automatic Alibaba uploads.
---

# 图片交接与上传前检查子模块

主控在视觉成品确认后调用。先读../../references/image-handoff.md和references/upload-gates.md。

输入为当前SKU、确认成品目录、detail-map.json及当前页面图片模块证据。调用主Skill的scripts/image_inventory.py检查名称、顺序、格式、完整性与映射；输出文件清单、哈希、错误及视觉／身份待核验状态。

将结果交主控与视觉Skill复核。不得因setInputFiles、固定等待或日志“完成”就声称上传成功；没有真实页面执行器时输出待适配，不调用旧包有缺陷的上传脚本。

本子模块实现了工作规则和对已有本地检查器的调度，不包含浏览器上传器。真实上传前应确认字段与模块，上传后核对预览数量、文件顺序、错误提示和保存后结果。
