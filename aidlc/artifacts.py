"""Artifact registry.

Paths are taken verbatim from the source project's generated-docs reference so
that an ``aidlc-docs/`` tree produced by this engine is byte-for-byte
interchangeable with one produced by the original rulebook.

Standard library only.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

from .model import Artifact

DOCS_ROOT = "aidlc-docs"

_ARTIFACTS: Tuple[Artifact, ...] = (
    # --- tracking -----------------------------------------------------------
    Artifact("state.file", f"{DOCS_ROOT}/aidlc-state.md",
             description="Workflow state tracker"),
    Artifact("audit.file", f"{DOCS_ROOT}/audit.md",
             description="Append-only audit trail"),

    # --- inception plans ----------------------------------------------------
    Artifact("plans.execution", f"{DOCS_ROOT}/inception/plans/execution-plan.md",
             description="Workflow visualization and phase execution decisions"),
    Artifact("plans.story_generation",
             f"{DOCS_ROOT}/inception/plans/story-generation-plan.md",
             description="Story development methodology and questions"),
    Artifact("plans.user_stories_assessment",
             f"{DOCS_ROOT}/inception/plans/user-stories-assessment.md",
             description="Assessment of whether user stories add value"),
    Artifact("plans.application_design",
             f"{DOCS_ROOT}/inception/plans/application-design-plan.md",
             description="Component and service design plan with questions"),
    Artifact("plans.unit_of_work",
             f"{DOCS_ROOT}/inception/plans/unit-of-work-plan.md",
             description="System decomposition plan with questions"),

    # --- reverse engineering (brownfield) -----------------------------------
    Artifact("re.business_overview",
             f"{DOCS_ROOT}/inception/reverse-engineering/business-overview.md"),
    Artifact("re.architecture",
             f"{DOCS_ROOT}/inception/reverse-engineering/architecture.md"),
    Artifact("re.code_structure",
             f"{DOCS_ROOT}/inception/reverse-engineering/code-structure.md"),
    Artifact("re.api_documentation",
             f"{DOCS_ROOT}/inception/reverse-engineering/api-documentation.md"),
    Artifact("re.component_inventory",
             f"{DOCS_ROOT}/inception/reverse-engineering/component-inventory.md"),
    Artifact("re.technology_stack",
             f"{DOCS_ROOT}/inception/reverse-engineering/technology-stack.md"),
    Artifact("re.dependencies",
             f"{DOCS_ROOT}/inception/reverse-engineering/dependencies.md"),
    Artifact("re.code_quality",
             f"{DOCS_ROOT}/inception/reverse-engineering/code-quality-assessment.md"),
    Artifact("re.timestamp",
             f"{DOCS_ROOT}/inception/reverse-engineering/reverse-engineering-timestamp.md"),

    # --- requirements -------------------------------------------------------
    Artifact("req.questions",
             f"{DOCS_ROOT}/inception/requirements/requirement-verification-questions.md",
             description="Clarifying questions with [Answer]: tags"),
    Artifact("req.requirements",
             f"{DOCS_ROOT}/inception/requirements/requirements.md"),

    # --- user stories -------------------------------------------------------
    Artifact("stories.stories", f"{DOCS_ROOT}/inception/user-stories/stories.md"),
    Artifact("stories.personas", f"{DOCS_ROOT}/inception/user-stories/personas.md"),

    # --- application design / units ----------------------------------------
    Artifact("ad.application_design",
             f"{DOCS_ROOT}/inception/application-design/application-design.md"),
    Artifact("ad.components",
             f"{DOCS_ROOT}/inception/application-design/components.md"),
    Artifact("ad.component_methods",
             f"{DOCS_ROOT}/inception/application-design/component-methods.md"),
    Artifact("ad.services",
             f"{DOCS_ROOT}/inception/application-design/services.md"),
    Artifact("ad.component_dependency",
             f"{DOCS_ROOT}/inception/application-design/component-dependency.md"),
    Artifact("ad.unit_of_work",
             f"{DOCS_ROOT}/inception/application-design/unit-of-work.md"),
    Artifact("ad.unit_of_work_dependency",
             f"{DOCS_ROOT}/inception/application-design/unit-of-work-dependency.md"),
    Artifact("ad.unit_of_work_story_map",
             f"{DOCS_ROOT}/inception/application-design/unit-of-work-story-map.md"),

    # --- construction plans (per unit) --------------------------------------
    Artifact("plans.functional_design",
             f"{DOCS_ROOT}/construction/plans/{{unit}}-functional-design-plan.md",
             per_unit=True),
    Artifact("plans.nfr_requirements",
             f"{DOCS_ROOT}/construction/plans/{{unit}}-nfr-requirements-plan.md",
             per_unit=True),
    Artifact("plans.nfr_design",
             f"{DOCS_ROOT}/construction/plans/{{unit}}-nfr-design-plan.md",
             per_unit=True),
    Artifact("plans.infrastructure_design",
             f"{DOCS_ROOT}/construction/plans/{{unit}}-infrastructure-design-plan.md",
             per_unit=True),
    Artifact("plans.code_generation",
             f"{DOCS_ROOT}/construction/plans/{{unit}}-code-generation-plan.md",
             per_unit=True,
             description="Code generation steps with [ ] checkboxes"),

    # --- per-unit design ----------------------------------------------------
    Artifact("fd.business_logic_model",
             f"{DOCS_ROOT}/construction/{{unit}}/functional-design/business-logic-model.md",
             per_unit=True),
    Artifact("fd.business_rules",
             f"{DOCS_ROOT}/construction/{{unit}}/functional-design/business-rules.md",
             per_unit=True),
    Artifact("fd.domain_entities",
             f"{DOCS_ROOT}/construction/{{unit}}/functional-design/domain-entities.md",
             per_unit=True),
    Artifact("fd.frontend_components",
             f"{DOCS_ROOT}/construction/{{unit}}/functional-design/frontend-components.md",
             per_unit=True, required=False),
    Artifact("nfrreq.requirements",
             f"{DOCS_ROOT}/construction/{{unit}}/nfr-requirements/nfr-requirements.md",
             per_unit=True),
    Artifact("nfrreq.tech_stack",
             f"{DOCS_ROOT}/construction/{{unit}}/nfr-requirements/tech-stack-decisions.md",
             per_unit=True),
    Artifact("nfrdes.patterns",
             f"{DOCS_ROOT}/construction/{{unit}}/nfr-design/nfr-design-patterns.md",
             per_unit=True),
    Artifact("nfrdes.logical_components",
             f"{DOCS_ROOT}/construction/{{unit}}/nfr-design/logical-components.md",
             per_unit=True),
    Artifact("infra.design",
             f"{DOCS_ROOT}/construction/{{unit}}/infrastructure-design/infrastructure-design.md",
             per_unit=True),
    Artifact("infra.deployment",
             f"{DOCS_ROOT}/construction/{{unit}}/infrastructure-design/deployment-architecture.md",
             per_unit=True),
    Artifact("code.summaries", f"{DOCS_ROOT}/construction/{{unit}}/code",
             per_unit=True, is_dir=True,
             description="Markdown summaries of generated code"),

    # --- build and test -----------------------------------------------------
    Artifact("bt.build", f"{DOCS_ROOT}/construction/build-and-test/build-instructions.md"),
    Artifact("bt.unit_tests",
             f"{DOCS_ROOT}/construction/build-and-test/unit-test-instructions.md"),
    Artifact("bt.integration_tests",
             f"{DOCS_ROOT}/construction/build-and-test/integration-test-instructions.md"),
    Artifact("bt.performance_tests",
             f"{DOCS_ROOT}/construction/build-and-test/performance-test-instructions.md",
             required=False),
    Artifact("bt.contract_tests",
             f"{DOCS_ROOT}/construction/build-and-test/contract-test-instructions.md",
             required=False),
    Artifact("bt.security_tests",
             f"{DOCS_ROOT}/construction/build-and-test/security-test-instructions.md",
             required=False),
    Artifact("bt.e2e_tests",
             f"{DOCS_ROOT}/construction/build-and-test/e2e-test-instructions.md",
             required=False),
    Artifact("bt.summary",
             f"{DOCS_ROOT}/construction/build-and-test/build-and-test-summary.md"),
)

BY_ID: Dict[str, Artifact] = {a.id: a for a in _ARTIFACTS}

STATE_PATH = BY_ID["state.file"].path
AUDIT_PATH = BY_ID["audit.file"].path

#: Written by the recorder, never by a stage — stage artifact checks skip these.
RECORDER_OWNED: Tuple[str, ...] = ("state.file", "audit.file")


def get(artifact_id: str) -> Artifact:
    try:
        return BY_ID[artifact_id]
    except KeyError as exc:  # pragma: no cover - defensive
        raise KeyError(f"unknown artifact id: {artifact_id}") from exc


def resolve(artifact_id: str, unit: Optional[str] = None) -> str:
    return get(artifact_id).resolve(unit)


def resolve_many(artifact_ids: Iterable[str], unit: Optional[str] = None) -> Tuple[str, ...]:
    return tuple(resolve(a, unit) for a in artifact_ids)


def all_artifacts() -> Tuple[Artifact, ...]:
    return _ARTIFACTS
