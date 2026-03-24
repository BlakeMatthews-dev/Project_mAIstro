"""Tests for agent framework modules: agent_spec, schemas, structured_output, recipe.

Covers:
  - AgentSpec: with_defaults() role→prompt_name mapping, default tools per role
  - AgentOutput: mark_complete() duration calculation, mark_error() recoverable classification
  - Lane / AgentRole / ErrorType enum values and membership
  - RECOVERABLE_ERRORS set contents
  - Schema models: PlanOutput, CodeOutput, ReviewOutput field validation
  - ReviewScores boundary enforcement (0-10 range)
  - SCHEMA_REGISTRY completeness and resolve_schema() with registry + importlib fallback
  - StructuredOutputParser: inject_schema(), parse() with 3 extraction strategies, format_retry_context()
  - _extract_json: direct JSON, markdown blocks, embedded objects, failure cases
  - AgentRecipe: Pydantic validation, defaults, role enum coercion
  - RecipeRegistry: YAML round-trip, caching, name→filename, list_recipes(), missing dir
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("orchestrator")

from orchestrator.agents.agent_spec import (
    RECOVERABLE_ERRORS,
    DEFAULT_TOOLS,
    AgentOutput,
    AgentRole,
    AgentSpec,
    ErrorType,
    Lane,
)
from orchestrator.agents.schemas import (
    SCHEMA_REGISTRY,
    CodeOutput,
    FileChange,
    PlanOutput,
    PlanSubtask,
    ReviewOutput,
    ReviewScores,
    resolve_schema,
)
from orchestrator.agents.structured_output import (
    StructuredOutputParser,
    _extract_json,
)
from orchestrator.agents.recipe import AgentRecipe, RecipeRegistry


# =====================================================================
# Lane / AgentRole / ErrorType enums
# =====================================================================


class TestEnums:
    def test_lane_values(self):
        assert Lane.LIVE == "live-chat"
        assert Lane.BACKGROUND == "background-task"

    def test_agent_role_values(self):
        assert AgentRole.PLANNER == "planner"
        assert AgentRole.CODER == "coder"
        assert AgentRole.REVIEWER == "reviewer"
        assert AgentRole.CONVERSATION == "conversation"

    def test_error_type_values(self):
        assert ErrorType.TIMEOUT == "timeout"
        assert ErrorType.SAFETY_VIOLATION == "safety_violation"

    def test_recoverable_errors_contains_expected(self):
        assert ErrorType.TIMEOUT in RECOVERABLE_ERRORS
        assert ErrorType.PARSE_FAILURE in RECOVERABLE_ERRORS
        assert ErrorType.MODEL_ERROR in RECOVERABLE_ERRORS
        assert ErrorType.LOW_SCORE in RECOVERABLE_ERRORS

    def test_non_recoverable_not_in_set(self):
        assert ErrorType.SAFETY_VIOLATION not in RECOVERABLE_ERRORS
        assert ErrorType.TOOL_VIOLATION not in RECOVERABLE_ERRORS
        assert ErrorType.DEPENDENCY_FAILED not in RECOVERABLE_ERRORS

    def test_recoverable_errors_exactly_four(self):
        assert len(RECOVERABLE_ERRORS) == 4


# =====================================================================
# DEFAULT_TOOLS
# =====================================================================


class TestDefaultTools:
    def test_planner_has_read_only_tools(self):
        tools = DEFAULT_TOOLS[AgentRole.PLANNER]
        assert "file_ops.read" in tools
        assert "file_ops.write" not in tools
        assert "shell.run" not in tools

    def test_coder_has_write_tools(self):
        tools = DEFAULT_TOOLS[AgentRole.CODER]
        assert "file_ops.write" in tools
        assert "shell.run" in tools

    def test_reviewer_is_read_only(self):
        tools = DEFAULT_TOOLS[AgentRole.REVIEWER]
        assert "file_ops.read" in tools
        assert "file_ops.write" not in tools

    def test_intent_router_has_no_tools(self):
        assert DEFAULT_TOOLS[AgentRole.INTENT_ROUTER] == []

    def test_conversation_has_no_tools(self):
        assert DEFAULT_TOOLS[AgentRole.CONVERSATION] == []

    def test_all_roles_have_entry(self):
        for role in AgentRole:
            assert role in DEFAULT_TOOLS


# =====================================================================
# AgentSpec
# =====================================================================


class TestAgentSpec:
    def _make_spec(self, role: AgentRole = AgentRole.CODER, **kwargs) -> AgentSpec:
        defaults = dict(role=role, task_id="t1", subtask_id="s1", description="do stuff")
        defaults.update(kwargs)
        return AgentSpec(**defaults)

    def test_auto_generates_agent_id(self):
        spec = self._make_spec()
        assert spec.agent_id.startswith("agent-")
        assert len(spec.agent_id) == len("agent-") + 8

    def test_with_defaults_fills_prompt_name_planner(self):
        spec = self._make_spec(role=AgentRole.PLANNER).with_defaults()
        assert spec.prompt_name == "planner.decompose"

    def test_with_defaults_fills_prompt_name_coder(self):
        spec = self._make_spec(role=AgentRole.CODER).with_defaults()
        assert spec.prompt_name == "coder.generate"

    def test_with_defaults_fills_prompt_name_reviewer(self):
        spec = self._make_spec(role=AgentRole.REVIEWER).with_defaults()
        assert spec.prompt_name == "reviewer.score"

    def test_with_defaults_no_prompt_name_for_unmapped_role(self):
        spec = self._make_spec(role=AgentRole.CONVERSATION).with_defaults()
        assert spec.prompt_name is None

    def test_with_defaults_fills_tools_from_role(self):
        spec = self._make_spec(role=AgentRole.CODER).with_defaults()
        assert spec.tools_allowed == DEFAULT_TOOLS[AgentRole.CODER]

    def test_with_defaults_does_not_overwrite_existing_tools(self):
        custom_tools = ["my_tool.special"]
        spec = self._make_spec(tools_allowed=custom_tools).with_defaults()
        assert spec.tools_allowed == custom_tools

    def test_with_defaults_does_not_overwrite_existing_prompt_name(self):
        spec = self._make_spec(prompt_name="custom.prompt").with_defaults()
        assert spec.prompt_name == "custom.prompt"

    def test_with_defaults_returns_self(self):
        spec = self._make_spec()
        result = spec.with_defaults()
        assert result is spec

    def test_default_lane_is_background(self):
        spec = self._make_spec()
        assert spec.lane == Lane.BACKGROUND

    def test_default_tier_is_2(self):
        spec = self._make_spec()
        assert spec.tier == 2

    def test_default_attempt_is_1(self):
        spec = self._make_spec()
        assert spec.attempt == 1

    def test_context_defaults_to_empty_dict(self):
        spec = self._make_spec()
        assert spec.context == {}

    def test_exemplar_defaults(self):
        spec = self._make_spec()
        assert spec.exemplar_count == 2
        assert spec.exemplar_min_score == 7.0


# =====================================================================
# AgentOutput
# =====================================================================


class TestAgentOutput:
    def _make_output(self, **kwargs) -> AgentOutput:
        defaults = dict(
            agent_id="agent-test1234",
            role=AgentRole.CODER,
            task_id="t1",
            subtask_id="s1",
        )
        defaults.update(kwargs)
        return AgentOutput(**defaults)

    def test_mark_complete_sets_completed_at(self):
        out = self._make_output()
        assert out.completed_at is None
        out.mark_complete()
        assert out.completed_at is not None
        assert isinstance(out.completed_at, datetime)

    def test_mark_complete_calculates_positive_duration(self):
        out = self._make_output()
        # Sleep briefly to ensure measurable duration
        time.sleep(0.005)
        out.mark_complete()
        assert out.duration_ms > 0

    def test_mark_complete_duration_is_reasonable(self):
        out = self._make_output()
        out.mark_complete()
        # Should complete nearly instantly (< 1 second)
        assert out.duration_ms < 1000

    def test_mark_error_sets_fields(self):
        out = self._make_output()
        out.mark_error("boom", ErrorType.TIMEOUT)
        assert out.success is False
        assert out.error == "boom"
        assert out.error_type == ErrorType.TIMEOUT

    def test_mark_error_recoverable_for_timeout(self):
        out = self._make_output()
        out.mark_error("timed out", ErrorType.TIMEOUT)
        assert out.recoverable is True

    def test_mark_error_recoverable_for_parse_failure(self):
        out = self._make_output()
        out.mark_error("bad json", ErrorType.PARSE_FAILURE)
        assert out.recoverable is True

    def test_mark_error_not_recoverable_for_safety_violation(self):
        out = self._make_output()
        out.mark_error("unsafe", ErrorType.SAFETY_VIOLATION)
        assert out.recoverable is False

    def test_mark_error_not_recoverable_for_tool_violation(self):
        out = self._make_output()
        out.mark_error("bad tool", ErrorType.TOOL_VIOLATION)
        assert out.recoverable is False

    def test_mark_error_not_recoverable_for_dependency_failed(self):
        out = self._make_output()
        out.mark_error("dep fail", ErrorType.DEPENDENCY_FAILED)
        assert out.recoverable is False

    def test_mark_error_sets_escalation_reason(self):
        out = self._make_output()
        out.mark_error("low", ErrorType.LOW_SCORE, escalation_reason="score was 3.2")
        assert out.escalation_reason == "score was 3.2"
        assert out.recoverable is True

    def test_mark_error_calls_mark_complete(self):
        out = self._make_output()
        out.mark_error("err", ErrorType.MODEL_ERROR)
        assert out.completed_at is not None
        assert out.duration_ms >= 0

    def test_default_success_is_true(self):
        out = self._make_output()
        assert out.success is True

    def test_started_at_is_utc(self):
        out = self._make_output()
        assert out.started_at.tzinfo is not None


# =====================================================================
# Schemas — ReviewScores boundary validation
# =====================================================================


class TestReviewScores:
    def test_valid_scores(self):
        scores = ReviewScores(
            correctness=5.0, quality=7.5, safety=10.0, completeness=0.0, overall=6.0
        )
        assert scores.correctness == 5.0
        assert scores.safety == 10.0
        assert scores.completeness == 0.0

    def test_score_below_zero_rejected(self):
        with pytest.raises(Exception):  # ValidationError
            ReviewScores(
                correctness=-0.1, quality=5.0, safety=5.0, completeness=5.0, overall=5.0
            )

    def test_score_above_ten_rejected(self):
        with pytest.raises(Exception):
            ReviewScores(
                correctness=5.0, quality=10.1, safety=5.0, completeness=5.0, overall=5.0
            )

    def test_boundary_zero(self):
        scores = ReviewScores(
            correctness=0, quality=0, safety=0, completeness=0, overall=0
        )
        assert scores.overall == 0

    def test_boundary_ten(self):
        scores = ReviewScores(
            correctness=10, quality=10, safety=10, completeness=10, overall=10
        )
        assert scores.overall == 10


class TestPlanOutput:
    def test_empty_subtasks(self):
        plan = PlanOutput(subtasks=[])
        assert plan.subtasks == []
        assert plan.reasoning == ""

    def test_with_subtasks(self):
        st = PlanSubtask(id="step-1", description="do thing")
        plan = PlanOutput(subtasks=[st], reasoning="because")
        assert len(plan.subtasks) == 1
        assert plan.subtasks[0].id == "step-1"

    def test_subtask_defaults(self):
        st = PlanSubtask(id="s1", description="d")
        assert st.agent_role == "coder"
        assert st.depends_on == []


class TestCodeOutput:
    def test_defaults(self):
        out = CodeOutput()
        assert out.files_modified == []
        assert out.summary == ""
        assert out.tests_added is False

    def test_with_file_changes(self):
        fc = FileChange(path="src/main.py", action="modify", description="added func")
        out = CodeOutput(files_modified=[fc], summary="did stuff", tests_added=True)
        assert len(out.files_modified) == 1
        assert out.tests_added is True


class TestReviewOutput:
    def test_requires_scores(self):
        with pytest.raises(Exception):
            ReviewOutput()  # scores is required

    def test_valid_review(self):
        scores = ReviewScores(
            correctness=8, quality=7, safety=9, completeness=8, overall=8
        )
        review = ReviewOutput(scores=scores, approved=True, feedback="looks good")
        assert review.approved is True
        assert review.selected_candidate == 0


# =====================================================================
# SCHEMA_REGISTRY and resolve_schema
# =====================================================================


class TestSchemaRegistry:
    def test_registry_has_all_schemas(self):
        expected = {
            "schemas.PlanOutput",
            "schemas.CodeOutput",
            "schemas.ReviewOutput",
            "schemas.PlanSubtask",
            "schemas.FileChange",
            "schemas.ReviewScores",
        }
        assert set(SCHEMA_REGISTRY.keys()) == expected

    def test_registry_values_are_classes(self):
        for cls in SCHEMA_REGISTRY.values():
            assert isinstance(cls, type)

    def test_resolve_schema_from_registry(self):
        assert resolve_schema("schemas.PlanOutput") is PlanOutput
        assert resolve_schema("schemas.ReviewScores") is ReviewScores

    def test_resolve_schema_unknown_returns_none(self):
        assert resolve_schema("nonexistent.Module") is None

    def test_resolve_schema_importlib_fallback(self):
        # json.JSONDecodeError is not a BaseModel — should return None
        result = resolve_schema("json.JSONDecodeError")
        assert result is None

    def test_resolve_schema_importlib_with_real_basemodel(self):
        # pydantic.BaseModel itself is a BaseModel subclass
        result = resolve_schema("pydantic.BaseModel")
        assert result is not None

    def test_resolve_schema_invalid_dotted_path_no_dot(self):
        assert resolve_schema("nodot") is None

    def test_resolve_schema_bad_module(self):
        assert resolve_schema("totally_fake_module_xyz.SomeClass") is None


# =====================================================================
# StructuredOutputParser
# =====================================================================


class TestExtractJson:
    """Tests for the _extract_json helper function."""

    def test_direct_json_object(self):
        raw = '{"key": "value"}'
        assert _extract_json(raw) == raw

    def test_direct_json_array(self):
        raw = '[{"a": 1}]'
        assert _extract_json(raw) == raw

    def test_direct_json_with_whitespace(self):
        raw = '  \n  {"key": "value"}  \n  '
        result = _extract_json(raw)
        assert json.loads(result) == {"key": "value"}

    def test_markdown_code_block_json(self):
        raw = 'Here is the output:\n```json\n{"answer": 42}\n```\nDone.'
        result = _extract_json(raw)
        assert json.loads(result) == {"answer": 42}

    def test_markdown_code_block_no_language(self):
        raw = 'Output:\n```\n{"answer": 42}\n```'
        result = _extract_json(raw)
        assert json.loads(result) == {"answer": 42}

    def test_embedded_json_in_text(self):
        raw = 'The result is {"score": 8.5, "pass": true} and that is all.'
        result = _extract_json(raw)
        assert json.loads(result) == {"score": 8.5, "pass": True}

    def test_no_json_returns_none(self):
        assert _extract_json("no json here at all") is None

    def test_invalid_json_returns_none(self):
        assert _extract_json("{invalid json without quotes}") is None

    def test_empty_string_returns_none(self):
        assert _extract_json("") is None

    def test_nested_json(self):
        obj = {"outer": {"inner": [1, 2, 3]}, "flag": True}
        raw = json.dumps(obj)
        result = _extract_json(raw)
        assert json.loads(result) == obj

    def test_json_with_surrounding_prose(self):
        raw = 'Sure! Here you go:\n\n{"files_modified": [], "summary": "nothing"}\n\nHope that helps!'
        result = _extract_json(raw)
        parsed = json.loads(result)
        assert parsed["summary"] == "nothing"


class TestStructuredOutputParser:
    def test_inject_schema_appends_instruction(self):
        parser = StructuredOutputParser()
        prompt = "You are an assistant."
        result = parser.inject_schema(prompt, ReviewScores)
        assert result.startswith("You are an assistant.")
        assert "Required Output Format" in result
        assert "correctness" in result  # from schema

    def test_inject_schema_includes_json_schema(self):
        parser = StructuredOutputParser()
        result = parser.inject_schema("sys", CodeOutput)
        # Should contain the schema in a code block
        assert "```json" in result
        assert "files_modified" in result

    def test_parse_valid_json(self):
        parser = StructuredOutputParser()
        raw = json.dumps({
            "correctness": 8.0,
            "quality": 7.0,
            "safety": 9.0,
            "completeness": 8.0,
            "overall": 8.0,
        })
        result = parser.parse(raw, ReviewScores)
        assert isinstance(result, ReviewScores)
        assert result.correctness == 8.0

    def test_parse_from_markdown_block(self):
        parser = StructuredOutputParser()
        raw = '```json\n{"correctness": 5, "quality": 5, "safety": 5, "completeness": 5, "overall": 5}\n```'
        result = parser.parse(raw, ReviewScores)
        assert result.overall == 5.0

    def test_parse_from_embedded_json(self):
        parser = StructuredOutputParser()
        raw = 'I think the scores are: {"correctness": 6, "quality": 6, "safety": 6, "completeness": 6, "overall": 6} based on review.'
        result = parser.parse(raw, ReviewScores)
        assert result.correctness == 6.0

    def test_parse_raises_value_error_no_json(self):
        parser = StructuredOutputParser()
        with pytest.raises(ValueError, match="Could not extract JSON"):
            parser.parse("no json here", ReviewScores)

    def test_parse_raises_validation_error_bad_schema(self):
        parser = StructuredOutputParser()
        # Valid JSON but wrong schema (correctness > 10)
        raw = json.dumps({
            "correctness": 15,
            "quality": 5,
            "safety": 5,
            "completeness": 5,
            "overall": 5,
        })
        with pytest.raises(Exception):  # ValidationError
            parser.parse(raw, ReviewScores)

    def test_parse_plan_output(self):
        parser = StructuredOutputParser()
        raw = json.dumps({
            "subtasks": [
                {"id": "step-1", "description": "implement feature"},
            ],
            "reasoning": "simple task",
        })
        result = parser.parse(raw, PlanOutput)
        assert isinstance(result, PlanOutput)
        assert len(result.subtasks) == 1
        assert result.subtasks[0].id == "step-1"

    def test_format_retry_context_validation_error(self):
        parser = StructuredOutputParser()
        try:
            ReviewScores(correctness=-1, quality=5, safety=5, completeness=5, overall=5)
        except Exception as e:
            ctx = parser.format_retry_context(e)
            assert "validation errors" in ctx
            assert "correctness" in ctx

    def test_format_retry_context_value_error(self):
        parser = StructuredOutputParser()
        err = ValueError("Could not extract JSON from response")
        ctx = parser.format_retry_context(err)
        assert "could not be parsed as JSON" in ctx
        assert "valid JSON" in ctx

    def test_max_retries_stored(self):
        parser = StructuredOutputParser(max_retries=5)
        assert parser.max_retries == 5


# =====================================================================
# AgentRecipe
# =====================================================================


class TestAgentRecipe:
    def test_minimal_recipe(self):
        recipe = AgentRecipe(
            name="coder.python",
            role=AgentRole.CODER,
            prompt_name="coder.generate",
        )
        assert recipe.name == "coder.python"
        assert recipe.role == AgentRole.CODER

    def test_defaults(self):
        recipe = AgentRecipe(
            name="test", role=AgentRole.PLANNER, prompt_name="planner.decompose"
        )
        assert recipe.prompt_variants == ["production"]
        assert recipe.result_schema is None
        assert recipe.tools == []
        assert recipe.min_tier == 2
        assert recipe.max_tier == 4
        assert recipe.temperature == 0.7
        assert recipe.max_tokens == 4096
        assert recipe.min_samples_before_selection == 20
        assert recipe.exploration_rate == 0.1
        assert recipe.description == ""

    def test_role_from_string(self):
        recipe = AgentRecipe(
            name="test", role="coder", prompt_name="coder.generate"
        )
        assert recipe.role == AgentRole.CODER

    def test_missing_required_fields_raises(self):
        with pytest.raises(Exception):
            AgentRecipe(role=AgentRole.CODER, prompt_name="coder.generate")  # missing name

    def test_custom_values(self):
        recipe = AgentRecipe(
            name="custom",
            role=AgentRole.REVIEWER,
            prompt_name="reviewer.score",
            prompt_variants=["v1", "v2"],
            result_schema="schemas.ReviewOutput",
            tools=["file_ops.read"],
            min_tier=1,
            max_tier=3,
            temperature=0.3,
            max_tokens=8192,
        )
        assert recipe.prompt_variants == ["v1", "v2"]
        assert recipe.min_tier == 1
        assert recipe.max_tokens == 8192


# =====================================================================
# RecipeRegistry
# =====================================================================


class TestRecipeRegistry:
    def test_get_returns_none_for_missing(self, tmp_path):
        reg = RecipeRegistry(tmp_path)
        assert reg.get("nonexistent") is None

    def test_register_and_get(self, tmp_path):
        reg = RecipeRegistry(tmp_path)
        recipe = AgentRecipe(
            name="test.recipe", role=AgentRole.CODER, prompt_name="coder.generate"
        )
        reg.register(recipe)
        assert reg.get("test.recipe") is recipe

    def test_save_creates_yaml_file(self, tmp_path):
        reg = RecipeRegistry(tmp_path)
        recipe = AgentRecipe(
            name="coder.python", role=AgentRole.CODER, prompt_name="coder.generate"
        )
        path = reg.save(recipe)
        assert path.exists()
        assert path.name == "coder_python.yaml"

    def test_save_and_load_round_trip(self, tmp_path):
        reg = RecipeRegistry(tmp_path)
        recipe = AgentRecipe(
            name="planner.decompose",
            role=AgentRole.PLANNER,
            prompt_name="planner.decompose",
            description="Plan decomposition",
            temperature=0.5,
            max_tokens=2048,
        )
        reg.save(recipe)

        # New registry instance — forces disk load
        reg2 = RecipeRegistry(tmp_path)
        loaded = reg2.get("planner.decompose")
        assert loaded is not None
        assert loaded.name == "planner.decompose"
        assert loaded.role == AgentRole.PLANNER
        assert loaded.temperature == 0.5
        assert loaded.max_tokens == 2048

    def test_name_to_filename_conversion(self, tmp_path):
        reg = RecipeRegistry(tmp_path)
        recipe = AgentRecipe(
            name="scout.research.deep", role=AgentRole.SCOUT, prompt_name="scout.explore"
        )
        path = reg.save(recipe)
        assert path.name == "scout_research_deep.yaml"

    def test_caching_returns_same_object(self, tmp_path):
        reg = RecipeRegistry(tmp_path)
        recipe = AgentRecipe(
            name="cached", role=AgentRole.CODER, prompt_name="coder.generate"
        )
        reg.save(recipe)
        first = reg.get("cached")
        second = reg.get("cached")
        assert first is second  # same object from cache

    def test_list_recipes_empty_dir(self, tmp_path):
        reg = RecipeRegistry(tmp_path)
        assert reg.list_recipes() == []

    def test_list_recipes_finds_all(self, tmp_path):
        reg = RecipeRegistry(tmp_path)
        for i in range(3):
            recipe = AgentRecipe(
                name=f"recipe.{i}",
                role=AgentRole.CODER,
                prompt_name="coder.generate",
            )
            reg.save(recipe)

        # New registry to clear cache
        reg2 = RecipeRegistry(tmp_path)
        recipes = reg2.list_recipes()
        assert len(recipes) == 3
        names = {r.name for r in recipes}
        assert names == {"recipe.0", "recipe.1", "recipe.2"}

    def test_list_recipes_nonexistent_dir(self, tmp_path):
        reg = RecipeRegistry(tmp_path / "does_not_exist")
        assert reg.list_recipes() == []

    def test_get_nonexistent_dir(self, tmp_path):
        reg = RecipeRegistry(tmp_path / "nope")
        assert reg.get("anything") is None

    def test_invalid_yaml_returns_none(self, tmp_path):
        # Write garbage YAML
        bad_file = tmp_path / "bad_recipe.yaml"
        bad_file.write_text("this is not: valid: yaml: [[[", encoding="utf-8")
        reg = RecipeRegistry(tmp_path)
        # Attempting to load by scan should not crash
        result = reg.get("bad_recipe")
        # Should return None gracefully (bad YAML or missing required fields)
        assert result is None

    def test_yaml_missing_required_fields_returns_none(self, tmp_path):
        import yaml

        incomplete = tmp_path / "incomplete.yaml"
        incomplete.write_text(
            yaml.dump({"role": "coder"}),  # missing name, prompt_name
            encoding="utf-8",
        )
        reg = RecipeRegistry(tmp_path)
        assert reg.get("incomplete") is None

    def test_save_creates_directory_if_needed(self, tmp_path):
        nested = tmp_path / "sub" / "recipes"
        reg = RecipeRegistry(nested)
        recipe = AgentRecipe(
            name="nested.test", role=AgentRole.CODER, prompt_name="coder.generate"
        )
        path = reg.save(recipe)
        assert path.exists()
        assert nested.exists()

    def test_scan_fallback_finds_recipe_with_mismatched_filename(self, tmp_path):
        import yaml

        # Save recipe under a non-standard filename
        data = {
            "name": "special.recipe",
            "role": "reviewer",
            "prompt_name": "reviewer.score",
        }
        weird_file = tmp_path / "my_weird_name.yaml"
        weird_file.write_text(yaml.dump(data), encoding="utf-8")

        reg = RecipeRegistry(tmp_path)
        result = reg.get("special.recipe")
        assert result is not None
        assert result.name == "special.recipe"
