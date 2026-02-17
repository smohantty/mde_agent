from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from agent.config import (
    AgentConfig,
    ConfigError,
    discover_config_path,
    load_config,
    write_default_config,
)
from agent.runtime.orchestrator import Orchestrator
from agent.skills.registry import SkillRegistry
from agent.types import EventRecord

app = typer.Typer(help="Autonomous skill-native agent")
skills_app = typer.Typer(help="Inspect and list skill packs")
config_app = typer.Typer(help="Initialize and validate configuration")
app.add_typer(skills_app, name="skills")
app.add_typer(config_app, name="config")
console = Console()


def _load_config_or_exit(config_path: Path | None) -> AgentConfig:
    try:
        return load_config(config_path)
    except ConfigError as exc:
        console.print(f"[red]Config error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command("run")
def run_command(
    task: Annotated[str, typer.Argument(help="Task to execute")],
    skills_dir: Annotated[Path, typer.Option(help="Skills directory path")] = Path("./skills"),
    profile: Annotated[str, typer.Option(help="Runtime profile")] = "permissive",
    provider: Annotated[
        str | None, typer.Option(help="Provider override: anthropic|gemini")
    ] = None,
    debug_llm: Annotated[bool, typer.Option(help="Capture full prompt/response artifacts")] = False,
    dry_run: Annotated[
        bool, typer.Option(help="Only prefilter/disclose/build prompt, no LLM or command execution")
    ] = False,
    show_progress: Annotated[
        bool, typer.Option(help="Show concise progress while the agent executes")
    ] = True,
    max_turns: Annotated[int | None, typer.Option(help="Override max turn count")] = None,
    config: Annotated[Path | None, typer.Option(help="Path to config file")] = None,
) -> None:
    cfg = _load_config_or_exit(config)
    cfg.runtime.profile = profile
    cfg.logging.debug_llm_bodies = debug_llm

    orchestrator = Orchestrator(cfg)

    def _render_progress(event: EventRecord) -> None:
        if not show_progress:
            return
        payload = event.payload
        et = event.event_type
        if et == "run_started":
            console.print(
                f"[cyan]start[/cyan] task={payload.get('task')} provider={payload.get('provider')}"
            )
        elif et == "skill_catalog_loaded":
            loaded = payload.get("skills_count")
            skills_dir_label = payload.get("skills_dir")
            console.print(f"[cyan]skills[/cyan] loaded={loaded} dir={skills_dir_label}")
        elif et == "skill_prefilter_completed":
            candidates = payload.get("candidates", [])
            top = candidates[0]["skill_name"] if candidates else "none"
            console.print(
                f"[cyan]router[/cyan] candidates={payload.get('candidate_count')} top={top}"
            )
        elif et == "skill_disclosure_loaded":
            stage = payload.get("stage")
            item_count = len(payload.get("paths", []))
            console.print(f"[cyan]disclosure[/cyan] stage={stage} items={item_count}")
        elif et == "llm_request_sent":
            turn = payload.get("turn_index")
            attempt = payload.get("attempt")
            call_site = payload.get("call_site", "unspecified")
            console.print(f"[cyan]llm[/cyan] turn={turn} attempt={attempt} site={call_site}")
        elif et == "llm_response_received":
            meta = payload.get("meta", {})
            latency_ms = meta.get("latency_ms")
            output_tokens = meta.get("output_tokens")
            call_site = payload.get("call_site", "unspecified")
            console.print(
                f"[cyan]llm[/cyan] response site={call_site} "
                f"latency_ms={latency_ms} output_tokens={output_tokens}"
            )
        elif et == "llm_decision_decoded":
            turn = payload.get("turn_index")
            skill = payload.get("selected_skill")
            console.print(f"[cyan]decision[/cyan] turn={turn} skill={skill}")
        elif et == "skill_step_executed":
            step_id = payload.get("step_id")
            step_type = payload.get("type")
            status = payload.get("status")
            message = payload.get("message")
            if message:
                console.print(
                    f"[cyan]step[/cyan] {step_id} type={step_type} status={status} "
                    f"message={message}"
                )
            else:
                console.print(f"[cyan]step[/cyan] {step_id} type={step_type} status={status}")
        elif et == "step_retry_scheduled":
            step_id = payload.get("step_id")
            retry_count = payload.get("retry_count")
            console.print(f"[yellow]retry[/yellow] {step_id} count={retry_count}")
        elif et == "llm_retry_scheduled":
            attempt = payload.get("attempt")
            retryable = payload.get("retryable")
            console.print(f"[yellow]llm-retry[/yellow] attempt={attempt} retryable={retryable}")
        elif et == "run_failed":
            console.print(f"[red]failed[/red] reason={payload.get('reason')}")
        elif et == "run_finished":
            final_summary = payload.get("final_summary")
            if final_summary:
                console.print(
                    f"[green]finished[/green] turn={payload.get('turn_index')} "
                    f"summary={final_summary}"
                )
            else:
                console.print(f"[green]finished[/green] turn={payload.get('turn_index')}")

    result = orchestrator.run(
        task=task,
        skills_dir=skills_dir,
        provider_override=provider,
        dry_run=dry_run,
        max_turns_override=max_turns,
        on_event=_render_progress,
    )

    if result.status == "success":
        console.print(f"[green]Run completed:[/green] {result.run_id}")
    else:
        console.print(f"[red]Run failed:[/red] {result.run_id} - {result.message}")
        raise typer.Exit(code=1)

    console.print(f"Events: {result.events_path}")
    if result.llm_transcript_path is not None:
        console.print(f"LLM Transcript: {result.llm_transcript_path}")
    if result.final_summary_path is not None:
        console.print(f"Final Summary: {result.final_summary_path}")


@skills_app.command("list")
def skills_list(
    skills_dir: Annotated[Path, typer.Option(help="Skills directory path")] = Path("./skills"),
) -> None:
    registry = SkillRegistry(skills_dir)
    skills = registry.load()
    if not skills:
        console.print("No skills found")
        return

    table = Table(title="Skills")
    table.add_column("Name")
    table.add_column("Description")
    table.add_column("Tags")
    for skill in skills:
        table.add_row(
            skill.metadata.name, skill.metadata.description, ", ".join(skill.metadata.tags)
        )
    console.print(table)


@skills_app.command("inspect")
def skills_inspect(
    skill_name: Annotated[str, typer.Argument(help="Skill name")],
    skills_dir: Annotated[Path, typer.Option(help="Skills directory path")] = Path("./skills"),
    show_frontmatter: Annotated[bool, typer.Option(help="Print frontmatter data")] = True,
    show_sections: Annotated[bool, typer.Option(help="Print parsed markdown sections")] = False,
) -> None:
    registry = SkillRegistry(skills_dir)
    skills = registry.load()
    selected = registry.by_name(skills, skill_name)
    if selected is None:
        console.print(f"Skill not found: {skill_name}")
        raise typer.Exit(code=1)

    if show_frontmatter:
        console.print_json(selected.metadata.model_dump_json(indent=2))

    if show_sections:
        for title, content in selected.sections.items():
            console.rule(title)
            console.print(content)


@app.command("replay")
def replay_command(
    run_id: Annotated[str, typer.Argument(help="Run ID")],
    event_stream: Annotated[bool, typer.Option(help="Replay events as a stream")] = True,
    llm_transcript: Annotated[
        bool, typer.Option(help="Replay readable LLM transcript entries")
    ] = False,
    config: Annotated[Path | None, typer.Option(help="Path to config file")] = None,
) -> None:
    cfg = _load_config_or_exit(config)
    events_path = Path(cfg.logging.jsonl_dir) / run_id / "events.jsonl"
    if not events_path.exists():
        console.print(f"Events file not found: {events_path}")
        raise typer.Exit(code=1)

    lines = events_path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        data = json.loads(line)
        if event_stream:
            console.print(
                f"[{data['timestamp']}] {data['event_type']} "
                f"run={data['run_id']} trace={data['trace_id']} payload={data['payload']}"
            )
        else:
            console.print_json(json.dumps(data))

    if llm_transcript:
        transcript_path = Path(cfg.logging.jsonl_dir) / run_id / cfg.logging.llm_transcript_filename
        if not transcript_path.exists():
            console.print(f"LLM transcript file not found: {transcript_path}")
            raise typer.Exit(code=1)
        transcript_text = transcript_path.read_text(encoding="utf-8")
        console.print(transcript_text.rstrip())


@config_app.command("init")
def config_init(
    output: Annotated[Path, typer.Option(help="Output config path")] = Path("./agent.yaml"),
    force: Annotated[bool, typer.Option(help="Overwrite existing config file")] = False,
) -> None:
    try:
        write_default_config(output, overwrite=force)
    except ConfigError as exc:
        console.print(f"[red]Config init failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"Wrote config file: {output}")


@config_app.command("validate")
def config_validate(
    file: Annotated[Path, typer.Option(help="Config file path")] = Path("agent.yaml"),
) -> None:
    try:
        _ = load_config(file)
    except ConfigError as exc:
        console.print(f"[red]Invalid config:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"Config valid: {file}")


@app.command("config-path")
def config_path() -> None:
    path = discover_config_path(None)
    if path is None:
        console.print("No config discovered; using built-in defaults")
        return
    console.print(str(path))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
