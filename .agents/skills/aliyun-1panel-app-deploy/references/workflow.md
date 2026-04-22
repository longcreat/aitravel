# 部署流程

这个文档记录“把项目部署到阿里云服务器，并让它正确显示在 1Panel 中”的通用流程。

## 1. 先建立部署映射

先把这些变量想清楚：

- `SSH_HOST`：通常是 `aliyun`
- `APP_NAME`：项目名
- `DEPLOY_ROOT`：服务器部署目录，通常是 `/root/<项目名>`
- `DOMAIN`：要在 1Panel 中显示的域名
- `CONF_FILE`：站点配置文件名，通常是 `<domain>.conf`
- `OPENRESTY_CONF_DIR`：通常是 `/opt/1panel/apps/openresty/openresty/conf/conf.d`
- `OPENRESTY_WEB_ROOT`：当前站点真正使用的静态目录，不要机械假设一定是 `/opt/1panel/apps/openresty/openresty/root`
- `FRONTEND_DIST`：前端构建产物目录，没有则留空
- `UPSTREAM_ADDR`：后端反向代理地址，没有则留空
- `HEALTH_URL`：项目健康检查地址

## 2. 识别项目形态

先判断项目属于哪一类：

- 纯静态站点
  - 只需要构建前端并发布到 OpenResty 站点目录
- 前端 + 后端
  - 前端发布到 OpenResty
  - 后端独立运行
  - OpenResty 负责把 `/api/` 或其他路径代理到后端
- 纯后端项目
  - 不需要静态发布
  - 但如果要通过域名暴露，依然建议在 1Panel 中创建站点记录并由 OpenResty 反向代理

## 3. 部署前检查

开始之前先检查基础状态：

```powershell
ssh <SSH_HOST> "hostname && pwd"
ssh <SSH_HOST> "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
curl.exe --noproxy "*" -I http://<DOMAIN>
curl.exe --noproxy "*" -I https://<DOMAIN>
```

如果浏览器表现和 `curl.exe --noproxy "*"` 不一致，先怀疑本地代理，而不是立刻改服务器。

还要确认：

- 这个域名在 1Panel 的 `网站` 里是否已经存在
- 当前正在生效的 conf 文件是哪一个
- OpenResty 当前容器名是什么
- 证书最终从哪个路径被 OpenResty 使用

## 4. 先从仓库文件反推部署输入

这一步决定“下次能不能完整复用”。

至少检查这些文件：

- `README.md`：确认项目启动方式、前后端目录、健康检查接口
- 前端 `package.json`：确认构建命令和构建产物目录
- `Dockerfile`：确认镜像构建真正依赖哪些文件
- `docker-compose*.yml`：确认 `build.context`、`env_file`、`ports`、`volumes`
- `.dockerignore`：确认哪些本地目录本来就不应该上传
- `deploy/` 下的脚本和 conf：确认是否已有现成部署入口

从这些文件里反推出 3 件事：

1. 本地需要先构建什么
2. 服务器上必须先存在什么
3. 真正需要上传什么

### 4.1 如何从 `Dockerfile` 反推上传集合

重点看：

- `COPY` 了哪些文件或目录
- `WORKDIR` 是什么
- 镜像启动命令依赖什么目录结构

原则：

- `Dockerfile` 明确 `COPY` 的内容，通常就是镜像构建最小上传集合
- 没有被 `COPY`、也没有被运行时挂载依赖的内容，不要默认上传

### 4.2 如何从 `docker-compose` 反推服务器前置条件

重点看：

- `build.context`
- `env_file`
- `ports`
- `volumes`

原则：

- `build.context` 决定服务器上必须具备的构建目录
- `env_file` 指向的文件必须在 `docker compose up` 之前就存在
- `volumes` 的源路径如果是宿主机路径，也必须预先存在
- 如果 `volumes` 挂载了配置文件或数据目录，就不能只上传镜像构建输入，还要补齐这些运行时文件

### 4.3 如何从 `.dockerignore` 反推“不上传”集合

`.dockerignore` 里排除的目录，通常也是远端不该直接复制过去的候选项，例如：

- `.venv`
- `tests`
- `data`
- 本地专用配置

这类目录如果运行时还需要，应该通过“服务器侧预创建”而不是“本地整包上传”来解决。

## 5. 本地构建项目

如果项目有前端构建产物，先在本地构建：

```powershell
Set-Location <frontend-dir>
<build-command>
Set-Location ..
```

如果是纯后端项目，这一步跳过。

## 6. 先补齐服务器前置文件

在首次部署或新服务器部署时，这一步不要漏。

典型前置文件包括：

- `.env`
- 运行时配置文件
- 被 `docker-compose` 挂载的宿主机目录
- 被 `docker-compose` 挂载的宿主机单文件

如果这些文件不在仓库里，或者被 `.dockerignore` 排除了，就应该在服务器端手动创建或从安全来源同步，而不是期待 `docker compose` 自己补出来。

## 7. 只上传需要的文件

先准备服务器部署目录：

```powershell
ssh <SSH_HOST> "mkdir -p <DEPLOY_ROOT>"
```

上传时只保留真正需要部署的内容：

- 项目运行所需源码
- Dockerfile、Compose 文件
- 部署脚本和 conf 模板
- 前端构建产物

不要把这些目录当作部署产物上传：

- `frontend/node_modules`
- `.venv`
- `tests`，除非它本来就是运行时的一部分
- 本地数据库
- 已经在服务器维护的密钥和配置文件
- 缓存目录和临时压缩包

如果仓库已有部署脚本，优先用现有脚本。否则使用最小化的 `scp` 或 `rsync` 集合。

最少应当上传的对象，通常来自这三类：

- 镜像构建所需文件
- 运行时编排文件
- 站点配置和部署脚本

## 8. 先在 1Panel 中创建站点

这是让项目显示在 1Panel `网站` 列表中的关键步骤：

- 先在 1Panel 中创建站点记录
- 后续继续沿用 1Panel 生成的这条站点记录
- 覆盖它正在使用的 conf 文件，而不是另起一份无关 conf

不要指望仅仅往 `conf.d` 里扔一个手写文件，就能出现在 1Panel `网站` 页面里。

## 9. 发布前端资源

如果项目有静态资源或 SPA 构建产物：

```powershell
scp -r <FRONTEND_DIST>/. <SSH_HOST>:<OPENRESTY_WEB_ROOT>/
```

确认文件确实进入当前正在生效的站点目录，而不是临时目录或备份目录。

## 10. 写入最终 OpenResty 配置

把最终站点配置复制到 1Panel 正在使用的 conf 路径：

```powershell
scp <local-conf-file> <SSH_HOST>:<OPENRESTY_CONF_DIR>/<CONF_FILE>
```

### 让 1Panel HTTPS 页面可识别的配置形态

如果你希望 1Panel v1 的 HTTPS 页面能正确读取这份自定义配置，建议保持下面这个结构：

- 只保留一个 `server {}`
- `listen 80;` 和 `listen 443 ssl http2;` 放在同一个 `server {}`
- `ssl_certificate`
- `ssl_certificate_key`
- `ssl_protocols`
- `ssl_ciphers`
- `server_name <DOMAIN>;`

如果项目有后端接口：

- 把 `/api/` 或指定路径代理到 `UPSTREAM_ADDR`
- 保留这些头：
  - `Host`
  - `X-Real-IP`
  - `X-Forwarded-For`
  - `X-Forwarded-Proto`

如果是 SPA：

- `/` 使用 `try_files $uri $uri/ /index.html`

## 11. 启动或更新项目运行时

如果项目通过 Docker Compose 运行：

```powershell
ssh <SSH_HOST> "docker compose -f <DEPLOY_ROOT>/<compose-file> up -d --build"
ssh <SSH_HOST> "docker compose -f <DEPLOY_ROOT>/<compose-file> ps"
```

如果项目使用 1Panel 自带运行环境或其他进程管理方式，就走对应运行环境的更新路径。

## 12. 配置证书

证书处理方式取决于当前站点结构：

- 如果站点完全由 1Panel 网站功能托管，可直接在 1Panel 界面绑定证书
- 如果你走的是 OpenResty 自定义 conf，则要保证最终证书位于：
  - `/www/certs/<DOMAIN>/fullchain.pem`
  - `/www/certs/<DOMAIN>/privkey.pem`

如果仓库已有证书同步脚本，优先复用。没有的话，就执行最小化的导出、复制、重载流程。

### 重载 OpenResty

```powershell
ssh <SSH_HOST> "docker ps --format '{{.Names}}'"
```

确认当前 OpenResty 容器名后重载：

```powershell
ssh <SSH_HOST> "OPENRESTY_CONTAINER=\$(docker ps --format '{{.Names}}' | grep '^1Panel-openresty-' | head -n 1); docker exec \"\$OPENRESTY_CONTAINER\" sh -lc '/usr/local/openresty/bin/openresty -t && /usr/local/openresty/bin/openresty -s reload'"
```

如果 PowerShell 本地转义把 `grep` 搞乱了，就把整段逻辑放到远端 shell 中执行，或者改用 `sed -n`。

## 13. 验证部署结果

从服务器、本地命令行、1Panel 页面三侧验证。

服务器侧：

```powershell
ssh <SSH_HOST> "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
ssh <SSH_HOST> "OPENRESTY_CONTAINER=\$(docker ps --format '{{.Names}}' | grep '^1Panel-openresty-' | head -n 1); docker exec \"\$OPENRESTY_CONTAINER\" sh -lc '/usr/local/openresty/bin/openresty -t'"
```

本地：

```powershell
curl.exe --noproxy "*" -I http://<DOMAIN>
curl.exe --noproxy "*" -I https://<DOMAIN>
curl.exe --noproxy "*" <HEALTH_URL>
```

1Panel 页面：

- 打开 `网站`，确认 `<DOMAIN>` 出现在列表中
- 打开 `网站设置 -> HTTPS`，确认没有出现服务异常或空白解析失败

## 14. 复用完成的判定标准

只有同时满足下面几条，才算这个流程已经完整可复用：

- 你能从仓库文件中明确推导出构建命令、上传集合和服务器前置文件
- 你知道必须先在 1Panel 中创建站点记录，而不是只复制 conf
- 你知道最终生效的 OpenResty conf、证书路径、静态目录分别是什么
- 你知道如何重载 OpenResty 并验证配置
- 你知道如何通过 `curl.exe --noproxy "*"` 和 1Panel 页面双重验证结果

## 15. 快速排错

### 情况 A：域名可访问，但 1Panel 的 HTTPS 页面异常

- 先重新确认这个站点记录确实是从 1Panel 里创建出来的
- 重新确认当前生效 conf 文件就是 `<OPENRESTY_CONF_DIR>/<CONF_FILE>`
- 重新确认该文件只使用一个 `server {}`，并且 SSL 指令都在这个首个块里

### 情况 B：容器正常，但 `/api/` 失败

- 重新确认运行时状态是否正常
- 重新确认 OpenResty 反向代理仍然指向 `UPSTREAM_ADDR`
- 重新确认 `curl.exe --noproxy "*" <HEALTH_URL>` 的返回结果

### 情况 C：浏览器异常，但命令行验证正常

- 对比浏览器结果和 `curl.exe --noproxy "*"` 的结果
- 如果两者不一致，先排查本地代理或 TUN，再决定是否修改服务器

## 16. 示例：aitravel

这个例子只是帮助理解变量如何落地，不是限制这个 skill 只能服务于 `aitravel`。

- `APP_NAME`: `aitravel`
- `DEPLOY_ROOT`: `/root/aitravel`
- `DOMAIN`: `aitravel.aigoway.tech`
- `CONF_FILE`: `aitravel.aigoway.tech.conf`
- `OPENRESTY_CONF_DIR`: `/opt/1panel/apps/openresty/openresty/conf/conf.d`
- `OPENRESTY_WEB_ROOT`: `/opt/1panel/apps/openresty/openresty/root`
- `OPENRESTY_CERT_BASE`: `/opt/1panel/apps/openresty/openresty/www/certs`
- `FRONTEND_DIST`: `frontend/dist`
- `UPSTREAM_ADDR`: `http://127.0.0.1:18000`
- compose file: `/root/aitravel/docker-compose.aliyun.yml`
- health URL: `https://aitravel.aigoway.tech/api/health`
- repo-specific cert sync script: `deploy/aliyun/sync_aitravel_cert.sh`

### 从当前仓库文件反推出的最小部署集合

根据当前仓库里的 `backend/Dockerfile`、`backend/.dockerignore`、`docker-compose.aliyun.yml` 和 `deploy/aliyun/`，这套项目至少需要这些内容：

- `frontend/dist`
- `backend/pyproject.toml`
- `backend/Dockerfile`
- `backend/.dockerignore`
- `backend/app`
- `backend/migrations`
- `docker-compose.aliyun.yml`
- `deploy/aliyun/`

### 当前项目首次部署前必须在服务器准备好的内容

根据 `docker-compose.aliyun.yml` 可知，下面这些文件或目录在 `docker compose up -d --build` 之前就要存在于服务器：

- `/root/aitravel/backend/.env`
- `/root/aitravel/backend/config/mcp.servers.json`
- `/root/aitravel/backend/data/`

原因：

- `env_file` 依赖 `./backend/.env`
- `volumes` 挂载了 `./backend/config/mcp.servers.json`
- `volumes` 挂载了 `./backend/data`
