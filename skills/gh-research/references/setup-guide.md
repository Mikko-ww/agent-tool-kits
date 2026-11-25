# 环境配置与检查路由

进入取证前使用本文件。检查只读状态，不安装、不登录、不修改配置、不读取凭据值。

## 依赖概览

| 依赖 | 类型 | 必需 | 支撑功能 | 缺失后果 |
|---|---|---|---|---|
| `python-runtime` | runtime | 是 | discover / verify / score / report | 脚本无法运行，全部功能降级为手工流程 |
| `gh-cli` | cli | 否 | discover / verify | 改用网页检索取证，覆盖面下降 |

机器可读清单在 `skill-dependencies.json`，检查器在 `scripts/check_environment.py`。

## Python

- 官方主页：<https://www.python.org/>
- 官方文档：<https://docs.python.org/3/>
- 官方下载：<https://www.python.org/downloads/>
- 最低版本：3.10。核验日期 2026-11-24，核验版本 3.12.10。

步骤：

1. macOS：`brew install python@3.12`。
2. Windows：从官方下载页安装，向导中勾选 Add python.exe to PATH。
3. Linux：用发行版包管理器安装 `python3`。
4. 重开终端后验证。

验证命令：

```bash
python3 --version
```

本技能脚本只用标准库，不需要 pip 安装任何第三方包，不读取任何凭据。切换或卸载 Python 后重新运行检查即可，本技能不保存状态。

## GitHub CLI

- 官方主页与下载：<https://cli.github.com/>
- 官方手册：<https://cli.github.com/manual/>
- 官方登录入口：<https://github.com/login>
- 核验日期 2026-11-24，核验版本 2.102.0。

安装并登录：

1. 按操作系统从官方主页安装 `gh`。
2. 终端执行 `gh auth login`。
3. 依次选择 `GitHub.com` → `HTTPS` → `Login with a web browser`。
4. 复制一次性代码，在浏览器中完成授权。
5. 验证登录与额度。

验证命令：

```bash
gh auth status
```

```bash
gh api rate_limit --jq '.resources.search'
```

凭据存储：由 `gh` 自行写入操作系统密钥链（macOS Keychain、Windows 凭据管理器、Linux secret service）。本技能不读取、不复制、不记录该凭据，也不要求在对话中粘贴 Token。

权限范围：只读使用搜索与仓库接口，不创建、不修改、不删除任何远端资源。不要为本技能申请超出读取公开仓库所需的权限。

轮换与撤销：执行 `gh auth logout` 退出登录；在 GitHub 网页 `Settings → Applications → Authorized OAuth Apps` 中撤销 GitHub CLI 授权，然后重新 `gh auth login`。

## 探测结果怎么传

`gh` 的版本与登录状态属于外部探测，检查器自己不执行，必须由宿主跑最小只读命令后把**脱敏**结果写成 JSON 传入。

宿主执行：

```bash
gh --version
```

```bash
gh auth status
```

只根据退出码与是否出现已登录账号判断，**不要把 Token、账号邮箱或完整输出写进 JSON**。写成：

```json
{
  "gh-cli": {
    "gh-version-probe": {
      "check_type": "cli_probe",
      "target": "gh --version",
      "status": "ready",
      "reason_code": "ok",
      "checked_at": "2026-11-24T09:00:00Z"
    },
    "gh-auth-probe": {
      "check_type": "auth_probe",
      "target": "gh auth status",
      "status": "ready",
      "reason_code": "ok",
      "checked_at": "2026-11-24T09:00:00Z"
    }
  }
}
```

`checked_at` 必须是 UTC 且以 `Z` 结尾。`status` 为 `ready` 时 `reason_code` 只能是 `ok`；`missing` 或 `unavailable` 时必须是具体原因，例如 `auth_expired_or_invalid`、`quota_or_rate_limit`、`network_or_timeout`、`version_incompatible`。

传入检查器：

```bash
python <skill-dir>/scripts/check_environment.py --capability discover --capability verify --probe-results <probe.json>
```

## 状态路由

| 状态 | 含义 | 下一步 |
|---|---|---|
| `ready` | 本次所需依赖均可用 | 直接进入流程，不展示安装教程 |
| `partial` | 核心可用，部分可选功能不可用 | 继续流程，只说明受影响功能与降级方式 |
| `needs_setup` | 必需依赖缺失 | 只展示缺失项的步骤，配置后重检 |
| `unavailable` | 配置存在但故障、权限不足、额度耗尽或版本不兼容 | 说明原因与恢复步骤，按降级继续 |

已通过的项目不重复引导。重检时只报告状态变化和仍未满足的项目。

## 降级要点

- `gh` 缺失或未登录：用网页搜索发现候选，用 `search --from-json` 写库；数值标注实际来源与获取日期。
- 代码搜索不可用：核心能力降为 E2 文档级，措辞停在「声明具备」，相似度按规则封顶。
- 限流或超时：有限重试（≤2 次）后降级，不无限循环。
- Python 不可用：手工按 references 的规则执行，并明确标注「未完成机器校验」。
- 渲染或落盘失败：保留对话输出，明确说明 HTML 未生成，**不得给出路径**。

任何情况下都不得用模型记忆、猜测数据或未经核验的来源伪装完整结果。