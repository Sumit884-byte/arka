import json
from pathlib import Path

from arka.agent.bi_dashboard import (
    build,
    export_json_spec,
    infer_panels,
    route_command,
    wants_bi_dashboard,
)
from arka.routing.symbolic import route_bi_dashboard, route_offline_extras


def _write_sales_csv(path: Path) -> None:
    path.write_text(
        "region,sales,units\n"
        "North,12000,400\n"
        "South,8500,280\n"
        "East,10200,330\n"
        "West,9100,295\n",
        encoding="utf-8",
    )


def test_wants_bi_dashboard():
    assert wants_bi_dashboard("generate bi dashboard from sales.csv")
    assert wants_bi_dashboard("create dashboard from data using reports.tsv")
    assert not wants_bi_dashboard("show my usage dashboard")


def test_route_command():
    route = route_command("build bi dashboard for sales by region from sales.csv")
    assert route.startswith("bi_dashboard ")
    assert "sales.csv" in route
    assert "--intent" in route


def test_symbolic_route():
    hit = route_bi_dashboard("generate bi dashboard from sales.csv")
    assert hit and hit.startswith("bi_dashboard")
    assert "sales.csv" in hit
    offline = route_offline_extras("create dashboard from sales.csv for revenue breakdown")
    assert offline and offline.startswith("bi_dashboard")


def test_infer_panels_sales_by_region():
    rows = [
        {"region": "North", "sales": "12000", "units": "400"},
        {"region": "South", "sales": "8500", "units": "280"},
    ]
    spec = infer_panels(rows, intent="sales by region", columns=["region", "sales", "units"])
    assert spec["label_column"] == "region"
    assert spec["value_column"] == "sales"
    types = [p["type"] for p in spec["panels"]]
    assert "kpi" in types
    assert any(t in {"bar", "pie", "line"} for t in types)


def test_build_html_and_json(tmp_path):
    csv_path = tmp_path / "sales.csv"
    _write_sales_csv(csv_path)
    out_html = tmp_path / "dash.html"
    result = build(csv_path, intent="sales by region", output=out_html, title="Sales dashboard")
    assert out_html.is_file()
    text = out_html.read_text(encoding="utf-8")
    assert "Sales dashboard" in text
    assert "region" in text.lower()
    json_path = Path(result["json"])
    assert json_path.is_file()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["title"] == "Sales dashboard"
    assert payload["panels"]
    assert export_json_spec(
        title="Sales dashboard",
        source=str(csv_path),
        intent="sales by region",
        spec={"panels": payload["panels"], "label_column": "region", "value_column": "sales"},
        html_path=str(out_html),
    )["templates"]["kpi_cards"]["type"] == "kpi"


def test_main_templates_flag(capsys):
    from arka.agent.bi_dashboard import main

    assert main(["--templates"]) == 0
    out = capsys.readouterr().out
    assert "kpi_cards" in out
