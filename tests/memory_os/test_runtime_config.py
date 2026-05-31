from core.memory_os.runtime_config import (
    MemoryOSRuntimeConfig,
    RuntimeAdapterSelection,
    RuntimePolicy,
    TenantMode,
)


def test_local_runtime_config_defaults_are_explicit(tmp_path):
    config = MemoryOSRuntimeConfig.local(tmp_path)

    assert config.tenant_mode is TenantMode.LOCAL_SINGLE_USER
    assert config.data_root == tmp_path
    assert config.object_root == tmp_path / "objects"
    assert config.ledger_path == tmp_path / "ledger.sqlite3"
    assert config.vector_root == tmp_path / "lance"
    assert config.graph_root == tmp_path / "kuzu"
    assert config.adapters == RuntimeAdapterSelection.local_defaults()
    assert config.policy == RuntimePolicy.local_defaults()
    assert config.policy.daemon_only_writes is True
    assert config.policy.allow_legacy_fallback is True
    assert config.policy.require_tenant_id is False


def test_constructor_defaults_to_local_single_user_mode(tmp_path):
    config = MemoryOSRuntimeConfig(tmp_path)

    assert config.tenant_mode is TenantMode.LOCAL_SINGLE_USER
    assert config.as_dict()["tenant_mode"] == "local_single_user"


def test_self_hosted_admin_config_uses_local_runtime_adapters(tmp_path):
    config = MemoryOSRuntimeConfig.self_hosted_admin(tmp_path)

    assert config.tenant_mode is TenantMode.SELF_HOSTED_ADMIN
    assert config.adapters == RuntimeAdapterSelection.local_defaults()
    assert config.policy == RuntimePolicy.self_hosted_admin_defaults()
    assert config.as_dict()["tenant_mode"] == "self_hosted_admin"
