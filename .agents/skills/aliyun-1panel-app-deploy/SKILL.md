---
name: aliyun-1panel-app-deploy
description: 将项目部署到用户的阿里云服务器，并通过 1Panel 与 OpenResty 配置站点、域名、反向代理和 HTTPS。用户只要提到 aliyun、1Panel、OpenResty、建站、绑定域名、反向代理、HTTPS、证书同步、静态站点发布、容器应用发布，或希望让站点显示在 1Panel 网站列表中，都应该使用这个 skill。
---

# 阿里云 1Panel 项目部署

这个 skill 只负责一件事：

- 把项目部署到阿里云服务器
- 通过 1Panel 建立站点记录
- 让站点配置显示在 1Panel 的 `网站` 页面中
- 通过 OpenResty 提供静态资源、反向代理和 HTTPS

它是通用流程，不绑定 `aitravel`，可用于：

- 纯静态站点
- 前后端分离项目
- 只有后端、通过域名反代暴露的项目
- 需要自定义 OpenResty 配置和证书同步的项目

## 何时使用

- 用户要把项目上传到 `aliyun` 服务器
- 用户要通过 1Panel 创建站点并绑定域名
- 用户要让站点出现在 1Panel 的 `网站` 列表里
- 用户要通过 OpenResty 配置静态资源、反向代理或 HTTPS
- 用户要把前端构建产物发布到 OpenResty 站点目录
- 用户要把后端服务通过 Docker Compose 或其他运行方式挂到 OpenResty 后面

## 前提条件

- 在仓库根目录执行
- `ssh aliyun` 可用
- 服务器已安装 1Panel
- 服务器已安装并启动 OpenResty 应用
- 最终验证 HTTPS 之前，域名应已解析到服务器

## 先收集这些信息

在动手之前先确认：

- SSH 主机别名，通常是 `aliyun`
- 项目名
- 服务器部署目录，通常是 `/root/<项目名>`
- 目标域名
- 是否有前端构建产物
- 是否有后端服务
- 后端运行方式
  - `docker compose`
  - 1Panel 现有运行环境
  - 其他进程管理方式
- OpenResty 需要代理到的上游地址
- 健康检查地址
- 1Panel 需要识别的站点 conf 文件名

然后从仓库中的这些文件反推真实部署输入：

- `README.md` 或其他启动文档
- 前端构建配置，例如 `package.json`
- `Dockerfile`
- `docker-compose*.yml`
- `.dockerignore`
- `deploy/` 下已有脚本或配置文件

如果仓库里已经有部署文件，优先复用现有文件，不要重新发明一套结构。

## 读取参考文档

- 详细部署流程看 [references/workflow.md](references/workflow.md)

## 主流程

1. 根据项目信息建立部署映射
2. 先检查 SSH、Docker、OpenResty、域名和现有站点状态
3. 先从仓库文件反推构建命令、上传集合和服务器前置文件
4. 如果项目有前端构建产物，先在本地构建
5. 先在 1Panel 中创建或复用站点记录
6. 只上传真正需要的源文件和部署文件
7. 把最终站点配置写入 1Panel 正在使用的 OpenResty conf 路径
8. 启动或更新项目运行时
9. 配置或同步证书
10. 从服务器、本地命令行和 1Panel 页面三个角度验证部署结果

## 关键规则

- 必须先在 1Panel 里创建站点记录，不能只手写一个 conf 就指望它出现在 `网站` 列表
- 如果要让 1Panel v1 的 HTTPS 页面正确解析自定义配置，最终 OpenResty 配置最好保持为单个 `server {}`
- `listen 80;` 和 `listen 443 ssl http2;` 要放在同一个 `server {}`
- `ssl_certificate`、`ssl_certificate_key`、`ssl_protocols`、`ssl_ciphers` 也要放在这个首个且唯一的 `server {}`
- 证书路径应使用 OpenResty 容器内实际生效的 `/www/certs/<domain>/...`
- 有后端时，后端应保持在内网地址，由 OpenResty 统一反向代理
- 有前端构建产物时，应发布到当前 OpenResty 正在服务的站点目录

## 常见坑

- 1Panel v1 对 HTTPS 配置解析比较脆弱，如果第一个 `server {}` 不是完整的 SSL 站点块，`网站设置 -> HTTPS` 可能报错或显示为空
- 浏览器里看到的 502、空白或跳转异常，不一定是服务器问题，本地代理或 TUN 也可能导致假象
- 部署脚本里如果写死了 OpenResty 容器名，1Panel 重建容器后需要重新确认容器名

## 预期结果

- 项目被部署到阿里云服务器
- 站点出现在 1Panel 的 `网站` 列表中
- 域名、HTTPS、静态资源和反向代理都走正确的 OpenResty 站点
- 进入 1Panel 的站点设置页面时，仍能看到这条站点的配置关系
