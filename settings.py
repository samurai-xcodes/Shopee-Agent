import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str = 'sqlite:///./data/agent.db'
    storage_dir: Path = Path('data/assets')
    checkpoint_path: str = 'data/checkpoints.db'
    auth_mode: str = 'dev'
    api_tokens: dict[str, str] = field(default_factory=dict, repr=False)
    provider: str = 'mock'
    text_model: str = 'gpt-4.1-mini'
    image_model: str = 'gpt-image-1'
    image_provider: str = 'openai'
    image_api_key: str = field(default='', repr=False)
    image_base_url: str = 'https://api.siliconflow.cn/v1'
    max_attempts: int = 3
    lease_seconds: int = 600
    queue_limit: int = 100
    requests_per_minute: int = 20
    tasks_per_day: int = 100
    provider_timeout: float = 60.0

    def __post_init__(self):
        if self.auth_mode not in {'dev', 'token'}:
            raise ValueError('AUTH_MODE must be dev or token')
        if self.auth_mode == 'token' and not self.api_tokens:
            raise ValueError('API_TOKENS_JSON is required in token mode')
        if not isinstance(self.api_tokens, dict) or any(
            not isinstance(owner, str) or not owner or len(owner) > 100 or
            not isinstance(token, str) or len(token) < 24
            for owner, token in self.api_tokens.items()
        ):
            raise ValueError('API tokens must contain at least 24 characters')
        if len(set(self.api_tokens.values())) != len(self.api_tokens):
            raise ValueError('API tokens must be unique per owner')
        if self.provider not in {'mock', 'openai'}:
            raise ValueError('PROVIDER must be mock or openai')
        if self.image_provider not in {'openai', 'siliconflow'}:
            raise ValueError('IMAGE_PROVIDER must be openai or siliconflow')
        if min(self.max_attempts, self.lease_seconds, self.queue_limit,
               self.requests_per_minute, self.tasks_per_day, self.provider_timeout) <= 0:
            raise ValueError('Limits and timeouts must be positive')

    @classmethod
    def from_env(cls):
        load_dotenv(Path(__file__).with_name('.env'), override=False)
        return cls(
            database_url=os.getenv('DATABASE_URL', cls.database_url),
            storage_dir=Path(os.getenv('STORAGE_DIR', 'data/assets')),
            checkpoint_path=os.getenv('CHECKPOINT_PATH', cls.checkpoint_path),
            auth_mode=os.getenv('AUTH_MODE', 'dev'),
            api_tokens=json.loads(os.getenv('API_TOKENS_JSON', '{}')),
            provider=os.getenv('PROVIDER', 'mock'),
            text_model=os.getenv('OPENAI_TEXT_MODEL', cls.text_model),
            image_model=os.getenv('OPENAI_IMAGE_MODEL', cls.image_model),
            # 修改人：wangjinwei
            # 修改日期：2026-10-20
            # 修改说明：图片服务使用独立凭据，保留文本服务原有配置。
            image_provider=os.getenv('IMAGE_PROVIDER', cls.image_provider),
            image_api_key=os.getenv('IMAGE_API_KEY', ''),
            image_base_url=os.getenv('IMAGE_BASE_URL', cls.image_base_url),
            max_attempts=int(os.getenv('MAX_ATTEMPTS', '3')),
            lease_seconds=int(os.getenv('LEASE_SECONDS', '600')),
            queue_limit=int(os.getenv('QUEUE_LIMIT', '100')),
            requests_per_minute=int(os.getenv('REQUESTS_PER_MINUTE', '20')),
            tasks_per_day=int(os.getenv('TASKS_PER_DAY', '100')),
            provider_timeout=float(os.getenv('PROVIDER_TIMEOUT', '60')),
        )
