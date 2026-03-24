"""
Conductor Orchestrator — Core Loop.

The main event loop that ties everything together:

1. Watch Obsidian inbox for tasks
2. Load project context via gateway
3. Planner decomposes task
4. For each subtask:
   - Estimate tier (heuristic)
   - Ultra Think generate candidates
   - Reviewer scores and selects
   - Apply candidate via file_ops
   - Run tests
   - Retry/escalate if needed
5. Write changelog entry
6. Record training data
7. Move task to completed/failed in Obsidian
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from . import _gateway_auth
from .agents.abra import Abra, DeviceRegistry
from .agents.agent_spec import RECOVERABLE_ERRORS, AgentRole, AgentSpec, Lane
from .agents.bouncer import Bouncer, Verdict
from .agents.intent_router import Intent, IntentRouter
from .agents.recipe import RecipeRegistry
from .agents.spawner import Spawner
from .agents.variant_selector import VariantSelector
from .coder import Coder
from .config import OrchestratorConfig
from .heartbeat import Heartbeat
from .interfaces.obsidian_watcher import ObsidianWatcher
from .interfaces.vault_sync import create_sync_adapter
from .memory.apm import AgentPersonalityMatrix
from .memory.board import MessageBoard
from .memory.changelog import Changelog, ChangelogEntry
from .memory.episodic import EpisodicMemory
from .memory.evolution import EvolutionHistory
from .memory.knowledge_graph import KnowledgeGraph
from .memory.layer0 import Layer0
from .memory.layer1 import Layer1
from .memory.layer2 import Layer2
from .planner import Planner
from .progress import ProgressReporter
from .reviewer import Reviewer
from .tools.file_ops import FileOps
from .tools.git import Git
from .tools.shell import Shell
from .tools.test_runner import TestRunner
from .training.data_collector import CandidateRecord, DataCollector, TrainingRow
from .training.exemplar_library import Exemplar, ExemplarLibrary

logger = logging.getLogger(__name__)
console = Console()


class Conductor:
    def __init__(self, config: OrchestratorConfig) -> None:
        self._config = config

        # Memory stack
        self._layer0 = Layer0(config.layer0_path)
        self._layer1 = Layer1(max_tokens=config.max_working_memory_tokens)
        self._layer2 = Layer2()
        self._changelog = Changelog(
            log_path=str(Path(config.training_data_dir).parent / "changelog.jsonl")
        )
        self._knowledge = KnowledgeGraph()

        # Agents
        self._bouncer = Bouncer(
            routing_api_base=config.routing_api_base or config.gateway_url,
            routing_api_key=config.routing_api_key or "",
            routing_model=config.routing_model or "auto",
        )
        self._intent_router = IntentRouter(
            gateway_url=config.gateway_url,
            routing_model=config.routing_model or None,
            routing_provider=config.routing_provider or None,
            routing_api_key=config.routing_api_key or None,
            routing_api_base=config.routing_api_base or None,
        )
        self._abra = Abra(
            registry=DeviceRegistry(
                alexa_map=config.ha_alexa_device_map or {},
            ),
            ha_url=config.ha_url,
            ha_token=config.ha_token,
        )
        self._planner = Planner(config.gateway_url)
        self._coder = Coder(config.gateway_url)
        self._reviewer = Reviewer(config.gateway_url, config.accept_threshold)

        # Tools
        self._file_ops = FileOps(config.project_dir)
        self._shell = Shell(config.project_dir)
        self._git = Git(config.project_dir)
        self._test_runner = TestRunner(config.project_dir)

        # Training
        self._data_collector = DataCollector(config.training_data_dir)
        self._exemplar_library = ExemplarLibrary(config.exemplar_library_dir)

        # Prompt management
        from .prompts.prompt_manager import PromptManager
        self._prompt_manager = PromptManager()

        # Langfuse tracer (optional — no-ops if unavailable)
        try:
            from ..gateway.langfuse_tracer import tracer as _gateway_tracer
            self._langfuse_tracer = _gateway_tracer
        except Exception:
            self._langfuse_tracer = None

        # Progress reporter — sends live status to the dashboard
        self._progress = ProgressReporter(
            router_url=config.routing_api_base or "http://localhost:8100",
            api_key=config.routing_api_key,
        )

        # Agent Factory — recipe registry + variant selector
        self._recipe_registry = RecipeRegistry()
        self._variant_selector = VariantSelector()

        # Agent spawner — wraps gateway calls with contracts, tracing, exemplars
        self._spawner = Spawner(
            gateway_url=config.gateway_url,
            prompt_manager=self._prompt_manager,
            exemplar_library=self._exemplar_library,
            langfuse_tracer=self._langfuse_tracer,
            variant_selector=self._variant_selector,
            recipe_registry=self._recipe_registry,
        )

        # Persistent surfaces
        memory_dir = Path(config.obsidian_vault).parent / "memory"
        self._apm = AgentPersonalityMatrix(memory_dir / "apm.yaml")
        self._episodic_memory = EpisodicMemory(
            dsn="postgresql://langfuse:langfuse@localhost:5432/conductor"
        )
        self._board = MessageBoard(config.obsidian_vault)
        self._evolution = EvolutionHistory(memory_dir)

        # Heartbeat — autonomous initiative loop
        self._heartbeat = Heartbeat(
            apm=self._apm,
            episodic_memory=self._episodic_memory,
            board=self._board,
            evolution=self._evolution,
            recipe_registry=self._recipe_registry,
            interval_minutes=30,
        )

        # Vault sync adapter (local, git, syncthing, or couchdb)
        sync_adapter = create_sync_adapter(
            mode=config.vault_sync_mode,
            vault_path=config.obsidian_vault,
            git_remote=config.vault_sync_git_remote,
            git_branch=config.vault_sync_git_branch,
            syncthing_api=config.vault_sync_syncthing_api,
            syncthing_api_key=config.vault_sync_syncthing_api_key,
            syncthing_folder_id=config.vault_sync_syncthing_folder_id,
            couchdb_url=config.vault_sync_couchdb_url,
            couchdb_database=config.vault_sync_couchdb_database,
            couchdb_username=config.vault_sync_couchdb_username,
            couchdb_password=config.vault_sync_couchdb_password,
            couchdb_conductor_prefix=config.vault_sync_couchdb_conductor_prefix,
        )

        # Obsidian interface
        self._watcher = ObsidianWatcher(
            vault_path=config.obsidian_vault,
            layer0_path=config.layer0_path,
            on_new_task=self._handle_new_task,
            on_constraints_changed=self._handle_constraints_changed,
            sync_adapter=sync_adapter,
        )

        # Task queue
        self._task_queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self._running = False

    async def start(self) -> None:
        """Start the conductor main loop."""
        self._running = True
        loop = asyncio.get_running_loop()

        # Configure shared gateway client
        _gateway_auth.configure(self._config.gateway_url)

        # Initialize persistent surfaces
        self._apm.load()
        try:
            await self._episodic_memory.initialize()
        except Exception as exc:
            logger.warning("Episodic memory init failed (continuing without): %s", exc)

        # Start Obsidian watcher
        self._watcher.start(loop)

        # Load project context into gateway
        await self._load_project_context()

        # Sync HA entities for Abra (if configured)
        if self._config.ha_url and self._config.ha_sync_entities:
            try:
                count = await self._abra._registry.sync_from_ha(
                    ha_url=self._config.ha_url,
                    ha_token=self._config.ha_token,
                    alexa_map=self._config.ha_alexa_device_map,
                )
                console.print(f"  HA entities synced: {count}")
            except Exception as exc:
                logger.warning("HA entity sync failed (using defaults): %s", exc)

        # Process any pending tasks in inbox (sync + scan)
        pending = await self._watcher.list_pending()
        for filename, content in pending:
            await self._task_queue.put((filename, content))

        console.print(f"[bold green]Conductor started[/] — project: {self._config.project_id}")
        console.print(f"  Gateway: {self._config.gateway_url}")
        console.print(f"  Inbox: {self._config.obsidian_vault}/conductor/inbox/")
        console.print(f"  Heartbeat: every {self._heartbeat._interval // 60} minutes")
        console.print(f"  APM: {self._apm.identity.get('name', 'Conductor')}")

        # Start heartbeat as background task
        heartbeat_task = asyncio.create_task(self._heartbeat.start())

        # Main loop (inbox watcher — reactive tasks)
        try:
            while self._running:
                try:
                    filename, content = await asyncio.wait_for(
                        self._task_queue.get(), timeout=5.0
                    )
                    await self._process_task(filename, content)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            pass
        finally:
            self._heartbeat.stop()
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            await self.stop()

    async def stop(self) -> None:
        """Shutdown gracefully."""
        self._running = False
        self._watcher.stop()
        await self._bouncer.close()
        await self._intent_router.close()
        await self._abra.close()
        await self._episodic_memory.close()
        await self._progress.close()
        await self._planner.close()
        await self._coder.close()
        await self._reviewer.close()
        await self._spawner.close()
        console.print("[bold yellow]Conductor stopped[/]")

    # ------------------------------------------------------------------
    # Core task processing
    # ------------------------------------------------------------------

    async def _process_task(self, filename: str, task_text: str) -> None:
        """Process a single task from inbox."""
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        console.print(f"\n[bold blue]Processing:[/] {filename} ({task_id})")

        # Determine lane after intent routing; default to background
        lane = Lane.BACKGROUND
        langfuse_trace_id = None

        try:
            # Report: queued
            await self._progress.update(task_id, "screening", filename=filename, current_step="Bouncer security screening")

            # Step 0a: Bouncer — security screening (BEFORE intent routing)
            console.print("  [dim]Screening input...[/]")
            screening = await self._bouncer.screen(task_text)

            if screening.risk_flags:
                console.print(f"  [dim yellow]Flags: {', '.join(screening.risk_flags)}[/]")

            if screening.verdict == Verdict.REJECT:
                console.print(f"  [bold red]Bouncer REJECTED:[/] {screening.rejection_reason}")
                await self._progress.update(task_id, "failed", filename=filename, current_step="Bouncer rejected", error=screening.rejection_reason)
                await self._watcher.write_failed(
                    filename,
                    f"Rejected by security screening: {screening.rejection_reason}",
                )
                return

            if screening.verdict == Verdict.CLARIFY:
                console.print("  [bold yellow]Bouncer needs clarification[/]")
                await self._progress.update(task_id, "failed", filename=filename, current_step="Needs clarification", error=screening.follow_up_question)
                await self._watcher.write_failed(
                    filename,
                    f"Needs clarification before processing:\n\n{screening.follow_up_question}",
                )
                return

            # Use the bouncer's sanitized/rewritten version
            screened_text = screening.rewritten_prompt
            console.print(f"  [dim green]Screening passed (confidence: {screening.confidence:.0%})[/]")

            # Step 0b: Intent routing
            await self._progress.update(task_id, "routing", filename=filename, current_step="Intent classification")
            console.print("  [dim]Routing intent...[/]")
            routing = await self._intent_router.route(screened_text)

            # Latency-sensitive intents get the live lane
            if routing.intent in (Intent.CONVERSATION, Intent.HOME_AUTOMATION):
                lane = Lane.LIVE

            # Create a Langfuse trace for this entire task, tagged with lane
            if self._langfuse_tracer:
                try:
                    from ..gateway.langfuse_tracer import _get_langfuse
                    lf = _get_langfuse()
                    if lf:
                        trace = lf.trace(
                            name=f"task:{task_id}",
                            tags=[lane.value, routing.intent.value],
                            metadata={
                                "filename": filename,
                                "intent": routing.intent.value,
                                "lane": lane.value,
                                "confidence": routing.confidence,
                            },
                        )
                        langfuse_trace_id = trace.id
                except Exception:
                    pass

            if routing.intent == Intent.DENIED:
                console.print(f"  [bold red]Denied:[/] {routing.denial_reason}")
                await self._watcher.write_failed(
                    filename, f"Denied: {routing.denial_reason}"
                )
                return

            if routing.intent == Intent.UNCLEAR:
                console.print("  [bold yellow]Unclear intent — asking for clarification[/]")
                await self._watcher.write_failed(
                    filename, f"Needs clarification:\n{routing.clarification_prompt}"
                )
                return

            if routing.intent == Intent.HOME_AUTOMATION:
                console.print("  [bold cyan]Home automation → Abra[/]")
                await self._handle_home_automation(filename, routing)
                return

            if routing.intent == Intent.ARTIFACT:
                console.print("  [bold magenta]Artifact creation → LLM[/]")
                await self._progress.update(task_id, "executing", filename=filename, current_step="Generating artifact")
                try:
                    answer = await _gateway_auth.gateway_chat(
                        messages=[
                            {"role": "system", "content": "You are a professional document creator. Produce well-structured, detailed artifacts (reports, specs, proposals, READMEs, design docs). Use markdown formatting."},
                            {"role": "user", "content": screened_text},
                        ],
                        max_tokens=4096,
                        temperature=0.5,
                    )
                    await self._progress.update(task_id, "completed", filename=filename, current_step="Artifact generated")
                    await self._watcher.write_completed(filename, answer)
                except Exception as exc:
                    await self._progress.update(task_id, "failed", filename=filename, error=str(exc))
                    await self._watcher.write_failed(filename, f"Artifact creation failed: {exc}")
                return

            if routing.intent == Intent.CONVERSATION:
                console.print("  [bold white]Conversation → direct LLM response[/]")
                await self._progress.update(task_id, "executing", filename=filename, current_step="Generating response")
                try:
                    answer = await _gateway_auth.gateway_chat(
                        messages=[{"role": "user", "content": screened_text}],
                        max_tokens=2048,
                        temperature=0.7,
                    )
                    await self._progress.update(task_id, "completed", filename=filename, current_step="Response generated")
                    await self._watcher.write_completed(filename, answer)
                except Exception as exc:
                    await self._progress.update(task_id, "failed", filename=filename, error=str(exc))
                    await self._watcher.write_failed(filename, f"Conversation failed: {exc}")
                return

            if routing.intent == Intent.PROJECT_BUILD:
                console.print("  [bold magenta]Project build → Scout → Architect → Extractor → Validator[/]")
                await self._handle_project_build(task_id, filename, routing, langfuse_trace_id)
                return

            # CODE or ANALYSIS → existing pipeline
            console.print(f"  [dim]Intent: {routing.intent.value} → {routing.agent_name} (confidence: {routing.confidence:.0%})[/]")
            effective_task = routing.rewritten_task or task_text

            # Build full context
            context = self._build_context()

            # Step 1: Plan
            await self._progress.update(task_id, "planning", filename=filename, current_step="Decomposing task into subtasks")
            console.print("  [dim]Planning...[/]")
            plan = await self._planner.decompose(task_id, effective_task, context)
            self._layer1.start_task(effective_task, plan.summary)

            for st in plan.subtasks:
                self._layer1.add_subtask(st.subtask_id, st.description)

            console.print(f"  Plan: {len(plan.subtasks)} subtasks")

            # Step 2: Execute each subtask (via spawner for tracing + contracts)
            all_passed = True
            total_subtasks = len(plan.subtasks)
            for i, subtask in enumerate(plan.subtasks):
                await self._progress.update(
                    task_id, "executing", filename=filename,
                    current_step=f"Subtask {i+1}/{total_subtasks}: {subtask.description[:60]}",
                    steps_total=total_subtasks, steps_completed=i,
                )
                success = await self._execute_subtask_spawned(
                    task_id=task_id,
                    subtask_id=subtask.subtask_id,
                    description=subtask.description,
                    tier=subtask.tier,
                    langfuse_trace_id=langfuse_trace_id,
                    plan_summary=plan.summary,
                    lane=lane,
                )
                if not success:
                    all_passed = False
                    break

            # Step 3: Finalize
            if all_passed:
                await self._progress.update(
                    task_id, "completed", filename=filename,
                    current_step="All subtasks passed",
                    steps_total=total_subtasks, steps_completed=total_subtasks,
                )
                await self._watcher.write_completed(filename, f"Task {task_id} completed successfully.")
                console.print(f"  [bold green]Completed:[/] {task_id}")
            else:
                await self._progress.update(
                    task_id, "failed", filename=filename,
                    current_step="Subtask failed after retries",
                    steps_total=total_subtasks, steps_completed=i,
                    error="Subtask execution failed",
                )
                await self._watcher.write_failed(filename, f"Task {task_id} failed after retries.")
                console.print(f"  [bold red]Failed:[/] {task_id}")

        except Exception as exc:
            logger.exception("Task %s failed with exception", task_id)
            await self._progress.update(task_id, "failed", filename=filename, error=str(exc))
            await self._watcher.write_failed(filename, f"Exception: {exc}")
            console.print(f"  [bold red]Error:[/] {exc}")

    async def _handle_project_build(
        self,
        task_id: str,
        filename: str,
        routing,
        langfuse_trace_id: str | None = None,
    ) -> None:
        """Multi-agent pipeline for project extraction and restructuring.

        Pipeline: SCOUT → ARCHITECT → EXTRACTOR (per file) → VALIDATOR

        Each stage uses Ultra Think for parallel candidate generation and
        the Reviewer for selection. The architect's output becomes the
        execution plan for the extractors.
        """
        task_text = routing.rewritten_task or routing.raw_input
        context_dict = {
            "layer0": self._layer0.build_prompt_section(),
            "layer1": self._layer1.build_prompt_section(),
        }

        # ── Stage 1: SCOUT — analyze source codebase ─────────────
        await self._progress.update(
            task_id, "scouting", filename=filename,
            current_step="Scout: analyzing source codebase",
        )
        console.print("  [dim]Stage 1: Scout analyzing source...[/]")

        scout_spec = AgentSpec(
            role=AgentRole.SCOUT,
            task_id=task_id,
            subtask_id=f"{task_id}-scout",
            description=f"Analyze the source codebase for: {task_text}",
            context=context_dict,
            recipe_name="scout.analyze",
            tier=2,
            lane=Lane.BACKGROUND,
            langfuse_trace_id=langfuse_trace_id,
        )
        scout_output = await self._spawner.spawn(scout_spec)

        if not scout_output.success:
            console.print(f"  [red]Scout failed:[/] {scout_output.error}")
            await self._watcher.write_failed(filename, f"Scout failed: {scout_output.error}")
            return

        console.print(f"  [green]Scout complete:[/] {scout_output.output[:200] if scout_output.output else 'no output'}")

        # ── Stage 2: ARCHITECT — design target structure ──────────
        await self._progress.update(
            task_id, "architecting", filename=filename,
            current_step="Architect: designing target structure",
        )
        console.print("  [dim]Stage 2: Architect designing structure...[/]")

        architect_spec = AgentSpec(
            role=AgentRole.ARCHITECT,
            task_id=task_id,
            subtask_id=f"{task_id}-architect",
            description=f"Design the target repo structure for: {task_text}",
            context=context_dict,
            upstream_outputs={"scout": scout_output.output or ""},
            recipe_name="architect.design",
            tier=3,
            lane=Lane.BACKGROUND,
            langfuse_trace_id=langfuse_trace_id,
        )
        architect_output = await self._spawner.spawn(architect_spec)

        if not architect_output.success:
            console.print(f"  [red]Architect failed:[/] {architect_output.error}")
            await self._watcher.write_failed(filename, f"Architect failed: {architect_output.error}")
            return

        console.print(f"  [green]Architect complete[/]")

        # Parse the architect's output for subtasks
        import json as _json
        try:
            arch_plan = _json.loads(architect_output.output) if isinstance(architect_output.output, str) else {}
        except _json.JSONDecodeError:
            arch_plan = {}

        file_mappings = arch_plan.get("file_mappings", [])
        subtask_descriptions = arch_plan.get("subtasks", [])

        console.print(f"  Plan: {len(file_mappings)} file mappings, {len(subtask_descriptions)} subtasks")

        # ── Stage 3: EXTRACTOR — transform each file ─────────────
        await self._progress.update(
            task_id, "extracting", filename=filename,
            current_step=f"Extracting {len(file_mappings)} files",
            steps_total=len(file_mappings),
        )

        extract_failures = []
        for i, mapping in enumerate(file_mappings):
            source = mapping.get("source", "")
            target = mapping.get("target", "")
            transforms = mapping.get("transforms", [])

            console.print(f"  [dim]Extracting [{i+1}/{len(file_mappings)}]: {source} → {target}[/]")
            await self._progress.update(
                task_id, "extracting", filename=filename,
                current_step=f"Extracting {i+1}/{len(file_mappings)}: {target}",
                steps_total=len(file_mappings), steps_completed=i,
            )

            extractor_spec = AgentSpec(
                role=AgentRole.EXTRACTOR,
                task_id=task_id,
                subtask_id=f"{task_id}-extract-{i}",
                description=f"Extract {source} → {target} with transforms: {transforms}",
                context=context_dict,
                upstream_outputs={
                    "architect": architect_output.output or "",
                    "mapping": _json.dumps(mapping),
                },
                recipe_name="extractor.transform",
                tier=2,
                lane=Lane.BACKGROUND,
                langfuse_trace_id=langfuse_trace_id,
            )
            ext_output = await self._spawner.spawn(extractor_spec)

            if not ext_output.success:
                console.print(f"    [red]Failed:[/] {ext_output.error}")
                extract_failures.append(f"{target}: {ext_output.error}")
            else:
                console.print(f"    [green]OK[/]")

        # ── Stage 4: VALIDATOR — check everything builds ──────────
        await self._progress.update(
            task_id, "validating", filename=filename,
            current_step="Validator: checking build integrity",
        )
        console.print("  [dim]Stage 4: Validator checking build...[/]")

        validator_spec = AgentSpec(
            role=AgentRole.VALIDATOR,
            task_id=task_id,
            subtask_id=f"{task_id}-validate",
            description="Validate the extracted Stronghold repo builds and imports correctly",
            context=context_dict,
            upstream_outputs={"architect": architect_output.output or ""},
            recipe_name="validator.check",
            tier=2,
            lane=Lane.BACKGROUND,
            langfuse_trace_id=langfuse_trace_id,
        )
        val_output = await self._spawner.spawn(validator_spec)

        # ── Finalize ──────────────────────────────────────────────
        result_parts = [f"## Project Build Result\n"]
        result_parts.append(f"**Files mapped:** {len(file_mappings)}")
        result_parts.append(f"**Extract failures:** {len(extract_failures)}")
        if extract_failures:
            result_parts.append("\n### Failures:")
            for f in extract_failures:
                result_parts.append(f"- {f}")
        if val_output.success:
            result_parts.append(f"\n### Validation:\n{val_output.output[:500] if val_output.output else 'OK'}")
        else:
            result_parts.append(f"\n### Validation FAILED:\n{val_output.error}")

        result_text = "\n".join(result_parts)

        if not extract_failures and val_output.success:
            await self._progress.update(task_id, "completed", filename=filename, current_step="Build complete")
            await self._watcher.write_completed(filename, result_text)
            console.print("  [bold green]Project build complete![/]")
        else:
            await self._progress.update(task_id, "failed", filename=filename, error=f"{len(extract_failures)} failures")
            await self._watcher.write_failed(filename, result_text)
            console.print(f"  [bold red]Project build finished with {len(extract_failures)} failures[/]")

    async def _handle_home_automation(self, filename: str, routing) -> None:
        """Route a home automation intent through Abra.

        Abra resolves the room from the source device, discovers devices,
        interprets the comfort intent, checks environment, and builds
        the HA service calls.
        """
        task_text = routing.rewritten_task or routing.raw_input

        # Extract source device from metadata if available
        # (Alexa skill would attach this; for now check raw_input for hints)
        source_device_id = getattr(routing, "source_device_id", "")
        area_id = getattr(routing, "area_id", "")

        result = await self._abra.handle(
            utterance=task_text,
            source_device_id=source_device_id,
            area_id=area_id,
        )

        if not result.success:
            console.print(f"  [yellow]Abra failed:[/] {result.error}")
            await self._watcher.write_failed(
                filename, f"Abra: {result.error}"
            )
            return

        console.print(f"  [cyan]Room:[/] {result.room_resolved}")
        console.print(f"  [cyan]Reasoning:[/] {result.reasoning}")
        for call in result.service_calls:
            console.print(
                f"  [cyan]→[/] {call.domain}.{call.service}({call.entity_id}"
                + (f", {call.data}" if call.data else "")
                + ")"
            )

        # Execute the calls against HA
        responses = await self._abra.execute(result)
        console.print(f"  [bold green]Executed {len(responses)} service call(s)[/]")

        # Write completion
        summary_lines = [
            f"Room: {result.room_resolved}",
            f"Reasoning: {result.reasoning}",
        ]
        for call in result.service_calls:
            summary_lines.append(f"  {call.domain}.{call.service}({call.entity_id})")
        await self._watcher.write_completed(filename, "\n".join(summary_lines))

    async def _execute_subtask_spawned(
        self,
        *,
        task_id: str,
        subtask_id: str,
        description: str,
        tier: int,
        langfuse_trace_id: str | None = None,
        plan_summary: str = "",
        lane: Lane = Lane.BACKGROUND,
    ) -> bool:
        """Execute a subtask via the spawner (coder → reviewer pipeline).

        Uses AgentSpec/AgentOutput contracts with Langfuse trace propagation,
        exemplar injection, and PromptManager integration.
        """
        self._layer1.start_subtask(subtask_id)
        self._build_context()  # Side effect: updates internal state

        # Build context dict from memory layers
        context_dict = {
            "layer0": self._layer0.build_prompt_section(),
            "layer1": self._layer1.build_prompt_section(),
            "layer2": self._layer2.build_prompt_section(),
            "knowledge": self._knowledge.build_prompt_section(),
        }

        for attempt in range(self._config.max_retries + 1):
            console.print(
                f"    [{subtask_id}] Tier {tier}, attempt {attempt + 1} (spawned)"
            )

            # --- Coder agent ---
            coder_spec = AgentSpec(
                role=AgentRole.CODER,
                task_id=task_id,
                subtask_id=subtask_id,
                description=description,
                attempt=attempt + 1,
                project_id=self._config.project_id,
                context=context_dict,
                upstream_outputs={"planner": plan_summary},
                tier=tier,
                parallel_generations=tier if tier <= 3 else 1,
                exemplar_task_type=self._classify_task(description),
                lane=lane,
                langfuse_trace_id=langfuse_trace_id,
            )

            coder_output = await self._spawner.spawn(coder_spec)

            if not coder_output.success:
                console.print(f"    [red]Coder failed:[/] {coder_output.error}")
                if coder_output.error_type and coder_output.error_type not in RECOVERABLE_ERRORS:
                    self._layer1.fail_subtask(subtask_id, coder_output.error or "Non-recoverable error")
                    return False
                if tier < 3:
                    tier += 1
                    console.print(f"    Escalating to Tier {tier}")
                continue

            if not coder_output.output:
                console.print("    [red]Coder returned empty output[/]")
                continue

            # --- Reviewer agent ---
            reviewer_spec = AgentSpec(
                role=AgentRole.REVIEWER,
                task_id=task_id,
                subtask_id=subtask_id,
                description=description,
                attempt=attempt + 1,
                context=context_dict,
                upstream_outputs={
                    "planner": plan_summary,
                    "coder": coder_output.output,
                },
                tier=min(tier, 2),  # reviewer doesn't need high tier
                lane=lane,
                langfuse_trace_id=langfuse_trace_id,
            )

            reviewer_output = await self._spawner.spawn(reviewer_spec)

            # Parse reviewer scores
            review_data = reviewer_output.output_parsed or {}
            selected_score = 5.0
            selected_idx = 0
            feedback_summary = ""

            if review_data:
                scores = review_data.get("scores", [])
                selected_idx = review_data.get("selected_idx") or 0
                feedback_summary = review_data.get("feedback_summary", "")
                if scores and isinstance(selected_idx, int) and 0 <= selected_idx < len(scores):
                    selected_score = scores[selected_idx].get("overall", 5.0)

            console.print(
                f"    Reviewer score: {selected_score:.1f} "
                f"({reviewer_output.duration_ms:.0f}ms)"
            )

            # Check threshold
            if selected_score < self._reviewer.accept_threshold:
                console.print(f"    [yellow]Below threshold ({self._reviewer.accept_threshold})[/]")
                self._layer1.add_feedback(feedback_summary or "Below quality threshold")

                if tier < 3:
                    tier += 1
                    console.print(f"    Escalating to Tier {tier}")
                continue

            # Apply the code
            self._apply_candidate(coder_output.output)

            # Run tests
            test_result = await self._test_runner.run()
            console.print(
                f"    Tests: {'PASS' if test_result.success else 'FAIL'} "
                f"({test_result.tests_passed}/{test_result.tests_total})"
            )

            if test_result.success:
                # Record changelog
                self._changelog.append(
                    ChangelogEntry(
                        task_id=task_id,
                        project_id=self._config.project_id,
                        description=description,
                        tier_used=tier,
                        candidates_generated=1,
                        accepted_candidate_idx=selected_idx,
                        reviewer_score=selected_score,
                        test_passed=True,
                        retries=attempt,
                    )
                )

                # Store as exemplar if score is high enough
                if selected_score >= 8.0:
                    self._exemplar_library.add(
                        Exemplar(
                            task_type=self._classify_task(description),
                            description=description[:200],
                            prompt=description,
                            solution=coder_output.output[:2000],
                            reviewer_score=selected_score,
                            project_id=self._config.project_id,
                            tags=[],
                        )
                    )

                self._layer1.complete_subtask(subtask_id, coder_output.output[:100])
                return True

            # Test failed — add feedback and retry
            self._layer1.add_feedback(f"Tests failed: {test_result.output[:200]}")
            if tier < 3:
                tier += 1

        # All retries exhausted
        self._layer1.fail_subtask(subtask_id, "Max retries exhausted")
        return False

    # ------------------------------------------------------------------
    # Context assembly
    # ------------------------------------------------------------------

    def _build_context(self) -> str:
        """Assemble the full prompt context from memory layers."""
        parts = [
            self._layer0.build_prompt_section(),
            self._layer1.build_prompt_section(),
            self._layer2.build_prompt_section(),
            self._knowledge.build_prompt_section(),
        ]
        return "\n\n".join(p for p in parts if p)

    # ------------------------------------------------------------------
    # Candidate application
    # ------------------------------------------------------------------

    def _apply_candidate(self, content: str) -> bool:
        """Apply a code candidate to the project files.

        Handles two formats:
        1. === NEW FILE: path === blocks (full file content)
        2. Unified diff format (--- a/path, +++ b/path, @@ hunks)

        Returns False if no changes were applied (prevents silent no-ops).
        """
        lines = content.splitlines()
        files_written = 0

        # Try format 1: === NEW FILE: path === blocks
        current_file: str | None = None
        current_content: list[str] = []

        for line in lines:
            if line.startswith("=== NEW FILE:") and line.endswith("==="):
                if current_file:
                    result = self._file_ops.write(current_file, "\n".join(current_content))
                    if result.success:
                        files_written += 1
                current_file = line.split(":", 1)[1].rsplit("===", 1)[0].strip()
                current_content = []
            elif current_file is not None:
                current_content.append(line)

        if current_file:
            result = self._file_ops.write(current_file, "\n".join(current_content))
            if result.success:
                files_written += 1

        if files_written > 0:
            logger.info("Applied candidate: %d file(s) written", files_written)
            return True

        # Try format 2: unified diff via unidiff library (MIT license)
        try:
            from unidiff import PatchSet

            patch = PatchSet(content)
            if not patch:
                logger.warning("Candidate applied nothing — no recognized file format")
                return False

            patches_applied = 0
            for patched_file in patch:
                path = patched_file.path
                # Strip a/ b/ prefixes
                if path.startswith("b/"):
                    path = path[2:]

                if patched_file.is_added_file:
                    # New file — write full content
                    new_content = "".join(
                        line.value for hunk in patched_file for line in hunk
                        if line.is_added or line.is_context
                    )
                    result = self._file_ops.write(path, new_content)
                    if result.success:
                        patches_applied += 1
                        logger.info("Created new file: %s", path)
                else:
                    # Existing file — apply hunks
                    read_result = self._file_ops.read(path)
                    if not read_result.success:
                        logger.warning("Cannot read %s for patching: %s", path, read_result.message)
                        continue

                    original = read_result.message.splitlines(keepends=True)
                    patched = list(original)
                    offset = 0

                    for hunk in patched_file:
                        start = hunk.source_start - 1 + offset
                        # Remove source lines, insert target lines
                        source_len = hunk.source_length
                        target_lines = [
                            line.value for line in hunk
                            if line.is_added or line.is_context
                        ]
                        patched[start:start + source_len] = target_lines
                        offset += len(target_lines) - source_len

                    if patched != original:
                        write_result = self._file_ops.write(path, "".join(patched))
                        if write_result.success:
                            patches_applied += 1
                            logger.info("Patched %s (%d hunks)", path, len(patched_file))

            if patches_applied > 0:
                logger.info("Applied candidate: %d file(s) patched", patches_applied)
                return True

        except ImportError:
            logger.warning("unidiff not installed — cannot apply diff format")
        except Exception as exc:
            logger.debug("Diff parsing failed (may not be diff format): %s", exc)

        logger.warning("Candidate applied nothing — no recognized file format")
        return False

    # ------------------------------------------------------------------
    # Training data
    # ------------------------------------------------------------------

    def _record_training(
        self,
        task_id: str,
        subtask_id: str,
        tier: int,
        coder_result,
        review,
        test_passed: bool,
        test_output: str,
    ) -> None:
        candidates = [
            CandidateRecord(
                content=c.content[:2000],
                sampling_params=c.sampling_params,
                reviewer_score=(
                    review.scores[i].overall
                    if i < len(review.scores)
                    else 0.0
                ),
                tokens_generated=c.tokens_generated,
            )
            for i, c in enumerate(coder_result.candidates)
        ]

        row = TrainingRow(
            task_id=task_id,
            subtask_id=subtask_id,
            project_id=self._config.project_id,
            tier=tier,
            candidates=candidates,
            test_passed=test_passed,
            test_output_summary=test_output,
            accepted_candidate_idx=review.selected_idx,
            prompt_hash=DataCollector.hash_content(self._layer1.build_prompt_section()),
            context_hash=self._layer0.content_hash,
        )
        self._data_collector.record(row)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _handle_new_task(self, filename: str, content: str) -> None:
        """Called by ObsidianWatcher when a new task file appears."""
        console.print(f"[cyan]New task:[/] {filename}")
        await self._task_queue.put((filename, content))

    async def _handle_constraints_changed(self) -> None:
        """Called when Layer 0 constraints file is modified."""
        console.print("[yellow]Constraints changed — reloading and invalidating cache[/]")
        self._layer0.reload()
        await self._load_project_context()

    async def _load_project_context(self) -> None:
        """Load/reload project context into the gateway."""
        try:
            client = await _gateway_auth.gateway_client()
            resp = await client.post(
                "/v1/project/load",
                json={
                    "project_id": self._config.project_id,
                    "layer0_text": self._layer0.content,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            console.print(f"  Context loaded: {data.get('action', 'unknown')}")
        except Exception as exc:
            logger.error("Failed to load project context: %s", exc)

    @staticmethod
    def _classify_task(description: str) -> str:
        """Simple heuristic task type classification."""
        desc_lower = description.lower()
        if any(w in desc_lower for w in ["fix", "bug", "error", "crash"]):
            return "bugfix"
        if any(w in desc_lower for w in ["test", "spec", "assert"]):
            return "test"
        if any(w in desc_lower for w in ["refactor", "rename", "extract", "clean"]):
            return "refactor"
        return "feature"


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Conductor Orchestrator")
    parser.add_argument(
        "--config", required=True, help="Path to conductor.yaml"
    )
    parser.add_argument(
        "--project", required=True, help="Project ID"
    )
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )

    config = OrchestratorConfig.from_yaml(args.config)
    if args.project:
        config.project_id = args.project

    conductor = Conductor(config)

    try:
        asyncio.run(conductor.start())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/]")


if __name__ == "__main__":
    main()
