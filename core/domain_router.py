"""Domain-agnostic multi-domain auto-router and department ACL gate (`core/domain_router.py`)."""

from __future__ import annotations

import os

from domains.base import DomainPlugin, DomainRegistry


class DomainAccessDeniedError(PermissionError):
    """Raised when a caller is not authorized to query a restricted company domain."""


def parse_domain_acl(raw_acl: str | None = None) -> dict[str, list[str]]:
    """Parse `SMRITI_DOMAIN_ACL` (`domain_a:user@x.com|@dept.com;domain_b:lead@x.com`)."""
    cfg = (raw_acl if raw_acl is not None else os.getenv("SMRITI_DOMAIN_ACL", "")).strip()
    if not cfg:
        return {}

    acl_map: dict[str, list[str]] = {}
    for block in cfg.split(";"):
        if ":" not in block:
            continue
        dom, rules_str = block.split(":", 1)
        dom_id = dom.strip().lower()
        rules = [r.strip().lower() for r in rules_str.split("|") if r.strip()]
        if dom_id and rules:
            acl_map[dom_id] = rules
    return acl_map


def is_caller_allowed_for_domain(
    caller_wif: str,
    domain_id: str,
    *,
    acl_map: dict[str, list[str]] | None = None,
) -> bool:
    """Return True if `domain_id` has no restriction or `caller_wif` matches its ACL."""
    effective_acl = acl_map if acl_map is not None else parse_domain_acl()
    norm_domain = domain_id.strip().lower()
    allowed_entries = effective_acl.get(norm_domain)
    if not allowed_entries:
        return True

    norm_caller = caller_wif.strip().lower()
    if not norm_caller or norm_caller == "anonymous":
        return False

    for rule in allowed_entries:
        if rule == "*":
            return True
        if rule.startswith("@") and norm_caller.endswith(rule):
            return True
        if norm_caller == rule:
            return True
    return False


def resolve_domain_for_query(
    question: str,
    *,
    domain_hint: str | None,
    caller_wif: str,
    registry: DomainRegistry,
    default_domain: str | None = None,
    raw_acl: str | None = None,
) -> DomainPlugin:
    """Automatically select the target DomainPlugin behind a single unified Smriti agent."""
    if domain_hint and domain_hint.strip():
        chosen = registry.resolve(domain_hint.strip(), fallback_default=default_domain)
    else:
        best_plugin: DomainPlugin | None = None
        best_score = 0
        for dom_id in registry.list_domains():
            candidate = registry.resolve(dom_id)
            scorer = getattr(candidate, "score_domain_match", None)
            if callable(scorer):
                score = int(scorer(question))
                if score > best_score:
                    best_score = score
                    best_plugin = candidate
        chosen = best_plugin or registry.resolve(None, fallback_default=default_domain)

    acl_map = parse_domain_acl(raw_acl)
    if not is_caller_allowed_for_domain(caller_wif, chosen.domain_id, acl_map=acl_map):
        raise DomainAccessDeniedError(
            f"Access restricted: '{caller_wif}' does not have permission for domain "
            f"'{chosen.domain_id}'."
        )
    return chosen
