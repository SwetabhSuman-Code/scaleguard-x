"""
Role-Based Access Control (RBAC) system.

Implements hierarchical role management with permission scope enforcement.
Supports multiple roles per user and fine-grained permission checking.

Role Hierarchy:
  - admin: Full access to all resources
  - operator: Can manage workloads and scaling
  - viewer: Read-only access
  - service: Machine-to-machine access for services
  - guest: Limited read-only access
"""

import logging
from typing import Set, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class Permission(str, Enum):
    """Available permission scopes."""
    
    # Metrics & Monitoring
    METRICS_READ = "metrics:read"
    METRICS_WRITE = "metrics:write"
    
    # Scaling & Autoscaling
    SCALING_READ = "scaling:read"
    SCALING_WRITE = "scaling:write"
    SCALING_EXECUTE = "scaling:execute"
    
    # Predictions
    PREDICTIONS_READ = "predictions:read"
    PREDICTIONS_WRITE = "predictions:write"
    
    # System Configuration
    CONFIG_READ = "config:read"
    CONFIG_WRITE = "config:write"
    CONFIG_ADMIN = "config:admin"
    
    # User & Access Management
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    USER_ADMIN = "user:admin"
    
    # Logs & Diagnostics
    LOGS_READ = "logs:read"
    LOGS_ADMIN = "logs:admin"
    
    # Services
    SERVICE_HEALTH = "service:health"
    SERVICE_SHUTDOWN = "service:shutdown"


@dataclass
class Role:
    """Role definition with permissions."""
    name: str
    description: str
    permissions: Set[Permission] = field(default_factory=set)

    def add_permission(self, permission: Permission) -> None:
        """Add permission to role."""
        self.permissions.add(permission)

    def remove_permission(self, permission: Permission) -> None:
        """Remove permission from role."""
        self.permissions.discard(permission)

    def has_permission(self, permission: Permission) -> bool:
        """Check if role has permission."""
        return permission in self.permissions

    def __repr__(self) -> str:
        return f"Role({self.name}, perms={len(self.permissions)})"


class AccessControl:
    """
    Access control decision based on roles and permissions.
    
    Attributes:
        user_id: User identifier
        roles: List of assigned role names
        permissions: Accumulated permissions from all roles
    """

    def __init__(self, user_id: str, roles: List[str]):
        """
        Initialize access control.
        
        Args:
            user_id: User identifier
            roles: List of role names
        """
        self.user_id = user_id
        self.roles = roles
        self.permissions: Set[Permission] = set()

    def has_permission(self, permission: Permission) -> bool:
        """Check if user has permission."""
        return permission in self.permissions

    def has_any_permission(self, permissions: List[Permission]) -> bool:
        """Check if user has any of the given permissions."""
        return any(p in self.permissions for p in permissions)

    def has_all_permissions(self, permissions: List[Permission]) -> bool:
        """Check if user has all given permissions."""
        return all(p in self.permissions for p in permissions)

    def add_permissions(self, permissions: Set[Permission]) -> None:
        """Add permissions (from role)."""
        self.permissions.update(permissions)

    def __repr__(self) -> str:
        return f"AccessControl(user={self.user_id}, roles={self.roles})"


class RBACManager:
    """
    Manager for roles and access control.
    
    Maintains role definitions and evaluates access decisions based on
    user roles and required permissions.
    
    Attributes:
        roles: Dict of role name -> Role instance
        _default_roles: Built-in role definitions
    """

    def __init__(self):
        """Initialize RBAC manager with default roles."""
        self.roles: Dict[str, Role] = {}
        self._init_default_roles()
        logger.info("RBAC Manager initialized with default roles")

    def _init_default_roles(self) -> None:
        """Initialize default roles with standard permissions."""
        
        # Admin: Full access
        admin_role = Role(
            name="admin",
            description="Full system access"
        )
        for perm in Permission:
            admin_role.add_permission(perm)
        self.register_role(admin_role)

        # Operator: Manage workloads and scaling
        operator_role = Role(
            name="operator",
            description="Manage scaling and workloads"
        )
        operator_permissions = [
            Permission.METRICS_READ,
            Permission.SCALING_READ,
            Permission.SCALING_WRITE,
            Permission.SCALING_EXECUTE,
            Permission.PREDICTIONS_READ,
            Permission.SERVICE_HEALTH,
        ]
        for perm in operator_permissions:
            operator_role.add_permission(perm)
        self.register_role(operator_role)

        # Viewer: Read-only access
        viewer_role = Role(
            name="viewer",
            description="Read-only monitoring access"
        )
        viewer_permissions = [
            Permission.METRICS_READ,
            Permission.SCALING_READ,
            Permission.PREDICTIONS_READ,
            Permission.SERVICE_HEALTH,
        ]
        for perm in viewer_permissions:
            viewer_role.add_permission(perm)
        self.register_role(viewer_role)

        # Service: Machine-to-machine access
        service_role = Role(
            name="service",
            description="Service-to-service authentication"
        )
        service_permissions = [
            Permission.METRICS_READ,
            Permission.METRICS_WRITE,
            Permission.SCALING_READ,
            Permission.PREDICTIONS_READ,
            Permission.PREDICTIONS_WRITE,
            Permission.SERVICE_HEALTH,
        ]
        for perm in service_permissions:
            service_role.add_permission(perm)
        self.register_role(service_role)

        # Guest: Very limited read-only
        guest_role = Role(
            name="guest",
            description="Limited public read access"
        )
        guest_permissions = [
            Permission.METRICS_READ,
            Permission.SERVICE_HEALTH,
        ]
        for perm in guest_permissions:
            guest_role.add_permission(perm)
        self.register_role(guest_role)

    def register_role(self, role: Role) -> None:
        """
        Register a role.
        
        Args:
            role: Role instance to register
        """
        self.roles[role.name] = role
        logger.debug(f"Role registered: {role.name}")

    def unregister_role(self, role_name: str) -> None:
        """
        Unregister a role.
        
        Args:
            role_name: Name of role to remove
        """
        if role_name in self.roles:
            del self.roles[role_name]
            logger.debug(f"Role unregistered: {role_name}")

    def get_role(self, role_name: str) -> Optional[Role]:
        """
        Get role by name.
        
        Args:
            role_name: Role name
        
        Returns:
            Role instance or None if not found
        """
        return self.roles.get(role_name)

    def evaluate_access(
        self,
        user_id: str,
        role_names: List[str],
        required_permission: Permission,
    ) -> AccessControl:
        """
        Evaluate access for user with given roles.
        
        Args:
            user_id: User identifier
            role_names: List of role names
            required_permission: Permission to check (for validation)
        
        Returns:
            AccessControl instance with accumulated permissions
        """
        access = AccessControl(user_id, role_names)

        for role_name in role_names:
            role = self.get_role(role_name)
            if role:
                access.add_permissions(role.permissions)
            else:
                logger.warning(f"Unknown role requested: {role_name}")

        has_access = access.has_permission(required_permission)
        log_level = logging.DEBUG if has_access else logging.WARNING
        logger.log(
            log_level,
            f"Access evaluation: user={user_id}, roles={role_names}, "
            f"required={required_permission.value}, granted={has_access}"
        )

        return access

    def has_access(
        self,
        user_id: str,
        role_names: List[str],
        required_permission: Permission,
    ) -> bool:
        """
        Check if user has required permission.
        
        Args:
            user_id: User identifier
            role_names: List of role names
            required_permission: Required permission
        
        Returns:
            True if user has permission, False otherwise
        """
        access = self.evaluate_access(user_id, role_names, required_permission)
        return access.has_permission(required_permission)

    def get_role_permissions(self, role_name: str) -> Set[Permission]:
        """
        Get all permissions for a role.
        
        Args:
            role_name: Role name
        
        Returns:
            Set of permissions
        """
        role = self.get_role(role_name)
        return role.permissions if role else set()

    def get_user_permissions(self, role_names: List[str]) -> Set[Permission]:
        """
        Get accumulated permissions from multiple roles.
        
        Args:
            role_names: List of role names
        
        Returns:
            Combined set of permissions
        """
        permissions: Set[Permission] = set()
        for role_name in role_names:
            role = self.get_role(role_name)
            if role:
                permissions.update(role.permissions)
        return permissions

    def add_custom_role(
        self,
        role_name: str,
        description: str,
        permissions: List[Permission],
    ) -> Role:
        """
        Create and register a custom role.
        
        Args:
            role_name: Name for new role
            description: Role description
            permissions: List of permissions
        
        Returns:
            Registered Role instance
        """
        role = Role(
            name=role_name,
            description=description,
            permissions=set(permissions)
        )
        self.register_role(role)
        return role

    def list_roles(self) -> List[Role]:
        """
        List all registered roles.
        
        Returns:
            List of Role instances
        """
        return list(self.roles.values())

    def list_permissions(self) -> List[Permission]:
        """
        List all available permissions.
        
        Returns:
            List of Permission enum values
        """
        return list(Permission)

    def get_role_graph(self) -> Dict[str, Dict[str, any]]:
        """
        Get role definitions for documentation.
        
        Returns:
            Dict mapping role names to metadata
        """
        return {
            role.name: {
                "description": role.description,
                "permissions": [p.value for p in role.permissions],
                "permission_count": len(role.permissions),
            }
            for role in self.roles.values()
        }
