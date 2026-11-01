export function canInitiatePublish(role) {
  return role === "admin";
}

export function canOverridePublish(role, readiness) {
  return role === "admin" && readiness?.can_override === true;
}
