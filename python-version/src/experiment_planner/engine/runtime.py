"""Pinned-version offline runtime compatibility settings."""
import importlib.metadata


def configure_offline_runtime():
    # BoTorch 0.18.1 tries local JIT compilation in qLogNEHVI's constructor.
    # Explicitly select its shipped pure-Python fallback. Keep this narrowly
    # version-gated and test it when upgrading; no downloads/compilers at runtime.
    if importlib.metadata.version("botorch") != "0.18.1":
        raise RuntimeError("未验证的 BoTorch 版本；请使用本版本依赖锁")
    from botorch.acquisition.multi_objective import logei
    logei._C = None
    logei._load_attempted = True
