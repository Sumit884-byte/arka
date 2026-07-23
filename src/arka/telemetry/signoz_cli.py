"""SigNoz helpers for Track 01 — status, demo traces, vLLM checks."""

from __future__ import annotations

import argparse
import os
import sys


def _signoz_ui_url() -> str:
    return os.environ.get("SIGNOZ_UI_URL", "http://localhost:8080").rstrip("/")


def _print_setup_hint(*, docker_ok: bool, foundry_ok: bool) -> None:
    if docker_ok and foundry_ok:
        return
    missing = []
    if not docker_ok:
        missing.append("Docker")
    if not foundry_ok:
        missing.append("foundryctl")
    print(f"hint\tmissing: {', '.join(missing)} — run: arka signoz setup")


def cmd_status(_args: argparse.Namespace) -> int:
    try:
        from arka.telemetry import spans_enabled, trace_status
    except ImportError:
        print("telemetry\tmissing")
        return 1

    from arka.telemetry.signoz_setup import (
        docker_daemon_running,
        foundryctl_path,
        prereq_status_lines,
        signoz_mcp_status,
        signoz_ui_setup_status,
    )

    status = trace_status()
    for key, value in status.items():
        print(f"{key}\t{value}")
    try:
        from arka.telemetry.observability_doctor import collect as doctor_collect

        doctor = doctor_collect()
        print(f"collector_reachable\t{str(doctor.get('collector_reachable', False)).lower()}")
        print(f"packages_installed\t{str(doctor.get('packages_installed', False)).lower()}")
        for key, value in (doctor.get("verification") or {}).items():
            print(f"verify_{key}\t{value}")
    except ImportError:
        pass
    for key, value in prereq_status_lines():
        print(f"{key}\t{value}")
    try:
        from arka.telemetry.supermemory_obs import supermemory_status_lines

        for key, value in supermemory_status_lines():
            print(f"{key}\t{value}")
    except ImportError:
        pass
    try:
        from arka.telemetry.mcp_obs import mcp_status_lines

        for key, value in mcp_status_lines():
            print(f"{key}\t{value}")
    except ImportError:
        pass
    try:
        from arka.llm.providers import get_provider, provider_base_url, vllm_cloud_configured
        from arka.llm.servers import _vllm_cloud_base_raw, is_reachable

        print(f"vllm_cloud_configured\t{str(vllm_cloud_configured()).lower()}")
        if vllm_cloud_configured():
            spec = get_provider("vllm-cloud")
            print(f"vllm_cloud_url\t{provider_base_url(spec) if spec else _vllm_cloud_base_raw()}")
            print(f"vllm_cloud_reachable\t{is_reachable('vllm-cloud')}")
            print(f"vllm_cloud_model\t{os.environ.get('VLLM_CLOUD_MODEL', 'default')}")
    except ImportError:
        pass
    ui = _signoz_ui_url()
    mcp_base = os.environ.get("SIGNOZ_MCP_URL", "http://localhost:8000").rstrip("/")
    setup = signoz_ui_setup_status(ui)
    mcp = signoz_mcp_status(mcp_base)
    print(f"signoz_setup\t{setup}")
    print(f"signoz_mcp\t{mcp}")
    print(f"ui\t{ui}/traces")
    print(f"mcp\t{mcp_base}/mcp")
    if spans_enabled() and status.get("configured") != "true":
        print("hint\tpip install 'arka-agent[observability]'")
    if setup == "pending":
        print(f"hint\topen {ui} and complete first-time SigNoz setup before OTLP traces will appear")
    if mcp == "unreachable":
        print("hint\tSigNoz MCP missing — ensure mcp.spec.enabled: true in casting.yaml and re-run: arka signoz setup -y")
    _print_setup_hint(docker_ok=docker_daemon_running(), foundry_ok=bool(foundryctl_path()))
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    from arka.telemetry.signoz_setup import cmd_setup as run_setup

    return run_setup(args)


def cmd_demo(_args: argparse.Namespace) -> int:
    """Emit a sample E2E agent trace without calling an LLM."""
    try:
        from arka.telemetry import llm_http_span_attributes, mark_ok, span, spans_enabled
        from arka.telemetry.tracing import shutdown_tracing
    except ImportError:
        print("Install observability extras: pip install 'arka-agent[observability]'", file=sys.stderr)
        return 1

    if not spans_enabled():
        print("Enable tracing first:", file=sys.stderr)
        print("  OTEL_TRACES_ENABLED=1 SIGNOZ_ENDPOINT=http://localhost:4318", file=sys.stderr)
        return 1

    import time

    from arka.telemetry.skill_obs import finish_skill_dispatch

    with span(
        "arka.request",
        attributes={"arka.command": "signoz demo", "arka.track": "01"},
    ):
        with span(
            "arka.route",
            attributes={
                "arka.route.source": "offline",
                "arka.route.skill": "goal demo",
                "arka.route.decision": "symbolic",
            },
        ):
            pass
        for skill, exit_code in (("greeting", 0), ("help", 0), ("play", 1)):
            skill_start = time.perf_counter()
            with span(
                f"arka.skill.{skill}",
                attributes={"arka.skill.name": skill, "arka.skill.line": skill},
            ) as skill_span:
                finish_skill_dispatch(
                    skill_span,
                    skill=skill,
                    exit_code=exit_code,
                    start=skill_start,
                    skill_line=skill,
                )
        with span(
            "arka.agent.goal",
            attributes={"arka.agent.goal_text": "demo observability trace", "arka.agent.max_steps": 3},
        ):
            for step in (1, 2, 3):
                with span(
                    "arka.agent.goal.step",
                    attributes={"arka.agent.step": step, "arka.agent.status": "continue" if step < 3 else "done"},
                ) as step_span:
                    with span(
                        "arka.llm.complete",
                        attributes={"arka.task": "agent", "gen_ai.provider.name": "demo", "gen_ai.request.model": "demo"},
                    ):
                        with span(
                            "arka.llm.attempt",
                            attributes={
                                "gen_ai.provider.name": "gemini",
                                "gen_ai.request.model": "gemini-2.0-flash",
                                "arka.llm.attempt_index": 1,
                                **llm_http_span_attributes("gemini"),
                                "http.status_code": 200,
                                "http.response.status_code": 200,
                            },
                        ):
                            pass
                        with span(
                            "arka.llm.attempt",
                            attributes={
                                "gen_ai.provider.name": "vllm-cloud",
                                "gen_ai.request.model": "demo-model",
                                "arka.llm.attempt_index": 2,
                                "arka.inference.backend": "vllm-cloud",
                                **llm_http_span_attributes("vllm-cloud"),
                                "http.status_code": 200,
                                "http.response.status_code": 200,
                            },
                        ):
                            pass
                    if step < 3:
                        with span(
                            "arka.tool.shell",
                            attributes={"arka.tool.command": "wc -l README.md", "arka.tool.exit_code": 0},
                        ):
                            mark_ok(step_span)
                    else:
                        mark_ok(step_span)
        with span(
            "arka.supermemory.context",
            attributes={
                "arka.supermemory.backend": "supermemory",
                "arka.supermemory.hits": 2,
                "arka.supermemory.mode": "auto",
                "http.method": "POST",
                "http.request.method": "POST",
                "http.url": "https://api.supermemory.ai/v4/profile",
                "url.full": "https://api.supermemory.ai/v4/profile",
                "http.status_code": 200,
                "http.response.status_code": 200,
            },
        ):
            pass

    try:
        from arka.telemetry.logs import emit_log
        from arka.telemetry.metrics import record_request, record_supermemory_op

        record_request(command="signoz demo")
        record_supermemory_op(operation="context", backend="supermemory", success=True, hits=2)
        emit_log(
            "Demo trace sent — synthetic E2E agent observability trace",
            level="info",
            attributes={"arka.command": "signoz demo", "arka.track": "01"},
        )
        emit_log(
            "Supermemory context fetch (demo)",
            level="info",
            attributes={
                "arka.component": "supermemory",
                "arka.supermemory.operation": "context",
                "arka.supermemory.backend": "supermemory",
            },
        )
    except ImportError:
        pass
    shutdown_tracing()
    print(f"Demo trace sent. Open {_signoz_ui_url()}/traces and filter service.name = arka")
    return 0


def cmd_vllm(_args: argparse.Namespace) -> int:
    """Report vLLM reachability for self-hosted and cloud inference observability."""
    try:
        from arka.llm.providers import get_provider, provider_base_url, vllm_cloud_configured
        from arka.llm.servers import (
            _vllm_cloud_base_raw,
            _vllm_cloud_health_url,
            _vllm_health_url,
            is_reachable,
            provider_available_with_servers,
        )
        from arka.telemetry import span, spans_enabled
        from arka.telemetry.tracing import shutdown_tracing
    except ImportError as exc:
        print(f"vllm check failed: {exc}", file=sys.stderr)
        return 1

    local_reachable = is_reachable("vllm")
    local_configured = provider_available_with_servers("vllm")
    host = os.environ.get("VLLM_HOST", "127.0.0.1:8000")
    model = os.environ.get("VLLM_MODEL", "default")
    print("backend\tvllm")
    print(f"reachable\t{local_reachable}")
    print(f"configured\t{local_configured}")
    print(f"host\t{host}")
    print(f"model\t{model}")

    cloud_configured = vllm_cloud_configured()
    cloud_reachable = is_reachable("vllm-cloud") if cloud_configured else False
    cloud_url = ""
    if cloud_configured:
        spec = get_provider("vllm-cloud")
        cloud_url = provider_base_url(spec) if spec else _vllm_cloud_base_raw()
    cloud_model = os.environ.get("VLLM_CLOUD_MODEL", "default")
    print("")
    print("backend\tvllm-cloud")
    print(f"configured\t{cloud_configured}")
    print(f"reachable\t{cloud_reachable}")
    print(f"url\t{cloud_url or '(unset)'}")
    print(f"model\t{cloud_model}")

    exit_code = 0
    if not local_reachable and not local_configured and not cloud_configured:
        exit_code = 1
    elif cloud_configured and not cloud_reachable and not local_reachable and not local_configured:
        exit_code = 1

    if spans_enabled():
        try:
            from arka.telemetry.logs import emit_log
            from arka.telemetry.metrics import record_inference_op
        except ImportError:
            emit_log = None  # type: ignore[assignment,misc]
            record_inference_op = None  # type: ignore[assignment,misc]

        health_url = _vllm_health_url()
        with span(
            "arka.inference.vllm.check",
            attributes={
                "arka.inference.backend": "vllm",
                "arka.inference.reachable": local_reachable,
                "gen_ai.request.model": model,
                "http.method": "GET",
                "http.request.method": "GET",
                "http.url": health_url,
                "url.full": health_url,
                "http.status_code": 200 if local_reachable else 503,
                "http.response.status_code": 200 if local_reachable else 503,
            },
        ) as current:
            if not local_reachable and local_configured:
                from arka.telemetry import mark_error

                mark_error(current, "vllm unreachable")
            elif local_reachable:
                from arka.telemetry import mark_ok

                mark_ok(current)
        if record_inference_op is not None:
            record_inference_op(backend="vllm", operation="check", success=local_reachable)
        if emit_log is not None:
            emit_log(
                f"vllm check reachable={local_reachable}",
                level="info" if local_reachable else "warning",
                attributes={
                    "arka.inference.backend": "vllm",
                    "arka.inference.reachable": local_reachable,
                },
            )

        if cloud_configured:
            cloud_health = _vllm_cloud_health_url() or cloud_url
            with span(
                "arka.inference.vllm.cloud",
                attributes={
                    "arka.inference.backend": "vllm-cloud",
                    "arka.inference.reachable": cloud_reachable,
                    "gen_ai.request.model": cloud_model,
                    "http.method": "GET",
                    "http.request.method": "GET",
                    "http.url": cloud_health,
                    "url.full": cloud_health,
                    "http.status_code": 200 if cloud_reachable else 503,
                    "http.response.status_code": 200 if cloud_reachable else 503,
                },
            ) as cloud_span:
                if not cloud_reachable:
                    from arka.telemetry import mark_error

                    mark_error(cloud_span, "vllm-cloud unreachable")
                else:
                    from arka.telemetry import mark_ok

                    mark_ok(cloud_span)
            if record_inference_op is not None:
                record_inference_op(
                    backend="vllm-cloud",
                    operation="check",
                    success=cloud_reachable,
                )
            if emit_log is not None:
                emit_log(
                    f"vllm-cloud check reachable={cloud_reachable}",
                    level="info" if cloud_reachable else "warning",
                    attributes={
                        "arka.inference.backend": "vllm-cloud",
                        "arka.inference.reachable": cloud_reachable,
                    },
                )

        shutdown_tracing()
        print(f"trace\tsent ({_signoz_ui_url()}/traces)")
    return exit_code


def _cmd_demo_inference(args: argparse.Namespace) -> int:
    from arka.telemetry.signoz_demo import demo_inference_latency

    return demo_inference_latency(synthetic=bool(getattr(args, "synthetic", False)))


def _cmd_demo_rag(args: argparse.Namespace) -> int:
    from arka.telemetry.signoz_demo import demo_rag_cascade

    return demo_rag_cascade(synthetic=bool(getattr(args, "synthetic", False)))


def _cmd_demo_router(args: argparse.Namespace) -> int:
    from arka.telemetry.signoz_demo import demo_router_split

    return demo_router_split(synthetic=bool(getattr(args, "synthetic", False)))


def _cmd_demo_all(args: argparse.Namespace) -> int:
    from arka.telemetry.signoz_demo import demo_all

    return demo_all(synthetic=bool(getattr(args, "synthetic", False)))


def _cmd_demo_e2e(args: argparse.Namespace) -> int:
    from arka.telemetry.signoz_demo import demo_e2e_observability

    return demo_e2e_observability(synthetic=bool(getattr(args, "synthetic", True)))


def _cmd_demo_exceptions(args: argparse.Namespace) -> int:
    from arka.telemetry.signoz_demo import demo_exception_stacks

    return demo_exception_stacks(synthetic=bool(getattr(args, "synthetic", True)))


def _cmd_alert_create(args: argparse.Namespace) -> int:
    from arka.telemetry.signoz_alerts import cmd_alert_create

    return cmd_alert_create(args)


def _cmd_alert_list(args: argparse.Namespace) -> int:
    from arka.telemetry.signoz_alerts import cmd_alert_list

    return cmd_alert_list(args)


def _cmd_dashboard_install(args: argparse.Namespace) -> int:
    from arka.telemetry.signoz_dashboards import cmd_dashboard_install

    return cmd_dashboard_install(args)


def _cmd_dashboard_list(args: argparse.Namespace) -> int:
    from arka.telemetry.signoz_dashboards import cmd_dashboard_list

    return cmd_dashboard_list(args)


def _cmd_mcp_ping(_args: argparse.Namespace) -> int:
    from arka.integrations.signoz_mcp import signoz_mcp_ping

    try:
        result = signoz_mcp_ping()
    except RuntimeError as exc:
        print(f"error\t{exc}", file=sys.stderr)
        print("hint\tSet SIGNOZ_API_KEY or configure credentials on the SigNoz MCP server", file=sys.stderr)
        return 1
    print(f"server\t{result.get('server', 'signoz')}")
    print(f"url\t{result.get('url', '')}")
    print(f"session\t{result.get('session_id', '')}")
    print(f"tools\t{result.get('tool_count', 0)}")
    for name in result.get("tools") or []:
        print(f"tool\t{name}")
    return 0


def _cmd_mcp_tools(_args: argparse.Namespace) -> int:
    from arka.integrations.mcp_client import signoz_mcp_client

    try:
        client = signoz_mcp_client()
        tools = client.list_tools()
    except RuntimeError as exc:
        print(f"error\t{exc}", file=sys.stderr)
        return 1
    for tool in tools:
        print(f"{tool.name}\t{tool.description[:120]}")
    return 0


def _cmd_mcp_call(args: argparse.Namespace) -> int:
    import json

    from arka.integrations.signoz_mcp import query_signoz_mcp

    arguments: dict = {}
    if args.args:
        try:
            arguments = json.loads(args.args)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON for --args: {exc}", file=sys.stderr)
            return 1
    try:
        text = query_signoz_mcp(args.tool, arguments)
    except RuntimeError as exc:
        print(f"error\t{exc}", file=sys.stderr)
        return 1
    print(text)
    return 0


def _cmd_cursor_setup(args: argparse.Namespace) -> int:
    from arka.telemetry.signoz_cursor_setup import cmd_cursor_setup

    return cmd_cursor_setup(args)


def _cmd_autostart(args: argparse.Namespace) -> int:
    from arka.telemetry.signoz_autostart import cmd_autostart

    return cmd_autostart(args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="SigNoz helpers for Arka Track 01 — AI & Agent Observability",
        epilog=(
            "Full local stack: arka signoz setup (-y for unattended Docker + foundryctl + cast). "
            "Docker Desktop on macOS must be started manually on first install."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="Tracing + SigNoz UI + Docker/foundryctl status")
    p_status.set_defaults(func=cmd_status)

    p_setup = sub.add_parser(
        "setup",
        help="Install Docker + foundryctl if missing, gauge casting.yaml, deploy SigNoz",
    )
    p_setup.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Auto-approve installs and foundryctl cast (or ARKA_AUTO_INSTALL=1)",
    )
    p_setup.add_argument(
        "--skip-cast",
        action="store_true",
        help="Install prerequisites and run foundryctl gauge only",
    )
    p_setup.add_argument(
        "--check-only",
        action="store_true",
        help="Report prerequisite status and exit (no installs)",
    )
    p_setup.add_argument(
        "--autostart",
        action="store_true",
        help=(
            "Install login autostart after a successful cast (macOS launchd / Linux systemd; "
            "respects SIGNOZ_AUTOSTART in .env)"
        ),
    )
    p_setup.set_defaults(func=cmd_setup)

    p_autostart = sub.add_parser(
        "autostart",
        help="Install login autostart for the SigNoz Docker stack",
    )
    autostart_sub = p_autostart.add_subparsers(dest="autostart_action", required=True)
    p_autostart_install = autostart_sub.add_parser(
        "install",
        help="Enable SigNoz autostart on login (skipped when SIGNOZ_AUTOSTART=0 in .env)",
    )
    p_autostart_install.set_defaults(func=_cmd_autostart)
    p_autostart_status = autostart_sub.add_parser("status", help="Report autostart installation status")
    p_autostart_status.set_defaults(func=_cmd_autostart)
    p_autostart_uninstall = autostart_sub.add_parser("uninstall", help="Remove SigNoz autostart")
    p_autostart_uninstall.set_defaults(func=_cmd_autostart)

    p_demo = sub.add_parser("demo", help="Send a sample E2E agent trace (no LLM)")
    p_demo.set_defaults(func=cmd_demo)

    p_vllm = sub.add_parser("vllm", help="Check local vLLM and vLLM Cloud inference traces")
    p_vllm.set_defaults(func=cmd_vllm)

    p_demo_inf = sub.add_parser(
        "demo-inference",
        help="Demo: vLLM vs cloud API latency (Self-hosted Inference Track)",
    )
    p_demo_inf.add_argument(
        "--synthetic",
        action="store_true",
        help="Emit demo spans without live LLM calls",
    )
    p_demo_inf.set_defaults(func=_cmd_demo_inference)

    p_demo_rag = sub.add_parser(
        "demo-rag",
        help="Demo: Supermemory vector lookup + LLM cascade",
    )
    p_demo_rag.add_argument("--synthetic", action="store_true")
    p_demo_rag.set_defaults(func=_cmd_demo_rag)

    p_demo_router = sub.add_parser(
        "demo-router",
        help="Demo: symbolic vs semantic router split (Agent Observability)",
    )
    p_demo_router.add_argument("--synthetic", action="store_true")
    p_demo_router.set_defaults(func=_cmd_demo_router)

    p_demo_all = sub.add_parser("demo-scenarios", help="Run all hackathon demo scenarios")
    p_demo_all.add_argument("--synthetic", action="store_true")
    p_demo_all.set_defaults(func=_cmd_demo_all)

    p_demo_e2e = sub.add_parser(
        "demo-e2e",
        help="E2E trace + correlated logs + token analytics (four SigNoz pillars)",
    )
    p_demo_e2e.add_argument("--synthetic", action="store_true", default=True)
    p_demo_e2e.set_defaults(func=_cmd_demo_e2e)

    p_demo_exc = sub.add_parser(
        "demo-exceptions",
        help="Demo automatic exception recording with stack traces",
    )
    p_demo_exc.add_argument("--synthetic", action="store_true", default=True)
    p_demo_exc.set_defaults(func=_cmd_demo_exceptions)

    p_alert_create = sub.add_parser(
        "alert-create",
        help="Create a bundled SigNoz alert rule via API (requires SIGNOZ_API_KEY)",
    )
    p_alert_create.add_argument(
        "name",
        nargs="?",
        default="agent-error-spike",
        help="Alert slug from signoz/alerts/ (default: agent-error-spike)",
    )
    p_alert_create.add_argument("--all", action="store_true", help="Create every bundled alert rule")
    p_alert_create.add_argument("--dry-run", action="store_true", help="Print payload without POST")
    p_alert_create.add_argument("--replace", action="store_true", help="Recreate even if name exists")
    p_alert_create.set_defaults(func=_cmd_alert_create)

    p_alert_list = sub.add_parser("alert-list", help="List bundled and remote SigNoz alert rules")
    p_alert_list.set_defaults(func=_cmd_alert_list)

    p_dashboard = sub.add_parser("dashboard", help="Bundled Arka observability dashboards")
    dashboard_sub = p_dashboard.add_subparsers(dest="dashboard_action", required=True)
    p_dashboard_install = dashboard_sub.add_parser(
        "install",
        help="Install the Arka agent observability dashboard (requires SIGNOZ_API_KEY)",
    )
    p_dashboard_install.add_argument(
        "name",
        nargs="?",
        default="arka-agent-observability",
        help="Dashboard slug from signoz/dashboards/ (default: arka-agent-observability)",
    )
    p_dashboard_install.add_argument("--dry-run", action="store_true", help="Print payload summary without POST")
    p_dashboard_install.add_argument("--replace", action="store_true", help="Recreate even if title exists")
    p_dashboard_install.add_argument(
        "--alerts",
        action="store_true",
        help="Also create bundled observability alerts (agent-error-spike, skill-dispatch-failures, llm-p99-latency)",
    )
    p_dashboard_install.add_argument(
        "--mcp",
        action="store_true",
        help="Try SigNoz MCP import before HTTP API",
    )
    p_dashboard_install.set_defaults(func=_cmd_dashboard_install)
    p_dashboard_list = dashboard_sub.add_parser("list", help="List bundled and remote dashboards")
    p_dashboard_list.set_defaults(func=_cmd_dashboard_list)

    p_mcp = sub.add_parser("mcp", help="SigNoz MCP client (traced connect / tools / call)")
    mcp_sub = p_mcp.add_subparsers(dest="mcp_cmd", required=True)
    p_mcp_ping = mcp_sub.add_parser("ping", help="Connect and list available MCP tools")
    p_mcp_ping.set_defaults(func=_cmd_mcp_ping)
    p_mcp_tools = mcp_sub.add_parser("tools", help="List SigNoz MCP tools")
    p_mcp_tools.set_defaults(func=_cmd_mcp_tools)
    p_mcp_call = mcp_sub.add_parser("call", help="Call a SigNoz MCP tool")
    p_mcp_call.add_argument("tool", help="MCP tool name")
    p_mcp_call.add_argument("--args", default="", help='JSON object of tool arguments, e.g. \'{"limit":5}\'')
    p_mcp_call.set_defaults(func=_cmd_mcp_call)

    p_cursor = sub.add_parser(
        "cursor-setup",
        help="Print SigNoz Agent Skills + Cursor MCP setup steps (see CURSOR_AGENT_SKILLS.md)",
    )
    p_cursor.add_argument(
        "--write",
        action="store_true",
        help="Write .cursor/mcp.json from example (uses SIGNOZ_API_KEY from .env)",
    )
    p_cursor.set_defaults(func=_cmd_cursor_setup)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
