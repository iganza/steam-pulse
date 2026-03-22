# Task: Refactor the config system in config.py

## Requirements

1. Loads config from env-specific `.env` files during deployment/development
2. Loads config from environment variables at runtime (e.g. Lambda)
3. Supports multiple environments (staging, production, etc.)
4. Provides type safety and validation
5. Code should never reference environment variables directly — all access goes through an instance of `GlobalConfig`
6. Lambda should obtain an instance of `GlobalConfig` via:

```python
config = GlobalConfig.config
```

where `config` is a cached instance of the config object.

## Implementation

### 1. Create config.py with these components

**`GlobalConfig` (BaseSettings)**
- Base configuration model with all application settings
- Use Pydantic `BaseSettings` for automatic environment variable loading
- Includes proper types: `str`, `int`, `float`, `bool`, `list[str]`, `Literal`
- No `model_config` at base level — subclasses define env files

**Environment-specific subclasses**

```python
class StagingConfig(GlobalConfig):
    model_config = SettingsConfigDict(env_file=".env.staging")

class ProductionConfig(GlobalConfig):
    model_config = SettingsConfigDict(env_file=".env.production")
```

**`ConfigFactory`**
- Takes an optional `env` parameter (defaults to `ENVIRONMENT` env var)
- Returns the appropriate config subclass based on environment
- Simple if/elif logic to instantiate the correct config class

**Helper functions**
- `GlobalConfig.from_env()` — class method to load from `os.environ` (for runtime)
- `set_test_config()` — utility to set environment variables for testing

### 2. Usage patterns

**During deployment (CDK/infra code):**

```python
config = ConfigFactory.staging_config()  # Load from .env.staging
```

**At runtime (Lambda):**

```python
config = ConfigFactory.from_env()  # Loads from os.environ
```

**In tests:**

```python
config = set_test_config(env="staging")
```

## Key design principles

1. Single source of truth — one config model, not separate models for different contexts
2. Pydantic handles coercion — environment variables (strings) auto-convert to proper types
3. Environment isolation — each environment has its own `.env` file
4. Type safety — use proper Pydantic types, not string literals for everything
5. Simple factory — no complex logic, just environment-based instantiation

## Example fields

- `ENVIRONMENT: Literal["staging", "production"]`
- `AWS_ACCOUNT: str`
- `REGION: str`
- `LOG_LEVEL: Literal[...]`
- Feature flags as `bool`
- Numeric config as `int` or `float`
- Names for configuration stored in Parameter Store, e.g. `/steampulse/staging/`


