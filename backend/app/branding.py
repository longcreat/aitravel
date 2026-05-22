"""品牌与产品名称常量。

把所有面向用户/外部系统暴露的品牌字符串集中到这里，方便日后整体改名或多
品牌部署。其他模块只应通过 import 引用，不要再各自硬编码。
"""

from __future__ import annotations

# 产品品牌名（出现在系统提示词、connector OAuth 注册名等处）。
BRAND_NAME = "WANDER AI"

# 业务领域名（系统提示词中描述助手定位时使用）。
DOMAIN_NAME = "旅行规划"

# 邮箱注册自动生成昵称失败时（local-part 为空白）使用的占位昵称。
DEFAULT_USER_NICKNAME = "旅行用户"

# LangSmith tracing 通用 tag，用于在 LangSmith 控制台筛选本应用请求。
APP_TRACE_TAG = "ai-travel-agent"

# OAuth 动态注册（RFC 7591）时附在第三方应用名后面的标识，让授权页能让
# 用户辨识是哪家产品在请求授权。
OAUTH_CLIENT_NAME_SUFFIX = "AI Travel"
