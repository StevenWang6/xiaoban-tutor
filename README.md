# 小伴：AI 家庭教师

使用 DeepSeek API 进行中文课后辅导的 Web 智能体。支持个性化学习档案、文字对话、拍照识题、浏览器语音输入与朗读，以及截取共享屏幕并在图片上批注。应用包含可部署的 WSGI 服务、Docker 镜像和 Render Blueprint。

## 启动

需要 Python 3.10 或更高版本，以及 DeepSeek API 密钥。首次使用时，在项目目录中复制示例配置文件并填写密钥：

```powershell
Copy-Item .env.example .env
notepad .env
```

将 `.env` 中的 `DEEPSEEK_API_KEY` 替换为你自己的密钥，然后启动：

```powershell
python hello.py
```

`.env.example` 只是模板，不要在其中填写真实密钥。已存在的系统环境变量优先于 `.env`。

打开 <http://127.0.0.1:8000>。服务启动时会自动读取项目目录中的 `.env`；已存在的系统环境变量优先。默认模型为 `deepseek-flash`，也可在 `.env` 中设置 `DEEPSEEK_MODEL` 和 `DEEPSEEK_BASE_URL`。`.env` 已加入 Git 忽略规则，请勿提交密钥。API 密钥只由 Python 服务端读取，不会发送到浏览器。

默认每个客户端 IP 每分钟最多 20 次提问，可用 `RATE_LIMIT_REQUESTS` 调整；该限制用于降低公网部署时额度被滥用的风险，不能代替登录鉴权。如需限制访问人群，建议在托管平台前面增加登录认证或访问控制。

## 部署到公网

### Render（项目已提供配置）

1. 将项目推送到你自己的 GitHub 仓库；确认真实 `.env` 没有被提交（已在 `.gitignore` 和 `.dockerignore` 中排除）。
2. 在 Render 选择 **New → Blueprint**，连接该仓库并部署。Render 会依据 [render.yaml](./render.yaml) 构建 Docker 服务，并使用 `/health` 检查服务健康状态。
3. 在 Render 要求输入 `DEEPSEEK_API_KEY` 时填写你的 DeepSeek 密钥。也可以在服务的 **Environment** 设置中添加该变量。不要将密钥写入源代码、`render.yaml` 或客户端页面。
4. 部署成功后使用 Render 提供的 HTTPS 网址访问。语音和屏幕共享等浏览器功能要求 HTTPS 和相应的浏览器权限。

Render 免费服务可能在空闲时休眠，首次访问会有冷启动延迟。API 密钥、账单和用量限制请在 DeepSeek 控制台管理。

### Docker

安装并启动 Docker 后，在项目目录执行：

```powershell
docker build -t xiaoban-tutor .
docker run --rm -p 8000:8000 -e DEEPSEEK_API_KEY="你的 DeepSeek API 密钥" xiaoban-tutor
```

然后打开 <http://localhost:8000>。生产容器使用 Gunicorn WSGI 服务；本地 `python hello.py` 仍使用 Python 自带的开发服务器。

### Sealos（国内访问首选）

项目已提供 [sealos.yaml](./sealos.yaml)，可直接部署到 Sealos 云或自建的 Kubernetes 集群。Sealos 国内网络低延迟，调用 DeepSeek 也更快，适合面向国内用户的部署。

1. 构建镜像并推送到一个镜像仓库（Docker Hub、阿里云容器镜像服务 ACR，或 Sealos 自带的镜像仓库）：

   ```powershell
   docker build -t xiaoban-tutor .
   docker tag xiaoban-tutor <你的镜像仓库地址>/xiaoban-tutor:latest
   docker push <你的镜像仓库地址>/xiaoban-tutor:latest
   ```

2. 编辑 [sealos.yaml](./sealos.yaml)：把 Deployment 里的 `image` 替换为上一步的镜像地址，把 Ingress 里的 `<你的域名>` 替换成你的域名，并在 Secret 中填写 `DEEPSEEK_API_KEY`。**不要把真实密钥提交到 Git**——生产环境建议改用命令注入：

   ```powershell
   kubectl create secret generic xiaoban-tutor-secrets --from-literal=DEEPSEEK_API_KEY=你的密钥
   ```

3. 部署：

   ```powershell
   kubectl apply -f sealos.yaml
   ```

4. 确认健康检查通过后，通过 Ingress 配置的域名（需已解析到集群并启用 HTTPS）访问。语音、屏幕共享等浏览器功能依赖 HTTPS。

Sealos 云也会为应用分配形如 `<应用名>.<命名空间>.cloud.sealos.io` 的域名并自动处理证书；此时可去掉 Ingress 中的 `tls` 段和 cert-manager 注解。

#### 方式二：Sealos 云网页控制台（无需本地 kubectl）

如果不想安装 kubectl，可以直接在 Sealos 云网页控制台用鼠标部署，效果与上面的 [sealos.yaml](./sealos.yaml) 等价，且平台会自动处理域名和 HTTPS：

1. 登录 [cloud.sealos.io](https://cloud.sealos.io)，进入 **应用管理**（或 **应用商店**）→ **新建应用**。
2. 在 **镜像** 一栏填写上一步推送的镜像地址（例如 `docker.io/用户名/xiaoban-tutor:latest`）。
3. 在 **环境变量** 中添加：
   - `DEEPSEEK_API_KEY`：你的 DeepSeek 密钥（建议使用平台的密钥管理，不要明文写在代码或文档里）
   - `DEEPSEEK_MODEL`：`deepseek-flash`（可选）
   - `PORT`：`8000`
   - `RATE_LIMIT_REQUESTS`：`20`（可选）
4. 在 **端口** 中暴露容器端口 `8000`，对外协议选择 HTTP。
5. 在 **网络/域名** 中开启公开访问，选择平台自动分配域名（形如 `<应用名>.<命名空间>.cloud.sealos.io`），平台会自动签发 HTTPS 证书——语音、屏幕共享依赖它。
6. 部署后等待应用状态变为运行中、`/health` 探针通过，即可用分配的 HTTPS 域名访问。

> 说明：网页端的自动域名与 HTTPS 托管，对应 [sealos.yaml](./sealos.yaml) 中的 `Ingress`（含 `tls` 与 cert-manager 注解）；走网页端时这些会由平台自动完成，无需在配置里手动声明。

### 其他平台

项目根目录的 [Procfile](./Procfile) 可直接用于支持 Procfile 的 Python 托管平台（例如 Railway）。平台需要注入 `DEEPSEEK_API_KEY`，并把 `PORT` 交给应用监听；`hello:application` 是 WSGI 入口。

### 部署检查清单

- 密钥仅通过托管平台的 Environment/Secret 配置注入，未写入仓库。
- 使用平台提供的 HTTPS 域名；HTTP 下语音、屏幕共享等浏览器能力可能被禁用。
- 平台健康检查路径为 `/health`。
- 公网 URL 会消耗你的 DeepSeek 额度；请设置平台预算或访问控制。

## 多模态交互

- 使用“图片”上传题目；也可以在截图或照片上拖动鼠标/手指添加批注。
- 使用“屏幕”选择窗口或屏幕共享，截取的画面可先批注，再点击发送。
- “语音”使用浏览器的 Web Speech API 识别中文；回答中的“朗读”使用浏览器语音合成。支持情况取决于浏览器、网络和权限设置。
- 图片和屏幕截图会在发送问题时传给 DeepSeek API。应用服务端不保存对话或图片；学习档案保存在当前浏览器的本地存储中。

## 测试

```powershell
python -m unittest -v
```
