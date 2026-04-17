"""项目统一配置与 LLM 客户端初始化。支持多 API 提供商切换。"""

import os

try:
    from openai import OpenAI
except ImportError as exc:
    raise RuntimeError("缺少 openai 依赖，请先安装 openai 包。") from exc

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

# ========== API 提供商选择 ==========
# 可选值：ecnu, custom
API_PROVIDER = os.getenv("API_PROVIDER", "ecnu").lower()

# ========== 通用配置 ==========
REQUEST_TIMEOUT_SECONDS = int(os.getenv("OPENAI_TIMEOUT_SECONDS", "60"))
TTS_TIMEOUT_SECONDS = int(os.getenv("TTS_TIMEOUT_SECONDS", "60"))

if API_PROVIDER == "ecnu":
    # ========== ECNU 配置 ==========
    API_KEY = os.getenv("OPENAI_API_KEY")
    BASE_URL = os.getenv("OPENAI_BASE_URL", "https://chat.ecnu.edu.cn/open/api/v1")
    MODEL_NAME = os.getenv("OPENAI_MODEL", "ecnu-max")

    # TTS 配置
    TTS_MODEL = os.getenv("ECNU_TTS_MODEL", "ecnu-tts")
    DEFAULT_VOICE = os.getenv("ECNU_DEFAULT_VOICE", "xiayu")
    TTS_API_URL = f"{BASE_URL}/audio/speech"

    if not API_KEY:
        raise ValueError(
            "未读取到 OPENAI_API_KEY，请检查环境变量或 .env 文件。"
            "\n提示：可以复制 .env.example 为 .env 并填入你的 API Key。"
        )

    print(f"[配置] 使用 ECNU API: {BASE_URL}")

elif API_PROVIDER == "custom":
    # ========== 自定义 API 配置 ==========
    API_KEY = os.getenv("CUSTOM_API_KEY")
    BASE_URL = os.getenv("CUSTOM_BASE_URL")
    MODEL_NAME = os.getenv("CUSTOM_MODEL", "gpt-3.5-turbo")

    # 自定义 API 的 TTS 配置（如不支持 TTS，可设为 None）
    TTS_MODEL = os.getenv("CUSTOM_TTS_MODEL", None)
    DEFAULT_VOICE = os.getenv("CUSTOM_DEFAULT_VOICE", None)
    TTS_API_URL = os.getenv("CUSTOM_TTS_URL", None)

    if not API_KEY or not BASE_URL:
        raise ValueError(
            "自定义 API 模式下，需要设置 CUSTOM_API_KEY 和 CUSTOM_BASE_URL。"
            "\n提示：参考 .env.example 中的自定义 API 配置示例。"
        )

    print(f"[配置] 使用自定义 API: {BASE_URL}")

else:
    raise ValueError(
        f"未知的 API_PROVIDER: {API_PROVIDER}。"
        "\n可选值：ecnu, custom"
    )

# 初始化 OpenAI 客户端
client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL,
)

# ========== 导出配置变量 ==========
__all__ = [
    "API_PROVIDER",
    "API_KEY",
    "BASE_URL",
    "MODEL_NAME",
    "REQUEST_TIMEOUT_SECONDS",
    "TTS_TIMEOUT_SECONDS",
    "TTS_MODEL",
    "DEFAULT_VOICE",
    "TTS_API_URL",
    "client",
]