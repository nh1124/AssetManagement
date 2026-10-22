"""Administrator capability vocabulary. No framework or persistence dependencies."""
from .errors import Invalid

ACCOUNTS_READ = "accounts.read"
ACCOUNTS_MANAGE = "accounts.manage"
ACCOUNTS_CREDENTIALS = "accounts.credentials"
ACCOUNTS_EXPORT = "accounts.export"
ACCOUNTS_DELETE = "accounts.delete"
HEALTH_READ = "health.read"
HEALTH_REPAIR = "health.repair"
AUDIT_READ = "audit.read"
SETTINGS_MANAGE = "settings.manage"
OPS_READ = "ops.read"
OPS_RUN = "ops.run"
ADMINS_MANAGE = "admins.manage"
ALL_PERMISSIONS = frozenset({
    ACCOUNTS_READ, ACCOUNTS_MANAGE, ACCOUNTS_CREDENTIALS, ACCOUNTS_EXPORT,
    ACCOUNTS_DELETE, HEALTH_READ, HEALTH_REPAIR, AUDIT_READ, SETTINGS_MANAGE,
    OPS_READ, OPS_RUN, ADMINS_MANAGE,
})
STEP_UP_REQUIRED = frozenset({
    ACCOUNTS_CREDENTIALS, ACCOUNTS_EXPORT, ACCOUNTS_DELETE, HEALTH_REPAIR,
    SETTINGS_MANAGE, OPS_RUN, ADMINS_MANAGE,
})
PRESETS = {
    "owner": ALL_PERMISSIONS,
    "support": frozenset({ACCOUNTS_READ, ACCOUNTS_MANAGE, HEALTH_READ, AUDIT_READ}),
    "viewer": frozenset(p for p in ALL_PERMISSIONS if p.endswith(".read")),
}


def validate_permissions(permissions) -> frozenset[str]:
    values = frozenset(permissions)
    if not values <= ALL_PERMISSIONS:
        raise Invalid("Unknown administrator permission.", ja="不明な管理者権限です。")
    return values
