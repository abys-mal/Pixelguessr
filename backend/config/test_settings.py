import os

os.environ["DEBUG"] = "True"
os.environ["USE_SQLITE"] = "True"
os.environ["LOCAL_SERVICES"] = "True"
os.environ["DJANGO_SECRET_KEY"] = "dev-tests-only-never-use-in-production"

from .settings import *  # noqa: F403, E402

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
if os.environ.get("TEST_DATABASE_URL"):
    DATABASES = {"default": env.db("TEST_DATABASE_URL")}  # noqa: F405
if os.environ.get("TEST_REDIS_URL"):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": os.environ["TEST_REDIS_URL"],
        }
    }
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [os.environ["TEST_REDIS_URL"]]},
        }
    }
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
