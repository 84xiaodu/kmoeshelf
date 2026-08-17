# Kmoe 自动订阅服务许可与第三方声明设计

日期：2026-08-17  
状态：已确认方案，等待书面规格复核

## 1. 目标

为首版发布物补充清晰、可随源码和 Python 分发包一起传播的许可信息：项目自身采用 MIT License，版权归 `84xiaodu`；同时对设计与实现期间参考的两个 MIT 项目保留明确的作者归属和许可文本。

## 2. 项目许可

根目录新增 `LICENSE`，使用标准 MIT License 全文，并写明：

```text
Copyright (c) 2026 84xiaodu
```

该许可证只授权本项目中由项目作者拥有权利的代码和文档，不授权 Kmoe 网站、商标、漫画内容、用户下载内容或其他第三方材料。

`pyproject.toml` 声明项目采用 MIT License，并把根目录的许可文件作为项目许可证来源。构建 Python wheel 和源码包时必须包含该许可文件。

## 3. 第三方声明

根目录新增 `THIRD_PARTY_NOTICES.md`，包含以下两项：

1. `holdjun/kmoe`，研究基线提交 `211fb7211f2cc3ca91cdfacb8b76fa7077d201e1`，`Copyright (c) 2025 holdjun`。
2. `chrisis58/kmoe-manga-downloader`，研究基线提交 `e88b7296ecd1a5ae1fe787793f87e7ea451953a4`，`Copyright (c) 2025 chris zheng`。

每项声明提供仓库与固定提交链接，并附上游 MIT License 全文。声明说明本项目参考了协议行为、故障切换、解析和下载完整性方面的公开实现与经验；无论当前代码属于独立实现还是包含受 MIT 许可保护的改写，保留完整声明均作为稳妥的发布策略。

第三方声明不得暗示上游作者认可、维护或担保本项目。

## 4. 文档入口

`README.md` 新增“许可证”小节，链接根目录 `LICENSE` 与 `THIRD_PARTY_NOTICES.md`，并简要说明：

- 项目自身以 MIT License 发布；
- 第三方组件和参考项目按各自许可证授权；
- Kmoe 服务及下载内容不属于本项目许可范围。

## 5. 发布物与验证

本次只修改许可和发布元数据，不改变应用运行行为。验收包括：

- `LICENSE` 中版权年份和署名准确；
- 两项上游版权、固定提交和 MIT 全文完整；
- README 链接有效；
- Python 构建元数据能识别 MIT License，构建产物包含许可文件；
- `scripts/check-sensitive-files.sh` 与 `git diff --check` 继续通过。

## 6. 非目标

- 不对 Kmoe 网站、接口、商标或内容主张所有权。
- 不为用户下载的漫画文件授予许可。
- 不修改应用代码、数据库、Docker 运行方式或网络协议。
- 不加入贡献者许可协议、商标政策或额外的非商业限制。
