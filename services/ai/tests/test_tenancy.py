import pytest

from app.tenancy import TenantValidationError, schema_for, validate_tenant_id


def test_valid_tenant_id_roundtrip():
    tid = "0b6a1f2e-3c4d-45e6-8f90-abcdefabcdef"
    assert validate_tenant_id(tid) == tid
    assert validate_tenant_id(tid.upper()) == tid  # normalized to lowercase


def test_schema_derivation():
    tid = "0b6a1f2e-3c4d-45e6-8f90-abcdefabcdef"
    assert schema_for(tid) == "tenant_0b6a1f2e3c4d45e68f90abcdefabcdef"


@pytest.mark.parametrize("bad", [
    "", "not-a-uuid", "0b6a1f2e-3c4d-45e6-8f90",           # malformed
    "0b6a1f2e-3c4d-45e6-8f90-abcdefabcdef; DROP SCHEMA",   # injection
    'tenant_x", public; --',                                 # smuggling
    "0b6a1f2e-3c4d-45e6-8f90-abcdefabcdeg",                 # non-hex
    None, 42,
])
def test_invalid_tenant_ids_rejected(bad):
    with pytest.raises((TenantValidationError, TypeError)):
        validate_tenant_id(bad)  # type: ignore[arg-type]
