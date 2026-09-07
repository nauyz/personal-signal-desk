# Personal Signal Desk · 个人信源

非商业面试展示作品：聚合 AIHOT、GitHub Trending、Product Hunt、SoPilot 和 Hacker News 的公开信息，保留双语内容、分类筛选和官方回链。

在线地址：https://nauyz.github.io/personal-signal-desk/

GitHub Actions 每小时第 17 分钟运行 Python 采集，GitHub Pages 提供静态页面。浏览器访问不会触发采集，个人电脑无需保持开机。定时任务可能延迟；数据以页面显示的来源更新时间为准。

## 开发

Python 3.10+，无需第三方 Python 依赖。

```sh
python -m unittest discover -s tests -q
python server.py
```

默认只读本地缓存。云端通过 `python cloud_build.py --collect` 更新，`python cloud_build.py` 仅导出已有数据。部署步骤参见 [云端部署说明](云端部署说明.md)。

公开仓库不包含本地数据库、日志、密钥或开发历史。Product Hunt 凭据配置于仓库 Secrets。
