# 本地 Linux CI 复现

状态：2026-11-26 已在全新 Linux 检出和空外部前缀完成一次实际 verify；下载、哈希校验、安装、版本检查、目标十轮及完整门禁全部通过。不是复用此前手工 WSL 环境的结果。

## 隔离约定

- 在 Linux 原生文件系统的干净检出运行，复现提交与 Node/Playwright/浏览器版本要明确记录。
- 下载缓存、Python、venv、Node、npm 依赖、Chromium 和 HDL 工具都安装在检出之外的用户目录。检出中只允许被忽略的依赖链接和测试生成物。
- 不使用 sudo，不安装系统包，不关闭 TLS 校验。代理由现有环境变量提供，证书使用系统 CA，不写入凭据。
- 每个下载项固定 URL、版本和 SHA-256；缓存命中也重验哈希。未知/不匹配版本或摘要必须失败。
- 不删除或终止用户进程；测试只清理自己创建的临时后端/浏览器。

## 固定来源

| 工具 | 来源 | SHA-256 |
|---|---|---|
| Node 24.22.3 Linux x64 | nodejs.org 官方 SHASUMS256 清单 | 4f2b175a6d53a5c617a80dba2676238a0688cef28c6da4eba35c7d844e66fcfb |
| CPython 3.14.10 GIL install_only_stripped | astral-sh/python-build-standalone release 20261124 | 73ee0629c19e9f87077f318cd50d7e703137c274479ce8e8fd5723e75c86c9bc |
| OSS CAD Suite Linux x64 2026-11-17 | YosysHQ 官方 release digest | d31c77e62aff4c922285ffc5265afa92034199206abb188bc72c0ee97b85e749 |
| Ubuntu libnspr4 2:4.35-0ubuntu0.22.04.1 | Ubuntu 签名包索引 | b3c96e4a61675c87f8d9655109346748847d859abc95f20493159d06b5aa30ef |
| Ubuntu libnss3 2:3.98-0ubuntu0.22.04.5 | Ubuntu 签名包索引 | 75f3879ab9969a930b5bf4b9229345d57e2ebe310ad8ce58c9d91393d823b236 |
| Ubuntu libasound2 1.2.6.1-1ubuntu1.2 | Ubuntu 签名包索引 | dce4ce1043cde35f4bc375a4b1bd84badd5dec7e656ea2a8849edf9215bc8c33 |

完整归档清单见 [../scripts/linux-ci-tools.json](../scripts/linux-ci-tools.json)，浏览器包含 Chromium/Headless Shell 145.0.7632.6 和 FFmpeg 1011 的固定摘要。Python 完整依赖使用 [../requirements-linux-ci.lock](../requirements-linux-ci.lock)，仅接受固定 wheel 哈希；npm 按现有 lockfile 的版本与 integrity 安装。不允许浮动 latest 安装。

## 从零运行

入口为 [../scripts/local_linux_ci.py](../scripts/local_linux_ci.py)。引导阶段只需要 Linux x86_64 的系统 Python >=3.10 标准库、curl、tar、dpkg-deb；测试阶段始终使用清单固定的 CPython。脚本拒绝 root 用户、检出内部/祖先工具目录、未知清单字段、错误摘要和已有真实 node_modules，不自动覆盖用户环境。

```bash
git clone --branch perf/2b-paired https://github.com/lylintel/bd_prototype.git "$HOME/bd-ci-checkout"
python3 "$HOME/bd-ci-checkout/scripts/local_linux_ci.py" \
	--repo "$HOME/bd-ci-checkout" \
	--prefix "$HOME/bd-ci-tools-clean" \
	--mode verify
```

首次 prefix 必须为空或不存在。归档、venv、npm 缓存、实际 node_modules、浏览器和库都位于 prefix；检出中的 web/node_modules 只是指向外部依赖的受忽略链接。使用新 lock 必须选择新 prefix，旧安装不会被静默改写。

支持 setup、target、check、verify 四种模式；verify 依次做 setup、目标用例十轮和完整门禁。target 的十轮是固定次数，不是失败重试；check 沿用现有脚本的两分片和全部时限。结果成功时在 prefix 写入对应的 `*-passed.json`；发生失败则没有该成功标记。版本与摘要记录在 installation.json。

需要代理时由调用环境提供 `https_proxy` / `http_proxy`，不写入仓库或报告。WSL 可使用 Windows 系统代理地址传入环境，不能禁用证书验证。默认 CA 为 /etc/ssl/certs/ca-certificates.crt；企业 CA 应由系统信任配置提供。便携 Verilator 使用自己的 bin 包装器，LD_LIBRARY_PATH 仅指向外置浏览器库，绝不加入套件自带 libc。

## 验证要求

从空的外部安装目录开始，实际下载、校验、安装，再运行版本检查、目标用例十轮及完整 scripts/check.py。保留安装清单、机器/运行时版本、失败状态附件、trace 和报告；不得只记录命令而宣称执行成功。

D050 的既有手工环境证据位于 build/ci-axis-linux-20261126，仅作为历史对照。本轮新脚本的从零结果单独记录，不覆盖历史证据。

## 实际从零记录

- 平台：WSL Ubuntu 22.04、Linux x86_64、普通用户；检出基线 d701e9d 加本任务六个新文件。
- 新检出：/home/yulongl1yulongl1/bd-linux-ci-zero-checkout-20261126-1；新工具目录：/home/yulongl1yulongl1/bd-linux-ci-zero-tools-20261126-1。首次均无已安装依赖，九个归档由脚本重新下载并校验。
- 实测 Node v24.22.3、CPython 3.14.10、Playwright 1.58.2、Chromium 145.0.7632.6、Verilator 5.055 devel v5.054-302-g2d6aba6ed (mod)、Yosys 0.70 git 28ba3cb92。installation.json 记录全部归档及 lockfile 摘要。
- 目标用例固定 10/10 通过（4.7 分钟）；完整门禁 255+55+347+97=754 Python、91 子测试、75 Node、38 E2E 通过，两浏览器分片 3.4/1.9 分钟。旧语义基准 201.792/236.663ms，仅为原门禁，不是接口配对验收。
- 本地证据目录 build/linux-ci-zero-20261126 保存 zero-verify.log、installation.json、verify-passed.json 和浏览器报告。未用 sudo，全部实际依赖在检出外，没有真实模型调用。
- 后续离线回归发现并修复复用目录后旧成功标记残留的问题：每次执行前使对应模式标记失效，只有本次成功才重新写入。七项引导器回归通过；最终代码完整门禁通过 755 Python +91 子测试、75 Node、38 E2E（两分片 2.5/1.5 分钟），原时限不变，日志 final-check.log。旧语义基准 205.349/235.090ms 通过，不作为新配对结果。