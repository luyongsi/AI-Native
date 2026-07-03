import json, asyncio, asyncpg
from datetime import datetime, timezone

async def main():
    conn = await asyncpg.connect("postgresql://ai_native:ai_native_dev@localhost:5432/ai_native")
    req_id = "91ba906c-13bb-437d-a0dd-68d9b35512fb"

    row = await conn.fetchrow(
        "SELECT spec FROM requirements WHERE id = $1::uuid", req_id
    )
    spec = row["spec"]
    if isinstance(spec, str):
        spec = json.loads(spec)

    sections = spec.get("sections", [])

    new_sections = []
    for s in sections:
        sid = s["id"]
        title = s["title"]
        content = s.get("content", "")
        now_ts = datetime.now(timezone.utc).strftime("%H:%M")

        if sid == "oauth_spec":
            content = """● 协议：标准 OAuth 2.0 授权码流程（Authorization Code Grant + PKCE）。
● IdP 数量：对接一个统一身份认证平台（如企业微信、阿里云 IDaaS），通过配置切换。
● 首次登录：强制绑定手机号（+86 格式），绑定后后续登录跳过。
● Token 管理：Access Token 有效期 2 小时，Refresh Token 有效期 30 天，支持静默刷新。
● 授权端点：由 IdP 提供方提供（支持配置），回调地址为 https://{domain}/api/auth/oauth/callback。
● Client ID/Secret：通过环境变量配置，支持多 IdP 时按 issuer 选择。
● 错误处理：授权拒绝 → 返回登录页并提示；Token 过期 → 自动刷新；Refresh Token 失效 → 重新登录。"""
        elif sid == "sms_spec":
            content = """● 短信服务商：阿里云短信（aliyun-sms）。
● 短信模板：登录验证码（SMS_123456789），注册验证码（SMS_987654321），找回密码（SMS_456789123）。
● 签名：应用名称，通过阿里云审核。
● 发送频率：同一手机号 60s 内限 1 次，每小时 5 次，每天 10 次。
● 验证码有效期：5 分钟，单次使用即失效。
● 验证码长度：6 位数字。
● 登录模式：手机号 + 验证码即可登录（首次即注册）。
● 备用通道：阿里云短信不可用时降级为邮箱验证码。"""
        elif sid == "password_login_spec":
            content = """● 账号字段：支持用户名（3-30字符，字母数字下划线）、邮箱、手机号三种格式登录。
● 注册入口：登录页提供"注册"链接，点击跳转至注册页面。
● 注册验证：手机号或邮箱验证码校验，验证码 5 分钟有效。
● 密码策略：最小长度 8 位，必须包含大写字母、小写字母、数字和特殊字符（@$!%*?&）。
● 密码存储：bcrypt 哈希 + salt（cost factor ≥ 12）。
● 找回密码：支持通过邮箱或手机验证码重置，重置链接有效期 15 分钟。
● 记住登录：支持"记住我"选项（7 天有效，基于 secure httpOnly cookie + refresh token）。
● 防暴力破解：同一账号/IP 连续 5 次失败后要求图形验证码，连续 10 次失败后锁定 15 分钟。"""
        elif sid == "pages_flow_spec":
            content = """● 登录页面：三种登录方式 Tab 切换（账密登录 | 手机验证码 | OAuth 第三方），默认展示账密登录。
● 注册页面：独立页面，手机号 + 验证码 + 设置密码注册。
● 找回密码页面：独立页面，邮箱或手机号 + 验证码 → 设置新密码。
● OAuth 首次登录：授权回调 → 检测是否已绑定 → 未绑定则跳转绑定页（手机号 + 验证码）→ 绑定后完成登录。
● 登录成功：跳转至 redirect 参数指定页面，无参数则跳转 /dashboard。
● 响应式布局：PC 端居中卡片式（max-width 420px），H5 端全屏自适应。
● 状态覆盖：每个页面覆盖 default / loading / error / edge 状态。"""
        elif sid == "nonfunc_spec":
            content = """● 目标平台：Web（PC + H5 响应式，最小支持宽度 320px）。
● 浏览器兼容：Chrome/Firefox/Safari/Edge 最新两个大版本。
● 密码策略：最小 8 位，含大小写 + 数字 + 特殊字符，90 天过期提醒，不可与前 3 次重复。
● 验证码频率：同一手机号/邮箱 60s 内限 1 次，每小时 5 次，每天 10 次。
● 防暴力破解：连续 5 次失败启用图形验证码，10 次失败锁定 15 分钟。
● 传输安全：全站 HTTPS（HSTS），敏感字段（密码、token）AES-256-GCM 加密存储。
● 会话管理：JWT (access token 2h + refresh token 30d)，登出时刷新令牌失效。
● 日志审计：登录成功/失败、密码修改、绑定操作全量记录审计日志。
● 性能指标：登录接口 P99 < 1s，页面首次渲染 < 2s。"""

        new_sections.append({
            "id": sid,
            "title": title,
            "status": "done",
            "content": content,
            "history": s.get("history", []) + [{"time": now_ts, "action": "AI 根据评审反馈补充完善"}],
        })

    spec["sections"] = new_sections
    spec["spec_sections"] = new_sections
    spec["updated_at"] = datetime.now(timezone.utc).isoformat()

    await conn.execute(
        "UPDATE requirements SET spec = $1::jsonb, updated_at = NOW() WHERE id = $2::uuid",
        json.dumps(spec), req_id,
    )
    print(f"Updated {len(new_sections)} sections for {req_id}")

    # Verify
    for s in new_sections:
        print(f"  ✅ {s['id']}: {s['title']}")

    await conn.close()

asyncio.run(main())
