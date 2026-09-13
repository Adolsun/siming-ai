"""One local CLI process attempt, with input/output boundary observation."""

from app.modules.operations.interfaces.trace_observer import observed


@observed(kind="cli", inputs=("prompt", "model"), input_layer="cli_input", output_layer="cli_event")
async def run_cli_once(adapter, prompt, model, extra_body, unlink_if_exists):
    runtime_body = dict(extra_body or {})
    context = adapter._prepare_run_context(prompt, model, runtime_body)
    try:
        process = await adapter._spawn_run_process(context)
        stdout, stderr, terminal_reason = await adapter._collect_run_output(
            context,
            process,
            runtime_body,
        )
        return await adapter._finalize_run_output(
            context,
            process,
            stdout,
            stderr,
            terminal_reason,
            model,
            runtime_body,
        )
    finally:
        unlink_if_exists(context.prompt_file)
        unlink_if_exists(context.codex_output_file if context.cleanup_codex_output_file else None)
