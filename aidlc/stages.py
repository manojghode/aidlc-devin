"""The stage graph.

Stage set, ordering, requires/produces/consumes edges, gates and
include/skip criteria are ported from the source project's core workflow and
rule details. The engine treats this module as data: it never branches on stage
identity, only on the declarations here.

Standard library only.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .model import Cardinality, Gate, Phase, Policy, Stage

WORKSPACE_DETECTION = "workspace_detection"
REVERSE_ENGINEERING = "reverse_engineering"
REQUIREMENTS_ANALYSIS = "requirements_analysis"
USER_STORIES = "user_stories"
WORKFLOW_PLANNING = "workflow_planning"
APPLICATION_DESIGN = "application_design"
UNITS_GENERATION = "units_generation"
FUNCTIONAL_DESIGN = "functional_design"
NFR_REQUIREMENTS = "nfr_requirements"
NFR_DESIGN = "nfr_design"
INFRASTRUCTURE_DESIGN = "infrastructure_design"
CODE_GENERATION = "code_generation"
BUILD_AND_TEST = "build_and_test"
OPERATIONS = "operations"

PART_PLANNING = "planning"
PART_GENERATION = "generation"

STAGES: Tuple[Stage, ...] = (
    Stage(
        id=WORKSPACE_DETECTION,
        title="Workspace Detection",
        phase=Phase.INCEPTION,
        policy=Policy.ALWAYS,
        cardinality=Cardinality.ONCE,
        gate=Gate.AUTO_PROCEED,
        rule_ref="inception/workspace-detection.md",
        produces=("state.file",),
        purpose="Analyze workspace state and project type; create the state file.",
    ),
    Stage(
        id=REVERSE_ENGINEERING,
        title="Reverse Engineering",
        phase=Phase.INCEPTION,
        policy=Policy.CONDITIONAL,
        cardinality=Cardinality.ONCE,
        gate=Gate.APPROVAL,
        rule_ref="inception/reverse-engineering.md",
        requires=(WORKSPACE_DETECTION,),
        produces=(
            "re.business_overview",
            "re.architecture",
            "re.code_structure",
            "re.api_documentation",
            "re.component_inventory",
            "re.technology_stack",
            "re.dependencies",
            "re.code_quality",
            "re.timestamp",
        ),
        include_criteria=(
            "Existing codebase detected (brownfield)",
            "No reverse engineering artifacts exist, or existing artifacts are stale",
            "User explicitly requested a rerun",
        ),
        skip_criteria=(
            "Greenfield project",
            "Current reverse engineering artifacts already exist",
        ),
        purpose="Analyze the existing codebase and document it.",
    ),
    Stage(
        id=REQUIREMENTS_ANALYSIS,
        title="Requirements Analysis",
        phase=Phase.INCEPTION,
        policy=Policy.ALWAYS,
        cardinality=Cardinality.ONCE,
        gate=Gate.QUESTIONS_THEN_APPROVAL,
        rule_ref="inception/requirements-analysis.md",
        requires=(WORKSPACE_DETECTION,),
        soft_requires=(REVERSE_ENGINEERING,),
        optional_consumes=("re.architecture", "re.component_inventory", "re.technology_stack"),
        produces=("req.questions", "req.requirements"),
        questions_artifact="req.questions",
        purpose="Intent analysis, clarifying questions, requirements document.",
    ),
    Stage(
        id=USER_STORIES,
        title="User Stories",
        phase=Phase.INCEPTION,
        policy=Policy.CONDITIONAL,
        cardinality=Cardinality.ONCE,
        gate=Gate.PLAN_THEN_APPROVAL,
        rule_ref="inception/user-stories.md",
        requires=(REQUIREMENTS_ANALYSIS,),
        consumes=("req.requirements",),
        optional_consumes=("re.architecture",),
        produces=("plans.user_stories_assessment", "plans.story_generation",
                  "stories.stories", "stories.personas"),
        parts=(PART_PLANNING, PART_GENERATION),
        questions_artifact="plans.story_generation",
        include_criteria=(
            "New or modified user-facing features or workflows",
            "Multiple user types or personas involved",
            "Complex business requirements needing acceptance criteria",
            "Customer-facing API or service changes",
            "Ambiguity that stories would clarify (default to inclusion when in doubt)",
        ),
        skip_criteria=(
            "Pure internal refactoring with zero user impact",
            "Simple isolated bug fix",
            "Infrastructure-only or tooling-only change",
            "Documentation-only update",
        ),
        purpose="Create user stories (INVEST) and personas.",
    ),
    Stage(
        id=WORKFLOW_PLANNING,
        title="Workflow Planning",
        phase=Phase.INCEPTION,
        policy=Policy.ALWAYS,
        cardinality=Cardinality.ONCE,
        gate=Gate.APPROVAL,
        rule_ref="inception/workflow-planning.md",
        requires=(REQUIREMENTS_ANALYSIS,),
        soft_requires=(USER_STORIES,),
        consumes=("req.requirements",),
        optional_consumes=("stories.stories", "re.architecture"),
        produces=("plans.execution",),
        purpose="Decide which downstream stages execute, at what depth, in what order.",
    ),
    Stage(
        id=APPLICATION_DESIGN,
        title="Application Design",
        phase=Phase.INCEPTION,
        policy=Policy.CONDITIONAL,
        cardinality=Cardinality.ONCE,
        gate=Gate.APPROVAL,
        rule_ref="inception/application-design.md",
        requires=(WORKFLOW_PLANNING,),
        consumes=("req.requirements", "plans.execution"),
        optional_consumes=("stories.stories", "re.architecture"),
        produces=("plans.application_design", "ad.application_design", "ad.components",
                  "ad.component_methods", "ad.services", "ad.component_dependency"),
        questions_artifact="plans.application_design",
        include_criteria=(
            "New components or services are needed",
            "Component methods and business rules need definition",
            "Service layer design is required",
            "Component dependencies need clarification",
        ),
        skip_criteria=(
            "Changes stay within existing component boundaries",
            "No new components or methods",
            "Pure implementation change",
        ),
        purpose="Identify components and design the service layer.",
    ),
    Stage(
        id=UNITS_GENERATION,
        title="Units Generation",
        phase=Phase.INCEPTION,
        policy=Policy.CONDITIONAL,
        cardinality=Cardinality.ONCE,
        gate=Gate.APPROVAL,
        rule_ref="inception/units-generation.md",
        requires=(WORKFLOW_PLANNING,),
        soft_requires=(APPLICATION_DESIGN,),
        consumes=("req.requirements",),
        optional_consumes=("ad.components", "ad.services", "stories.stories"),
        produces=("plans.unit_of_work", "ad.unit_of_work", "ad.unit_of_work_dependency",
                  "ad.unit_of_work_story_map"),
        questions_artifact="plans.unit_of_work",
        include_criteria=(
            "The system needs decomposition into multiple units of work",
            "Multiple services or modules are required",
            "Complex system requiring a structured breakdown",
        ),
        skip_criteria=(
            "Single simple unit",
            "Straightforward single-component implementation",
        ),
        purpose="Decompose the system into units of work with dependencies.",
    ),
    Stage(
        id=FUNCTIONAL_DESIGN,
        title="Functional Design",
        phase=Phase.CONSTRUCTION,
        policy=Policy.CONDITIONAL,
        cardinality=Cardinality.PER_UNIT,
        gate=Gate.APPROVAL,
        rule_ref="construction/functional-design.md",
        requires=(WORKFLOW_PLANNING,),
        soft_requires=(UNITS_GENERATION,),
        consumes=("req.requirements",),
        optional_consumes=("ad.unit_of_work", "ad.unit_of_work_story_map", "stories.stories"),
        produces=("plans.functional_design", "fd.business_logic_model", "fd.business_rules",
                  "fd.domain_entities"),
        questions_artifact="plans.functional_design",
        optional_produces=("fd.frontend_components",),
        include_criteria=(
            "New data models or schemas",
            "Complex business logic",
            "Business rules need detailed design",
        ),
        skip_criteria=("Simple logic changes", "No new business logic"),
        purpose="Detailed business logic design for one unit.",
    ),
    Stage(
        id=NFR_REQUIREMENTS,
        title="NFR Requirements",
        phase=Phase.CONSTRUCTION,
        policy=Policy.CONDITIONAL,
        cardinality=Cardinality.PER_UNIT,
        gate=Gate.APPROVAL,
        rule_ref="construction/nfr-requirements.md",
        requires=(WORKFLOW_PLANNING,),
        soft_requires=(FUNCTIONAL_DESIGN,),
        optional_consumes=("fd.business_logic_model", "req.requirements"),
        produces=("plans.nfr_requirements", "nfrreq.requirements", "nfrreq.tech_stack"),
        questions_artifact="plans.nfr_requirements",
        include_criteria=(
            "Performance requirements exist",
            "Security considerations are needed",
            "Scalability concerns are present",
            "Tech stack selection is required",
        ),
        skip_criteria=("No NFR requirements", "Tech stack already determined"),
        purpose="Determine NFRs and select the tech stack for one unit.",
    ),
    Stage(
        id=NFR_DESIGN,
        title="NFR Design",
        phase=Phase.CONSTRUCTION,
        policy=Policy.CONDITIONAL,
        cardinality=Cardinality.PER_UNIT,
        gate=Gate.APPROVAL,
        rule_ref="construction/nfr-design.md",
        requires=(NFR_REQUIREMENTS,),
        consumes=("nfrreq.requirements", "nfrreq.tech_stack"),
        produces=("plans.nfr_design", "nfrdes.patterns", "nfrdes.logical_components"),
        include_criteria=(
            "NFR Requirements executed for this unit",
            "NFR patterns need to be incorporated",
        ),
        skip_criteria=("NFR Requirements was skipped for this unit",),
        purpose="Incorporate NFR patterns and logical components for one unit.",
    ),
    Stage(
        id=INFRASTRUCTURE_DESIGN,
        title="Infrastructure Design",
        phase=Phase.CONSTRUCTION,
        policy=Policy.CONDITIONAL,
        cardinality=Cardinality.PER_UNIT,
        gate=Gate.APPROVAL,
        rule_ref="construction/infrastructure-design.md",
        requires=(WORKFLOW_PLANNING,),
        soft_requires=(NFR_DESIGN,),
        optional_consumes=("nfrdes.patterns", "nfrdes.logical_components"),
        produces=("plans.infrastructure_design", "infra.design", "infra.deployment"),
        include_criteria=(
            "Infrastructure services need mapping",
            "Deployment architecture is required",
            "Cloud resources need specification",
        ),
        skip_criteria=("No infrastructure changes", "Infrastructure already defined"),
        purpose="Map the unit's logical components to infrastructure services.",
    ),
    Stage(
        id=CODE_GENERATION,
        title="Code Generation",
        phase=Phase.CONSTRUCTION,
        policy=Policy.ALWAYS,
        cardinality=Cardinality.PER_UNIT,
        gate=Gate.PLAN_THEN_APPROVAL,
        rule_ref="construction/code-generation.md",
        requires=(WORKFLOW_PLANNING,),
        soft_requires=(FUNCTIONAL_DESIGN, NFR_REQUIREMENTS, NFR_DESIGN, INFRASTRUCTURE_DESIGN),
        optional_consumes=("fd.business_logic_model", "fd.business_rules", "fd.domain_entities",
                           "fd.frontend_components", "nfrreq.tech_stack", "nfrdes.patterns",
                           "infra.design", "ad.unit_of_work_story_map", "re.code_structure"),
        produces=("plans.code_generation", "code.summaries"),
        parts=(PART_PLANNING, PART_GENERATION),
        purpose="Plan then generate code, tests and artifacts for one unit.",
    ),
    Stage(
        id=BUILD_AND_TEST,
        title="Build and Test",
        phase=Phase.CONSTRUCTION,
        policy=Policy.ALWAYS,
        cardinality=Cardinality.ONCE,
        gate=Gate.APPROVAL,
        rule_ref="construction/build-and-test.md",
        requires=(CODE_GENERATION,),
        consumes=("code.summaries",),
        produces=("bt.build", "bt.unit_tests", "bt.integration_tests", "bt.summary"),
        optional_produces=("bt.performance_tests", "bt.contract_tests", "bt.security_tests",
                           "bt.e2e_tests"),
        purpose="Build all units and execute comprehensive testing.",
    ),
    Stage(
        id=OPERATIONS,
        title="Operations",
        phase=Phase.OPERATIONS,
        policy=Policy.PLACEHOLDER,
        cardinality=Cardinality.ONCE,
        gate=Gate.NONE,
        rule_ref="operations/operations.md",
        requires=(BUILD_AND_TEST,),
        purpose="Placeholder for deployment and monitoring workflows.",
    ),
)

ORDER: Tuple[str, ...] = tuple(s.id for s in STAGES)
BY_ID: Dict[str, Stage] = {s.id: s for s in STAGES}

#: Stages whose approval gate presents the standardized two-option message.
#: The source forbids emergent three-option menus in construction stages.
TWO_OPTION_STAGES: Tuple[str, ...] = (
    FUNCTIONAL_DESIGN, NFR_REQUIREMENTS, NFR_DESIGN, INFRASTRUCTURE_DESIGN, CODE_GENERATION,
)

COMPLETION_OPTIONS: Tuple[str, ...] = ("Request Changes", "Continue to Next Stage")


def get(stage_id: str) -> Stage:
    try:
        return BY_ID[stage_id]
    except KeyError as exc:  # pragma: no cover - defensive
        raise KeyError(f"unknown stage id: {stage_id}") from exc


def index(stage_id: str) -> int:
    return ORDER.index(stage_id)


def per_unit_stages() -> Tuple[Stage, ...]:
    return tuple(s for s in STAGES if s.per_unit)


def predecessors(stage_id: str) -> Tuple[str, ...]:
    stage = get(stage_id)
    return tuple(stage.requires) + tuple(stage.soft_requires)


def validate_graph() -> List[str]:
    """Structural invariants. Returns a list of problems (empty when healthy)."""

    problems: List[str] = []
    from . import artifacts as artifacts_module

    for stage in STAGES:
        for dep in predecessors(stage.id):
            if dep not in BY_ID:
                problems.append(f"{stage.id}: unknown dependency {dep}")
                continue
            if index(dep) >= index(stage.id):
                problems.append(f"{stage.id}: dependency {dep} is not earlier in the order")
        for field_name in ("consumes", "optional_consumes", "produces", "optional_produces"):
            for artifact_id in getattr(stage, field_name):
                if artifact_id not in artifacts_module.BY_ID:
                    problems.append(f"{stage.id}.{field_name}: unknown artifact {artifact_id}")
                    continue
                artifact = artifacts_module.get(artifact_id)
                if artifact.per_unit and not stage.per_unit and field_name.endswith("produces"):
                    problems.append(
                        f"{stage.id}: produces per-unit artifact {artifact_id} "
                        "from a once-only stage"
                    )
        if stage.policy is Policy.CONDITIONAL and not stage.include_criteria:
            problems.append(f"{stage.id}: conditional stage without include criteria")
        if stage.policy is Policy.ALWAYS and stage.include_criteria:
            problems.append(f"{stage.id}: unconditional stage declares include criteria")
    return problems


def next_stage_after(stage_id: Optional[str]) -> Optional[str]:
    if stage_id is None:
        return ORDER[0]
    i = index(stage_id)
    return ORDER[i + 1] if i + 1 < len(ORDER) else None
