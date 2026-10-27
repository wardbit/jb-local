# JB Local

Windows、Linux、macOS 共用的本地脚本项目，用于替代 `irm … | iex` / `wget … && bash …` / `curl … && bash …` 的远程执行方式。

**GitHub 公开版只包含 MIT 源码，不分发第三方 JAR、配置和授权文件。** 安装需要你另行准备有权使用且经过核验的 `vendor/` 资源；资源齐备后安装过程不访问网络。 主程序是可直接阅读的 `jb.py`，仅使用 Python 标准库。需要 Python 3.9 或更新版本，不需要 pip 包；Java 使用 IDE 自带的运行时。

本项目实现资源部署、JVM 参数配置和授权文件写入。**配置写入成功不等于激活成功**，必须启动你使用的 IDE 检查授权界面。本项目未验证实际 IDE 的激活结果，也不承诺将来版本兼容。

## 快速使用

克隆或解压项目，进入 `jb-local` 目录。先按 `manifest.json` 的 `files` 清单准备 `vendor/`：主 JAR、6 个插件 JAR、4 份配置和 `license.key`。公开仓库不包含这些资源；仅克隆仓库还不能运行安装。已有本地完整包的用户可保留其 `vendor/`。

`manifest.json` 固定了历史快照的校验值。不同版本或内容会被拒绝，不应为绕过检查而盲目修改哈希；自行更换资源需先核验其来源及兼容性。测试使用无效的惰性字节夹具，不依赖第三方资源，也不会执行任何 JAR。

Windows PowerShell：

```powershell
python .\jb.py verify
python .\jb.py list
python .\jb.py install
# 确认预览中的目录正确，并关闭所有相关 IDE 后：
python .\jb.py install --apply
```

macOS / Linux：

```bash
python3 ./jb.py verify
python3 ./jb.py list
python3 ./jb.py install
# 确认预览中的目录正确，并关闭所有相关 IDE 后：
python3 ./jb.py install --apply
```

也可以分别使用 `./jb.ps1 install` 和 `bash ./jb.sh install`。无需管理员或 `sudo`。启动脚本仅调用本地 Python；不绕过系统脚本执行策略、不安装运行时。

`install` 默认只预览；`--apply` 明确执行。自动模式会处理所有找到且可用的 IDE 配置目录，包括仍保留的旧版本；只想修改一个版本时使用下面的 `--config-dir`。

## 自定义目录或只处理一个 IDE

```powershell
python .\jb.py install --config-dir "$env:APPDATA\JetBrains\IntelliJIdea2026.2" --product idea
```

```bash
python3 ./jb.py install --config-dir "$HOME/Library/Application Support/JetBrains/IntelliJIdea2026.2" --product idea
```

产品参数支持 `idea`、`pycharm`、`clion`、`phpstorm`、`goland`、`webstorm`、`rider`、`datagrip`、`rubymine`、`appcode`、`dataspell`、`dotmemory`、`rustrover`；这是目录/文件命名支持列表，不代表每个产品的激活都经过验证。

若用户 VM options 文件不存在，脚本会尝试读取系统缓存目录中的 `.home`，从对应 IDE 安装目录复制默认参数作为基础。找不到时会跳过，避免生成缺少原始参数的文件。可以先在 IDE 使用 **Help → Edit Custom VM Options**，或指定安装目录：

```bash
python3 ./jb.py install --config-dir "$HOME/.config/JetBrains/IntelliJIdea2026.2" --product idea --ide-home /opt/idea
# macOS 的 --ide-home 可以传 /Applications/IntelliJ\ IDEA.app
```

存在 `IDEA_VM_OPTIONS` 等环境变量覆盖时，不删除变量；显式传入真正生效的已有文件：

```bash
python3 ./jb.py install --config-dir /path/to/config --product idea --vmoptions /path/to/effective.vmoptions
```

上述命令确认无误后追加 `--apply`。Toolbox、自定义 `idea.config.path`、Snap/Flatpak 容器、远程开发后端等不一定能自动识别，需显式指定实际目录。本项目不自动调整应用沙箱权限。环境变量检测使用当前进程继承的环境；通过桌面启动的 IDE 可能使用不同环境，应以 IDE 的 Custom VM Options 界面显示的路径为准。

## 恢复

安装完成会打印备份 ID，例如 `20261027T080000Z-012345abcdef`。使用实际输出的 ID：

```bash
python3 ./jb.py restore 20261027T080000Z-012345abcdef
python3 ./jb.py restore 20261027T080000Z-012345abcdef --apply
```

Windows 将 `python3` 改为 `python`。恢复前也应关闭 IDE。恢复会核对备份完整性和当前文件；若安装后你手动改过文件，会停止，避免覆盖新内容。需要时可对照备份手动合并。恢复本身也会留下恢复前的备份。

默认存储位置：

```text
~/.jb-local/
  runtime/<资源清单哈希>/    固定的 JAR 和配置
  backups/<备份ID>/         原始字节备份、journal.json
```

资源目录在恢复后保留，避免破坏其他仍引用它的 IDE；它不会单独运行。确认所有 IDE 都已恢复后才可自行删除该目录。项目文件夹在部署完成后可以移动，但 `runtime/` 不能移动或删除，IDE 参数包含它的绝对路径。

可将全局 `--state-dir` 放在子命令前，使用另外的持久目录；恢复时必须使用同一个目录：

```bash
python3 ./jb.py --state-dir /your/persistent/jb-local install
```

写入采用文件替换与预先保存的日志；普通失败自动恢复已修改配置。断电、强制结束或磁盘损坏不可能保证自动恢复。若遗留 `.lock`，先确认没有安装进程，再删除这个锁文件，使用相应备份 ID 恢复。`backups/` 含旧授权文件等个人数据，不要公开上传。

## 相比原脚本的变化

- 不执行下载的 PowerShell/Bash，不调用远程授权接口，不自动提权。
- 默认只修改用户级 VM options 和产品 `.key`，不修改 IDE 安装目录，避免破坏 macOS 应用签名。显式使用 `--vmoptions` 时修改你指定的文件，请选择用户自定义文件。
- 保留不相关 JVM 参数和其他 `-javaagent`；只替换指向 `ja-netfilter.jar` 的旧条目。
- 不删除旧工具目录、Shell 配置、注册表环境变量；不打开推广网页、不删除自身。
- 检查 12 个资源的 SHA-256，发现缺失、改动或额外资源就停止。符号链接、junction 和特殊文件拒绝处理。
- 安装/恢复前预览，逐项备份，恢复遇到后续修改则停止。

## 资源核验边界

资源取自 2026-10-27 的站点响应。主 JAR 对应上游 **2025.3.0**，不是原脚本注释中写的 2022.2.0。核心与另外五个插件文件逐字节匹配上游发布包；其中原站 `dns.jar` 实际等于上游 `env.jar`，为保持行为沿用原文件名。

**`privacy.jar` 未能与作者发布包独立比对。** 原站的 HTTPS 证书核验失败，站点资源通过原命令使用的 HTTP 下载。上游对照包通过 HTTPS 获取并匹配发布页 SHA-1。站点专用配置、授权文件及 `privacy.jar` 只有本次快照的 SHA-256；哈希能发现后续变化，不能证明下载时的文件安全。没有进行所有 JAR 的完整源码审计，也未运行这些 JAR。

完整来源和哈希见 `manifest.json`，许可边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。所有第三方代码、配置和授权数据的权利归各自作者，未对它们重新授权。

## 开发验证

```bash
python3 -m unittest discover -s tests -v
```

测试只使用临时目录，不修改真实 IDE。测试涵盖三端路径、默认参数保留、资源篡改、预览、重复执行、回滚、恢复冲突等。已在 Windows Python 3.12 和 WSL Ubuntu Python 3.14 验证；macOS 仅做路径夹具测试，未做原生运行验证。

## 开源协议

自写代码、启动脚本、测试与文档采用 [MIT](LICENSE) 协议，版权归 wardbit。第三方资源不适用本仓库的 MIT 授权，且不在公开仓库内分发，详见 [第三方说明](THIRD_PARTY_NOTICES.md)。
